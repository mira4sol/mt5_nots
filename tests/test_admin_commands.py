from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from mt5_trigger.commands.admins import (
    add_whatsapp_admin,
    parse_admin_phone,
    read_whatsapp_admin_lines,
    remove_whatsapp_admin,
)
from mt5_trigger.commands.service import CommandService
from mt5_trigger.config import AccountConfig, AppConfig, AppSettings, CommandsSettings


SETTINGS_SNIPPET = """\
commands:
  enabled: true
  whatsapp_admins:
    - '+2349050273391'
    - '+2348134563699' # kidir
  cooldown_seconds: 1
"""


@pytest.fixture
def settings_file(tmp_path: Path) -> Path:
    path = tmp_path / "settings.yaml"
    path.write_text(SETTINGS_SNIPPET, encoding="utf-8")
    return path


def test_parse_admin_phone() -> None:
    assert parse_admin_phone("/authorize +2349585758595") == "+2349585758595"
    assert parse_admin_phone("/unauthorize 2349585758595") == "+2349585758595"
    assert parse_admin_phone("/authorize") is None
    assert parse_admin_phone("/positions") is None


def test_add_and_remove_whatsapp_admin(settings_file: Path) -> None:
    admins, added = add_whatsapp_admin("+2349585758595", settings_file)
    assert added is True
    assert "+2349585758595" in admins
    assert "+2348134563699" in read_whatsapp_admin_lines(settings_file)

    admins, added = add_whatsapp_admin("+2349585758595", settings_file)
    assert added is False

    remaining, removed = remove_whatsapp_admin("+2349585758595", settings_file)
    assert removed is True
    assert "+2349585758595" not in remaining
    assert "# kidir" in settings_file.read_text(encoding="utf-8")


def test_authorize_command_updates_config(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(SETTINGS_SNIPPET, encoding="utf-8")
    config = AppConfig(
        settings=AppSettings(
            commands=CommandsSettings(
                enabled=True,
                whatsapp_admins=["+2349050273391"],
            ),
            db_path=str(tmp_path / "test.db"),
        ),
        accounts=[
            AccountConfig(
                name="main",
                login="1",
                password="x",
                server="Demo",
                whatsapp_target="120363428584387160@g.us",
            )
        ],
    )
    service = CommandService(config)

    with patch(
        "mt5_trigger.commands.admins.DEFAULT_SETTINGS_PATH",
        settings_path,
    ):
        with patch(
            "mt5_trigger.commands.service.sync_openclaw_allowlist",
            return_value="OpenClaw allowlist synced.",
        ):
            with patch.object(service, "_send_reply", return_value=True):
                result = service.run_command(
                    "authorize",
                    account_name="main",
                    send=True,
                    target="120363428584387160@g.us",
                    command_text="/authorize +2349585758595",
                    sender="+2349050273391",
                )

    assert result.error is None
    assert "Authorized +2349585758595" in result.message
    assert "+2349585758595" in config.settings.commands.whatsapp_admins
    assert "+2349585758595" in read_whatsapp_admin_lines(settings_path)
