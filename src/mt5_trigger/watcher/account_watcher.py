from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from mt5_trigger.config import AccountConfig, AppConfig
from mt5_trigger.market_hours import (
    MarketHoursConfig,
    get_market_status,
    should_send_near_trigger_alerts,
    week_start_for,
)
from mt5_trigger.messages import (
    closed_loss_message,
    closed_profit_message,
    near_trigger_message,
    weekly_summary_message,
)
from mt5_trigger.mt5.client import (
    MT5Client,
    distance_to_trigger,
    order_matches_position,
)
from mt5_trigger.notify.openclaw import OpenClawNotifier
from mt5_trigger.storage.db import init_db
from mt5_trigger.storage.repository import EventRepository

logger = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")


class AccountWatcher:
    def __init__(self, account: AccountConfig, config: AppConfig) -> None:
        self.account = account
        self.config = config
        self.client = MT5Client(account)
        self.notifier = OpenClawNotifier(config.settings, account.whatsapp_target)
        self.market_cfg = MarketHoursConfig(
            rollover_blackout_minutes=config.settings.near_trigger.rollover_blackout_minutes,
            daily_rollover_blackout_minutes=config.settings.near_trigger.daily_rollover_blackout_minutes,
        )
        db_path = config.settings.db_path_resolved
        self.conn = init_db(db_path)
        self.repo = EventRepository(self.conn)

    def run(self) -> None:
        logger.info("Starting watcher for account %s", self.account.name)
        while True:
            try:
                self._poll_cycle()
            except Exception:
                logger.exception("Poll cycle error for %s", self.account.name)
                self.repo.update_watcher_status(
                    self.account.name, connected=False, last_error="poll_error"
                )
            time.sleep(self.config.settings.poll_interval_seconds)

    def _poll_cycle(self) -> None:
        if not self.client.connected:
            if not self.client.connect():
                self.repo.update_watcher_status(
                    self.account.name, connected=False, last_error="mt5_connect_failed"
                )
                return

        self.repo.update_watcher_status(self.account.name, connected=True)
        market = get_market_status(self.market_cfg)

        self._check_weekly_summary(market)
        self._check_pending_near_triggers(market)
        self._sync_triggered_positions()
        self._check_closed_positions()

    def _near_threshold_price(self, symbol: str, spread_points: float) -> float:
        point = self.client.get_point(symbol)
        # 1 pip = 10 points on 5-digit symbols
        min_price = self.config.settings.near_trigger.min_pips * 10 * point
        spread_price = (
            spread_points * self.config.settings.near_trigger.spread_multiplier * point
        )
        return max(min_price, spread_price)

    def _check_pending_near_triggers(self, market) -> None:
        if not should_send_near_trigger_alerts(self.market_cfg, market.now_et):
            return

        orders = self.client.get_pending_orders()
        active_tickets = {o.ticket for o in orders}
        self.repo.prune_stale_pending(self.account.name, active_tickets)

        for order in orders:
            if not self.client.symbol_trade_allowed(order.symbol):
                continue

            tick = self.client.get_tick(order.symbol)
            if tick is None:
                continue

            distance = distance_to_trigger(order, tick)
            threshold = self._near_threshold_price(order.symbol, tick.spread_points)
            in_zone = distance <= threshold

            if in_zone:
                if self.repo.get_pending_near_alert_sent(self.account.name, order.ticket):
                    continue
                if self.repo.event_exists(self.account.name, "near_trigger", order.ticket):
                    self.repo.set_pending_near_alert(
                        self.account.name, order.ticket, True, distance
                    )
                    continue

                current = tick.ask if order.order_type in (2, 4, 6) else tick.bid
                msg = near_trigger_message(
                    order.symbol,
                    order.order_type_label,
                    order.price_open,
                    current,
                )
                if self.notifier.send(msg):
                    self.repo.record_event(
                        self.account.name,
                        "near_trigger",
                        msg,
                        ticket=order.ticket,
                        symbol=order.symbol,
                        open_price=order.price_open,
                    )
                    self.repo.set_pending_near_alert(
                        self.account.name, order.ticket, True, distance
                    )
            else:
                if self.repo.get_pending_near_alert_sent(self.account.name, order.ticket):
                    self.repo.set_pending_near_alert(
                        self.account.name, order.ticket, False, distance
                    )

    def _sync_triggered_positions(self) -> None:
        positions = self.client.get_positions()
        open_tickets = {p.ticket for p in positions}
        tracked = self.repo.get_tracked_positions(self.account.name)
        tracked_tickets = {t["ticket"] for t in tracked}

        pending_orders = {o.ticket: o for o in self.client.get_pending_orders()}

        for pos in positions:
            if pos.ticket in tracked_tickets:
                continue
            pending_ticket = None
            for ticket, order in list(pending_orders.items()):
                if order_matches_position(order, pos):
                    pending_ticket = ticket
                    self.repo.clear_pending_state(self.account.name, ticket)
                    break
            self.repo.track_position(
                self.account.name,
                pos.ticket,
                pos.symbol,
                pos.price_open,
                pending_ticket,
            )
            logger.info(
                "Tracking new position %s %s @ %s",
                pos.ticket,
                pos.symbol,
                pos.price_open,
            )

    def _check_closed_positions(self) -> None:
        positions = self.client.get_positions()
        open_tickets = {p.ticket for p in positions}
        tracked = self.repo.get_tracked_positions(self.account.name)

        for t in tracked:
            ticket = t["ticket"]
            if ticket in open_tickets:
                continue

            deals = self.client.get_position_deals(ticket)
            close_deals = [d for d in deals if d.ticket]
            if not close_deals:
                self.repo.remove_tracked_position(self.account.name, ticket)
                continue

            close_deal = max(close_deals, key=lambda d: d.time)
            net = sum(d.net_profit for d in deals)
            open_price = t["open_price"]
            close_price = close_deal.price

            if self.repo.event_exists(self.account.name, "closed", ticket):
                self.repo.remove_tracked_position(self.account.name, ticket)
                continue

            if net > 0:
                msg = closed_profit_message(open_price, close_price, net)
            else:
                msg = closed_loss_message(open_price, close_price, abs(net))

            if self.notifier.send(msg):
                self.repo.record_event(
                    self.account.name,
                    "closed",
                    msg,
                    ticket=ticket,
                    symbol=t["symbol"],
                    open_price=open_price,
                    close_price=close_price,
                    profit=net,
                )
            self.repo.remove_tracked_position(self.account.name, ticket)

    def _check_weekly_summary(self, market) -> None:
        if market.is_open or market.reason != "market_closed_weekend":
            return

        now_et = market.now_et
        if now_et.weekday() != 5:  # Saturday — right after Friday close
            return

        week_start = week_start_for(now_et)
        if self.repo.weekly_summary_sent(self.account.name, week_start):
            return

        week_open = datetime.fromisoformat(week_start).replace(tzinfo=NY)
        week_close = week_open + timedelta(days=5)
        deals = self.client.get_weekly_closed_deals(week_open, week_close)

        if deals:
            profits = [d.net_profit for d in deals]
            wins = sum(1 for p in profits if p > 0)
            losses = sum(1 for p in profits if p <= 0)
            profit_sum = sum(p for p in profits if p > 0)
            loss_sum = sum(abs(p) for p in profits if p <= 0)
            total = len(deals)
        else:
            stats = self.repo.get_week_stats_from_events(self.account.name, week_start)
            total = stats["total_trades"]
            wins = stats["wins"]
            losses = stats["losses"]
            profit_sum = stats["profit_sum"]
            loss_sum = stats["loss_sum"]

        if total == 0:
            self.repo.mark_weekly_summary_sent(self.account.name, week_start)
            return

        msg = weekly_summary_message(total, wins, profit_sum, losses, loss_sum)
        if self.notifier.send(msg):
            self.repo.record_event(
                self.account.name,
                "weekly_summary",
                msg,
                ticket=None,
            )
            self.repo.mark_weekly_summary_sent(self.account.name, week_start)


def run_account_watcher(account: AccountConfig, config: AppConfig) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    watcher = AccountWatcher(account, config)
    watcher.run()
