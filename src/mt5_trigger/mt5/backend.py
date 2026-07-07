from __future__ import annotations

import logging
import platform
import socket
from typing import Any

from mt5_trigger.config import AccountConfig, Mt5Backend

logger = logging.getLogger(__name__)

# MT5 order type constants (mirrors MetaTrader5)
ORDER_TYPE_BUY_LIMIT = 2
ORDER_TYPE_SELL_LIMIT = 3
ORDER_TYPE_BUY_STOP = 4
ORDER_TYPE_SELL_STOP = 5
ORDER_TYPE_BUY_STOP_LIMIT = 6
ORDER_TYPE_SELL_STOP_LIMIT = 7

PENDING_ORDER_TYPES = {
    ORDER_TYPE_BUY_LIMIT,
    ORDER_TYPE_SELL_LIMIT,
    ORDER_TYPE_BUY_STOP,
    ORDER_TYPE_SELL_STOP,
    ORDER_TYPE_BUY_STOP_LIMIT,
    ORDER_TYPE_SELL_STOP_LIMIT,
}

ORDER_TYPE_LABELS = {
    ORDER_TYPE_BUY_LIMIT: "BUY LIMIT",
    ORDER_TYPE_SELL_LIMIT: "SELL LIMIT",
    ORDER_TYPE_BUY_STOP: "BUY STOP",
    ORDER_TYPE_SELL_STOP: "SELL STOP",
    ORDER_TYPE_BUY_STOP_LIMIT: "BUY STOP LIMIT",
    ORDER_TYPE_SELL_STOP_LIMIT: "SELL STOP LIMIT",
}

POSITION_TYPE_BUY = 0
POSITION_TYPE_SELL = 1


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def resolve_backend(account: AccountConfig) -> Mt5Backend:
    backend = account.mt5_backend
    if backend != "auto":
        return backend
    if platform.system() == "Windows":
        return "native"
    # Mac/Linux: always use bridge for auto. Mock is opt-in only (mt5_backend: mock).
    return "bridge"


def load_mt5_module(backend: Mt5Backend, account: AccountConfig) -> Any:
    if backend == "mock":
        try:
            import mt5_mac_bridge as mt5b

            mt5b.init(backend="mock")
            return mt5b
        except ImportError:
            from mt5_trigger.mt5.mock import MockMT5

            return MockMT5()

    if backend == "bridge":
        import mt5_mac_bridge as mt5b

        mt5b.init(
            backend="bridge",
            host=account.bridge_host,
            port=account.bridge_port,
        )
        return mt5b

    if backend == "native":
        import MetaTrader5 as mt5

        return mt5

    raise ValueError(f"Unknown MT5 backend: {backend}")
