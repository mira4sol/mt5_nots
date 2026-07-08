from __future__ import annotations

from collections import namedtuple
from typing import Any

Order = namedtuple(
    "Order",
    [
        "ticket",
        "symbol",
        "type",
        "price_open",
        "volume_current",
        "sl",
        "tp",
        "time_setup",
    ],
)
Position = namedtuple(
    "Position",
    ["ticket", "symbol", "type", "price_open", "volume", "sl", "tp", "profit", "time", "comment"],
)
Tick = namedtuple("Tick", ["bid", "ask"])
SymbolInfo = namedtuple("SymbolInfo", ["point", "trade_mode"])
Deal = namedtuple(
    "Deal",
    [
        "ticket",
        "position_id",
        "symbol",
        "price",
        "profit",
        "swap",
        "commission",
        "time",
        "entry",
        "reason",
    ],
)


class MockMT5:
    """Minimal MT5 stub for offline development without mt5-mac-bridge."""

    def initialize(self, **kwargs: Any) -> bool:
        return True

    def shutdown(self) -> None:
        pass

    def last_error(self) -> tuple[int, str]:
        return (0, "mock ok")

    def orders_get(self) -> list[Order]:
        return []

    def positions_get(self) -> list[Position]:
        return []

    def symbol_select(self, symbol: str, enable: bool) -> bool:
        return True

    def symbol_info_tick(self, symbol: str) -> Tick | None:
        return Tick(bid=1.10000, ask=1.10010)

    def symbol_info(self, symbol: str) -> SymbolInfo:
        return SymbolInfo(point=0.00001, trade_mode=4)

    def history_deals_get(
        self,
        date_from: Any = None,
        date_to: Any = None,
        *,
        position: int | None = None,
        ticket: int | None = None,
        group: str | None = None,
    ) -> list[Deal]:
        return []
