from __future__ import annotations

from unittest.mock import MagicMock, patch

from mt5_trigger.commands.service import CommandService
from mt5_trigger.config import (
    AppConfig,
    AppSettings,
    CommandsSettings,
    phones_match,
    whatsapp_admin_variants,
)


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


def test_parse_chart_command() -> None:
    service = CommandService(_minimal_config())
    assert service.parse_command("/chart") == "chart"


def test_mt5_datetime_strips_timezone_for_bridge() -> None:
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from mt5_trigger.mt5.client import _mt5_datetime

    aware = datetime(2026, 7, 8, 10, 53, 15, tzinfo=ZoneInfo("America/New_York"))
    naive_utc = _mt5_datetime(aware)
    assert naive_utc.tzinfo is None
    assert naive_utc.hour in {14, 15}  # depends on DST; just ensure converted


def test_guide_lists_chart_command() -> None:
    service = CommandService(_minimal_config())
    account = MagicMock(name="valetax_main")
    message = service._execute("guide", account)
    assert "/chart" in message


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


def test_fetch_mt5_command_sends_with_reply_to() -> None:
    forward_ts = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "openclaw-plugins/mt5-whatsapp-commands/forward.ts"
    ).read_text(encoding="utf-8")
    index_ts = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "openclaw-plugins/mt5-whatsapp-commands/index.ts"
    ).read_text(encoding="utf-8")
    assert "send: true" in index_ts
    assert 'params.set("reply_to"' in forward_ts
    assert 'params.set("target"' in forward_ts
    assert "body.sent === true" in forward_ts
    assert "WhatsApp delivery failed" in index_ts
    assert "message_received" in index_ts
    assert "suppressReply: true" in index_ts


def test_run_command_dedupes_reply_to_delivery(tmp_path) -> None:
    from mt5_trigger.config import AccountConfig, AppConfig, AppSettings, CommandsSettings

    config = AppConfig(
        settings=AppSettings(
            commands=CommandsSettings(enabled=True),
            db_path=str(tmp_path / "dedupe.db"),
        ),
        accounts=[
            AccountConfig(
                name="valetax_main",
                login="1",
                password="x",
                server="MetaQuotes-Demo",
                whatsapp_target="120363428584387160@g.us",
            )
        ],
    )
    service = CommandService(config)
    account = config.accounts[0]

    with patch.object(service, "_execute", return_value="No open positions."):
        with patch.object(service, "_send_reply", return_value=True) as send_reply:
            first = service.run_command(
                "positions",
                account_name=account.name,
                send=True,
                target=account.whatsapp_target,
                reply_to="MSG-1",
            )
            second = service.run_command(
                "positions",
                account_name=account.name,
                send=True,
                target=account.whatsapp_target,
                reply_to="MSG-1",
            )

    assert first.sent is True
    assert second.sent is True
    assert send_reply.call_count == 1


def test_run_command_send_failure_returns_sent_false_without_error() -> None:
    from mt5_trigger.config import AccountConfig, AppConfig, AppSettings, CommandsSettings

    config = AppConfig(
        settings=AppSettings(commands=CommandsSettings(enabled=True)),
        accounts=[
            AccountConfig(
                name="valetax_main",
                login="1",
                password="x",
                server="MetaQuotes-Demo",
                whatsapp_target="120363428584387160@g.us",
            )
        ],
    )
    service = CommandService(config)
    account = config.accounts[0]

    with patch.object(service, "_execute", return_value="Open positions (0):"):
        with patch.object(service, "_send_reply", return_value=False):
            result = service.run_command(
                "positions",
                account_name=account.name,
                send=True,
                target=account.whatsapp_target,
                reply_to="MSG-UNIQUE",
            )

    assert result.sent is False
    assert result.error is None
    assert result.message == "Open positions (0):"


def test_internal_hook_skips_plugin_handled_commands() -> None:
    handler_ts = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "openclaw-plugins/mt5-whatsapp-commands/handler.ts"
    ).read_text(encoding="utf-8")
    assert "isPluginHandledCommand" in handler_ts
    assert "registerCommand owns delivery" in handler_ts


def test_plugin_uses_message_cache() -> None:
    plugin_dir = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "openclaw-plugins/mt5-whatsapp-commands"
    )
    assert (plugin_dir / "message-cache.ts").exists()
    index_ts = (plugin_dir / "index.ts").read_text(encoding="utf-8")
    assert "rememberMessageId" in index_ts
    assert "lookupMessageId" in index_ts


def test_install_openclaw_hook_sets_reply_to_mode() -> None:
    install_py = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "scripts/install_openclaw_hook.py"
    ).read_text(encoding="utf-8")
    assert 'whatsapp["replyToMode"]' in install_py
    assert '"disable", PLUGIN_ID' in install_py


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


def test_phones_match_nigerian_local_formats() -> None:
    admin = "+2348134563699"
    assert phones_match(admin, "8134563699")
    assert phones_match(admin, "08134563699")
    assert phones_match(admin, "2348134563699")
    assert phones_match(admin, "+2348134563699")
    assert not phones_match(admin, "+2349050273391")


def test_whatsapp_admin_variants_include_local_digits() -> None:
    variants = whatsapp_admin_variants(["+2348134563699"])
    assert "+2348134563699" in variants
    assert "8134563699" in variants
    assert "08134563699" in variants
    assert "2348134563699" in variants


def test_is_allowed_sender_accepts_local_whatsapp_id() -> None:
    config = AppConfig(
        settings=AppSettings(
            commands=CommandsSettings(
                enabled=True,
                whatsapp_admins=["+2348134563699"],
            )
        ),
        accounts=[],
    )
    service = CommandService(config)
    assert service.is_allowed_sender("8134563699")
    assert service.is_allowed_sender("08134563699@s.whatsapp.net")
    assert not service.is_allowed_sender("+2349050273391")
