from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from mt5_trigger.config import AccountConfig, AppConfig
from mt5_trigger.market_hours import (
    MarketHoursConfig,
    get_market_status,
    should_send_trade_alerts,
    should_send_weekly_summary,
    week_start_for,
)
from mt5_trigger.messages import (
    closed_message,
    near_trigger_message,
    triggered_message,
    weekly_summary_message,
)
from mt5_trigger.mt5.client import (
    MT5Client,
    OpenPosition,
    distance_to_trigger,
    is_buy_order,
    order_already_triggered,
    order_matches_position,
    position_side_label,
)
from mt5_trigger.notify.async_queue import AsyncNotifier
from mt5_trigger.notify.openclaw import OpenClawNotifier
from mt5_trigger.storage.db import init_db
from mt5_trigger.storage.repository import EventRepository

logger = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")
RECOVERY_LOOKBACK = timedelta(hours=24)


class AccountWatcher:
    def __init__(self, account: AccountConfig, config: AppConfig) -> None:
        self.account = account
        self.config = config
        self.client = MT5Client(account)
        base_notifier = OpenClawNotifier(config.settings, account.whatsapp_target)
        self.notifier = AsyncNotifier(base_notifier)
        self.market_cfg = MarketHoursConfig(
            rollover_blackout_minutes=config.settings.near_trigger.rollover_blackout_minutes,
            daily_rollover_blackout_minutes=config.settings.near_trigger.daily_rollover_blackout_minutes,
        )
        db_path = config.settings.db_path_resolved
        self.conn = init_db(db_path)
        self.repo = EventRepository(self.conn)
        self._bootstrapped = False

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
            self._bootstrapped = False

        self.repo.update_watcher_status(self.account.name, connected=True)
        market = get_market_status(self.market_cfg)

        if should_send_weekly_summary(self.market_cfg, market.now_et):
            self._check_weekly_summary(market)

        if not self._bootstrapped:
            self._bootstrap_open_positions()
            self._bootstrapped = True

        trade_alerts = should_send_trade_alerts(self.market_cfg, market.now_et)
        positions = self.client.get_positions()
        pending_orders = self.client.get_pending_orders()

        # Detect fills and closes before proximity alerts to avoid stale messages.
        self._sync_triggered_positions(positions, pending_orders, trade_alerts)
        self._check_closed_positions(positions, trade_alerts)
        if trade_alerts:
            self._recover_missed_closes(market.now_et)
            self._check_pending_near_triggers(pending_orders, positions)

    def _near_threshold_price(self, symbol: str, spread_points: float) -> float:
        point = self.client.get_point(symbol)
        min_price = self.config.settings.near_trigger.min_pips * 10 * point
        spread_price = (
            spread_points * self.config.settings.near_trigger.spread_multiplier * point
        )
        return max(min_price, spread_price)

    def _bootstrap_open_positions(self) -> None:
        for pos in self.client.get_positions():
            if self.repo.event_exists(self.account.name, "triggered", pos.ticket):
                self._ensure_tracked(pos, pending_ticket=None)
                continue
            self._register_triggered_position(pos, pending_ticket=None, notify=False)

    def _ensure_tracked(
        self,
        pos: OpenPosition,
        *,
        pending_ticket: int | None,
    ) -> None:
        tracked = {
            row["ticket"]: row
            for row in self.repo.get_tracked_positions(self.account.name)
        }
        if pos.ticket in tracked:
            return
        self.repo.track_position(
            self.account.name,
            pos.ticket,
            pos.symbol,
            pos.price_open,
            pending_ticket,
            position_type=pos.position_type,
            volume=pos.volume,
            sl=pos.sl,
            tp=pos.tp,
        )

    def _register_triggered_position(
        self,
        pos: OpenPosition,
        *,
        pending_ticket: int | None,
        notify: bool,
    ) -> None:
        self._ensure_tracked(pos, pending_ticket=pending_ticket)
        if self.repo.event_exists(self.account.name, "triggered", pos.ticket):
            return

        msg = triggered_message(pos, pending_ticket=pending_ticket)
        if not notify:
            self.repo.record_event(
                self.account.name,
                "triggered",
                msg,
                ticket=pos.ticket,
                symbol=pos.symbol,
                open_price=pos.price_open,
            )
            return

        def on_success() -> None:
            self.repo.record_event(
                self.account.name,
                "triggered",
                msg,
                ticket=pos.ticket,
                symbol=pos.symbol,
                open_price=pos.price_open,
            )

        self.notifier.send(msg, on_success=on_success)
        logger.info("Triggered alert queued for position %s %s", pos.ticket, pos.symbol)

    def _check_pending_near_triggers(
        self,
        orders: list,
        positions: list[OpenPosition],
    ) -> None:
        active_tickets = {o.ticket for o in orders}
        self.repo.prune_stale_pending(self.account.name, active_tickets)

        open_by_symbol_side = {
            (p.symbol, p.position_type) for p in positions
        }

        for order in orders:
            if not self.client.symbol_trade_allowed(order.symbol):
                continue

            side = 0 if is_buy_order(order.order_type) else 1
            if (order.symbol, side) in open_by_symbol_side:
                continue

            tick = self.client.get_tick(order.symbol)
            if tick is None:
                continue

            if order_already_triggered(order, tick):
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

                current = tick.ask if is_buy_order(order.order_type) else tick.bid
                msg = near_trigger_message(
                    order,
                    current_price=current,
                    distance=distance,
                )

                def on_success(
                    ticket: int = order.ticket,
                    symbol: str = order.symbol,
                    open_price: float = order.price_open,
                    message: str = msg,
                ) -> None:
                    self.repo.record_event(
                        self.account.name,
                        "near_trigger",
                        message,
                        ticket=ticket,
                        symbol=symbol,
                        open_price=open_price,
                    )
                    self.repo.set_pending_near_alert(
                        self.account.name, ticket, True, distance
                    )

                self.notifier.send(msg, on_success=on_success)
            elif self.repo.get_pending_near_alert_sent(self.account.name, order.ticket):
                self.repo.set_pending_near_alert(
                    self.account.name, order.ticket, False, distance
                )

    def _sync_triggered_positions(
        self,
        positions: list[OpenPosition],
        pending_orders: list,
        trade_alerts: bool,
    ) -> None:
        tracked = self.repo.get_tracked_positions(self.account.name)
        tracked_tickets = {t["ticket"] for t in tracked}
        pending_by_ticket = {o.ticket: o for o in pending_orders}

        for pos in positions:
            if pos.ticket in tracked_tickets:
                continue

            pending_ticket = None
            for ticket, order in list(pending_by_ticket.items()):
                if order_matches_position(order, pos):
                    pending_ticket = ticket
                    self.repo.clear_pending_state(self.account.name, ticket)
                    break

            self._register_triggered_position(
                pos,
                pending_ticket=pending_ticket,
                notify=trade_alerts,
            )

    def _check_closed_positions(
        self,
        positions: list[OpenPosition],
        trade_alerts: bool,
    ) -> None:
        open_tickets = {p.ticket for p in positions}
        tracked = self.repo.get_tracked_positions(self.account.name)

        for t in tracked:
            ticket = t["ticket"]
            if ticket in open_tickets:
                continue
            if self.repo.event_exists(self.account.name, "closed", ticket):
                self.repo.remove_tracked_position(self.account.name, ticket)
                continue

            deals = self.client.get_position_deals(ticket)
            if not deals:
                logger.debug(
                    "Position %s closed but deals not ready yet; will retry",
                    ticket,
                )
                continue

            self._notify_closed_position(t, deals, trade_alerts)

    def _recover_missed_closes(self, now_et: datetime) -> None:
        since = now_et - RECOVERY_LOOKBACK
        grouped = self.client.get_recent_closed_positions(since, now_et)
        if not grouped:
            return

        for position_id, deals in grouped.items():
            if self.repo.event_exists(self.account.name, "closed", position_id):
                continue

            tracked_rows = self.repo.get_tracked_positions(self.account.name)
            tracked = next(
                (row for row in tracked_rows if row["ticket"] == position_id),
                None,
            )
            if tracked is None:
                tracked = {
                    "ticket": position_id,
                    "symbol": deals[0].symbol,
                    "open_price": deals[0].price,
                    "position_type": 0,
                    "volume": 0.0,
                    "sl": 0.0,
                    "tp": 0.0,
                }
            self._notify_closed_position(tracked, deals, trade_alerts=True)

    def _notify_closed_position(
        self,
        tracked: dict,
        deals: list,
        trade_alerts: bool,
    ) -> None:
        ticket = tracked["ticket"]
        if self.repo.event_exists(self.account.name, "closed", ticket):
            self.repo.remove_tracked_position(self.account.name, ticket)
            return

        close_deals = [d for d in deals if d.ticket]
        if not close_deals:
            return

        close_deal = max(close_deals, key=lambda d: d.time)
        net = sum(d.net_profit for d in deals)
        side = position_side_label(tracked.get("position_type", 0))
        msg = closed_message(
            ticket=ticket,
            symbol=tracked["symbol"],
            side=side,
            volume=float(tracked.get("volume") or 0.0),
            open_price=float(tracked["open_price"]),
            close_price=close_deal.price,
            net_profit=net,
            close_reason=close_deal.reason,
            sl=float(tracked.get("sl") or 0.0),
            tp=float(tracked.get("tp") or 0.0),
        )

        if not trade_alerts:
            self.repo.record_event(
                self.account.name,
                "closed",
                msg,
                ticket=ticket,
                symbol=tracked["symbol"],
                open_price=float(tracked["open_price"]),
                close_price=close_deal.price,
                profit=net,
            )
            self.repo.remove_tracked_position(self.account.name, ticket)
            logger.info(
                "Recorded close for %s without alert (market closed; stats only)",
                ticket,
            )
            return

        def on_success() -> None:
            self.repo.record_event(
                self.account.name,
                "closed",
                msg,
                ticket=ticket,
                symbol=tracked["symbol"],
                open_price=float(tracked["open_price"]),
                close_price=close_deal.price,
                profit=net,
            )
            self.repo.remove_tracked_position(self.account.name, ticket)

        self.notifier.send(msg, on_success=on_success)

    def _check_weekly_summary(self, market) -> None:
        now_et = market.now_et
        if now_et.weekday() != 5:
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

        def on_success() -> None:
            self.repo.record_event(
                self.account.name,
                "weekly_summary",
                msg,
                ticket=None,
            )
            self.repo.mark_weekly_summary_sent(self.account.name, week_start)

        self.notifier.send(msg, on_success=on_success)


def run_account_watcher(account: AccountConfig, config: AppConfig) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    watcher = AccountWatcher(account, config)
    watcher.run()
