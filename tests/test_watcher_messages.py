from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from mt5_trigger.market_hours import (
    MarketHoursConfig,
    should_send_trade_alerts,
    should_send_weekly_summary,
)
from mt5_trigger.messages import (
    closed_message,
    near_trigger_message,
    triggered_message,
    weekly_summary_message,
)
from mt5_trigger.mt5.client import (
    DEAL_REASON_SL,
    DEAL_REASON_TP,
    OpenPosition,
    PendingOrder,
    SymbolTick,
    order_already_triggered,
)

NY = ZoneInfo("America/New_York")


def test_order_already_triggered_sell_stop() -> None:
    order = PendingOrder(
        ticket=1,
        symbol="XAUUSD.vx",
        order_type=5,
        order_type_label="SELL STOP",
        price_open=3963.3,
        volume=0.01,
        sl=0.0,
        tp=0.0,
        time_setup=0,
    )
    tick = SymbolTick(bid=3963.0, ask=3963.2, spread_points=20.0)
    assert order_already_triggered(order, tick) is True


def test_order_not_yet_triggered_sell_stop() -> None:
    order = PendingOrder(
        ticket=1,
        symbol="XAUUSD.vx",
        order_type=5,
        order_type_label="SELL STOP",
        price_open=3963.3,
        volume=0.01,
        sl=0.0,
        tp=0.0,
        time_setup=0,
    )
    tick = SymbolTick(bid=4063.77, ask=4063.97, spread_points=20.0)
    assert order_already_triggered(order, tick) is False


def test_near_trigger_message_format() -> None:
    order = PendingOrder(
        ticket=42,
        symbol="XAUUSD.vx",
        order_type=5,
        order_type_label="SELL STOP",
        price_open=3963.3,
        volume=0.01,
        sl=3950.0,
        tp=3980.0,
        time_setup=0,
    )
    message = near_trigger_message(order, current_price=3965.0, distance=1.7)
    assert "Order approaching trigger" in message
    assert "#42  XAUUSD.vx" in message
    assert "SELL STOP" in message


def test_triggered_message_format() -> None:
    position = OpenPosition(
        ticket=100,
        symbol="XAUUSD.vx",
        position_type=1,
        price_open=3963.3,
        volume=0.01,
        sl=3950.0,
        tp=3980.0,
        profit=-1.0,
        time=0,
        comment="",
    )
    message = triggered_message(position, pending_ticket=42)
    assert "Order triggered" in message
    assert "SELL" in message
    assert "From pending #42" in message


def test_closed_message_take_profit() -> None:
    message = closed_message(
        ticket=100,
        symbol="XAUUSD.vx",
        side="SELL",
        volume=0.01,
        open_price=3963.3,
        close_price=3950.0,
        net_profit=8.58,
        close_reason=DEAL_REASON_TP,
        sl=3950.0,
        tp=3950.0,
    )
    assert "Take profit hit" in message
    assert "$8.58" in message


def test_closed_message_stop_loss() -> None:
    message = closed_message(
        ticket=100,
        symbol="XAUUSD.vx",
        side="SELL",
        volume=0.01,
        open_price=3963.3,
        close_price=3980.0,
        net_profit=-12.0,
        close_reason=DEAL_REASON_SL,
        sl=3980.0,
        tp=3950.0,
    )
    assert "Stop loss hit" in message
    assert "Result: -$12.00" in message


def test_weekly_summary_message_format() -> None:
    message = weekly_summary_message(10, 6, 120.0, 4, 45.0)
    assert "Weekly trading summary" in message
    assert "Net profit: $75.00" in message


def test_trade_alerts_only_when_market_open() -> None:
    cfg = MarketHoursConfig()
    wednesday_noon = datetime(2026, 7, 8, 12, 0, tzinfo=NY)
    assert should_send_trade_alerts(cfg, wednesday_noon) is True


def test_weekly_summary_only_on_weekend_close() -> None:
    cfg = MarketHoursConfig()
    saturday_noon = datetime(2026, 7, 11, 12, 0, tzinfo=NY)
    assert should_send_weekly_summary(cfg, saturday_noon) is True

    wednesday_noon = datetime(2026, 7, 8, 12, 0, tzinfo=NY)
    assert should_send_weekly_summary(cfg, wednesday_noon) is False
