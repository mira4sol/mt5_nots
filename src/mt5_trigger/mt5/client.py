from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from mt5_trigger.config import AccountConfig, normalize_account_config
from mt5_trigger.mt5.backend import (
    ORDER_TYPE_LABELS,
    PENDING_ORDER_TYPES,
    POSITION_TYPE_BUY,
    POSITION_TYPE_SELL,
    bridge_protocol_hint,
    load_mt5_module,
    resolve_backend,
    resolve_bridge_client,
)

logger = logging.getLogger(__name__)


@dataclass
class PendingOrder:
    ticket: int
    symbol: str
    order_type: int
    order_type_label: str
    price_open: float
    volume: float
    sl: float
    tp: float
    time_setup: int


@dataclass
class OpenPosition:
    ticket: int
    symbol: str
    position_type: int
    price_open: float
    volume: float
    sl: float
    tp: float
    profit: float
    time: int
    comment: str


@dataclass
class ClosedDeal:
    ticket: int
    position_id: int
    symbol: str
    price: float
    profit: float
    swap: float
    commission: float
    time: int

    @property
    def net_profit(self) -> float:
        return self.profit + self.swap + self.commission


@dataclass
class SymbolTick:
    bid: float
    ask: float
    spread_points: float


class MT5Client:
    def __init__(self, account: AccountConfig) -> None:
        self.account = normalize_account_config(account)
        self.backend = resolve_backend(self.account)
        self._mt5: Any = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        try:
            self._mt5 = load_mt5_module(self.backend, self.account)
        except ImportError as exc:
            bridge_client = resolve_bridge_client(self.account)
            logger.error(
                "MT5 import failed for %s (%s): %s",
                self.account.name,
                self.backend,
                exc,
            )
            if bridge_client == "mt5linux" and "mt5linux" in str(exc):
                logger.error(
                    "Install mt5linux in this venv: .venv/bin/pip install mt5linux "
                    "or run: make install-prod"
                )
            self._connected = False
            return False
        except Exception as exc:
            hint = bridge_protocol_hint(exc)
            logger.error(
                "MT5 bridge setup failed for %s: %s",
                self.account.name,
                exc,
            )
            if hint:
                logger.error(hint)
            self._connected = False
            return False

        kwargs: dict[str, Any] = {
            "login": int(self.account.login),
            "password": self.account.password,
            "server": self.account.server,
        }
        if self.account.terminal_path:
            kwargs["path"] = self.account.terminal_path

        ok = self._mt5.initialize(**kwargs)
        if not ok:
            err = self._mt5.last_error()
            logger.error(
                "MT5 initialize failed for %s: %s (backend=%s)",
                self.account.name,
                err,
                self.backend,
            )
            self._connected = False
            return False

        self._connected = True
        logger.info(
            "Connected to MT5 account %s (%s) via %s",
            self.account.name,
            self.account.login,
            self.backend,
        )
        return True

    def disconnect(self) -> None:
        if self._mt5 is not None:
            try:
                self._mt5.shutdown()
            except Exception:
                logger.exception("Error shutting down MT5 for %s", self.account.name)
        self._connected = False

    def get_pending_orders(self) -> list[PendingOrder]:
        self._ensure_connected()
        orders = self._mt5.orders_get()
        if orders is None:
            return []
        result: list[PendingOrder] = []
        for o in orders:
            if o.type not in PENDING_ORDER_TYPES:
                continue
            result.append(
                PendingOrder(
                    ticket=o.ticket,
                    symbol=o.symbol,
                    order_type=o.type,
                    order_type_label=ORDER_TYPE_LABELS.get(o.type, f"TYPE_{o.type}"),
                    price_open=o.price_open,
                    volume=o.volume_current,
                    sl=o.sl,
                    tp=o.tp,
                    time_setup=o.time_setup,
                )
            )
        return result

    def get_positions(self) -> list[OpenPosition]:
        self._ensure_connected()
        positions = self._mt5.positions_get()
        if positions is None:
            return []
        return [
            OpenPosition(
                ticket=p.ticket,
                symbol=p.symbol,
                position_type=p.type,
                price_open=p.price_open,
                volume=p.volume,
                sl=p.sl,
                tp=p.tp,
                profit=p.profit,
                time=p.time,
                comment=p.comment or "",
            )
            for p in positions
        ]

    def get_tick(self, symbol: str) -> SymbolTick | None:
        self._ensure_connected()
        if not self._mt5.symbol_select(symbol, True):
            logger.warning("Could not select symbol %s", symbol)
        tick = self._mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        info = self._mt5.symbol_info(symbol)
        point = info.point if info else 0.00001
        spread_points = (tick.ask - tick.bid) / point if point else 0
        return SymbolTick(bid=tick.bid, ask=tick.ask, spread_points=spread_points)

    def get_point(self, symbol: str) -> float:
        self._ensure_connected()
        info = self._mt5.symbol_info(symbol)
        if info is None:
            return 0.00001
        return info.point

    def symbol_trade_allowed(self, symbol: str) -> bool:
        self._ensure_connected()
        info = self._mt5.symbol_info(symbol)
        if info is None:
            return True
        # SYMBOL_TRADE_MODE_FULL = 4
        return getattr(info, "trade_mode", 4) == 4

    def get_position_deals(self, position_ticket: int) -> list[ClosedDeal]:
        self._ensure_connected()
        now = datetime.now(timezone.utc)
        date_from = now - timedelta(days=30)
        self._mt5.history_select(date_from, now)
        deals = self._mt5.history_deals_get(position=position_ticket)
        if deals is None:
            return []
        return [
            ClosedDeal(
                ticket=d.ticket,
                position_id=d.position_id,
                symbol=d.symbol,
                price=d.price,
                profit=d.profit,
                swap=d.swap,
                commission=d.commission,
                time=d.time,
            )
            for d in deals
        ]

    def get_weekly_closed_deals(self, week_start: datetime, week_end: datetime) -> list[ClosedDeal]:
        self._ensure_connected()
        self._mt5.history_select(week_start, week_end)
        deals = self._mt5.history_deals_get()
        if deals is None:
            return []
        # Only exit deals (DEAL_ENTRY_OUT = 1)
        return [
            ClosedDeal(
                ticket=d.ticket,
                position_id=d.position_id,
                symbol=d.symbol,
                price=d.price,
                profit=d.profit,
                swap=d.swap,
                commission=d.commission,
                time=d.time,
            )
            for d in deals
            if d.entry == 1
        ]

    def _ensure_connected(self) -> None:
        if not self._connected or self._mt5 is None:
            raise RuntimeError(f"MT5 not connected for account {self.account.name}")


def is_buy_order(order_type: int) -> bool:
    return order_type in (2, 4, 6)


def is_sell_order(order_type: int) -> bool:
    return order_type in (3, 5, 7)


def order_matches_position(order: PendingOrder, position: OpenPosition) -> bool:
    if order.symbol != position.symbol:
        return False
    if is_buy_order(order.order_type) and position.position_type == POSITION_TYPE_BUY:
        return True
    if is_sell_order(order.order_type) and position.position_type == POSITION_TYPE_SELL:
        return True
    return False


def distance_to_trigger(order: PendingOrder, tick: SymbolTick) -> float:
    """Distance in price units to activation."""
    if is_buy_order(order.order_type):
        ref = tick.ask
        return abs(order.price_open - ref)
    ref = tick.bid
    return abs(order.price_open - ref)
