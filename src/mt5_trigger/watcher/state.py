from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TrackedPending:
    ticket: int
    symbol: str
    order_type_label: str
    price_open: float
    near_alert_sent: bool = False


@dataclass
class TrackedPosition:
    ticket: int
    symbol: str
    open_price: float
    pending_ticket: int | None = None


@dataclass
class WatcherState:
    pending_orders: dict[int, TrackedPending] = field(default_factory=dict)
    positions: dict[int, TrackedPosition] = field(default_factory=dict)
