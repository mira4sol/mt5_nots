from __future__ import annotations

from unittest.mock import MagicMock

from mt5_trigger.commands.service import CommandService
from mt5_trigger.config import AppConfig, AppSettings, CommandsSettings


def _minimal_config() -> AppConfig:
    return AppConfig(
        settings=AppSettings(commands=CommandsSettings(enabled=True)),
        accounts=[],
    )


def test_parse_guide_and_help_aliases() -> None:
    service = CommandService(_minimal_config())
    assert service.parse_command("/guide") == "guide"
    assert service.parse_command("/help") == "guide"
    assert service.parse_command("/mt5help") == "guide"


def test_execute_guide_without_mt5() -> None:
    service = CommandService(_minimal_config())
    account = MagicMock(name="valetax_main")
    message = service._execute("guide", account)
    assert "MT5 Trigger" in message
    assert "/orders" in message
    assert "/guide" in message


def test_list_commands_unique() -> None:
    service = CommandService(_minimal_config())
    commands = service.list_commands()
    assert commands.count("/guide") == 1
    assert "/orders" in commands


def test_run_guide_via_api_normalization() -> None:
    from mt5_trigger.api.app import _normalize_command_name

    assert _normalize_command_name("guide") == "guide"
    assert _normalize_command_name("help") == "guide"
    assert _normalize_command_name("mt5help") == "guide"


def test_fetch_mt5_command_uses_send_false() -> None:
    forward_ts = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "openclaw-plugins/mt5-whatsapp-commands/forward.ts"
    ).read_text(encoding="utf-8")
    assert "send=false" in forward_ts
    assert "fetchMt5Command" in forward_ts


def test_orders_message_includes_symbol_price() -> None:
    from mt5_trigger.commands import format as cmd_format
    from mt5_trigger.mt5.client import PendingOrder, SymbolTick

    orders = [
        PendingOrder(
            ticket=1,
            symbol="XAUUSD.vx",
            order_type=5,
            order_type_label="SELL STOP",
            price_open=2650.0,
            volume=0.01,
            sl=0.0,
            tp=0.0,
            time_setup=0,
        )
    ]
    tick = SymbolTick(bid=2649.5, ask=2649.7, spread_points=20.0)
    message = cmd_format.orders_message(orders, symbol="XAUUSD.vx", tick=tick)
    assert message.startswith("XAUUSD.vx: bid 2649.50000 · ask 2649.70000")
    assert "Pending orders (1):" in message


def test_cts_message_includes_symbol_price() -> None:
    from mt5_trigger.commands import format as cmd_format
    from mt5_trigger.mt5.client import OpenPosition, SymbolTick

    positions = [
        OpenPosition(
            ticket=10,
            symbol="XAUUSD.vx",
            position_type=0,
            price_open=2640.0,
            volume=0.01,
            sl=2630.0,
            tp=2660.0,
            profit=12.5,
            time=0,
            comment="",
        )
    ]
    tick = SymbolTick(bid=2650.0, ask=2650.2, spread_points=20.0)
    message = cmd_format.cts_message(positions, ticks={"XAUUSD.vx": tick})
    assert "XAUUSD.vx: bid 2650.00000 · ask 2650.20000" in message
    assert "now=2650.20000" in message

