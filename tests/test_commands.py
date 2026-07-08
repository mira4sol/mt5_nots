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
