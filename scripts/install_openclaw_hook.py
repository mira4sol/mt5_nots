#!/usr/bin/env python3
"""Install and enable the mt5-whatsapp-commands OpenClaw hook."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

from mt5_trigger.config import command_group_jids, enabled_accounts, load_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOOK_SOURCE = PROJECT_ROOT / "openclaw-hooks" / "mt5-whatsapp-commands"
OPENCLAW_HOME = Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw"))
HOOK_DEST = OPENCLAW_HOME / "hooks" / "mt5-whatsapp-commands"
CONFIG_CANDIDATES = [
    OPENCLAW_HOME / "openclaw.json",
    OPENCLAW_HOME / "config.json",
]


def _webhook_url(config) -> str:
    explicit = os.environ.get("MT5_TRIGGER_WEBHOOK_URL", "").strip()
    if not explicit:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            explicit = (dotenv_values(env_path).get("MT5_TRIGGER_WEBHOOK_URL") or "").strip()
    if explicit:
        return explicit
    host = config.settings.health_host
    port = config.settings.health_port
    if host == "0.0.0.0":
        host = "127.0.0.1"
    return f"http://{host}:{port}/webhooks/whatsapp/inbound"


def _find_config_path() -> Path:
    for path in CONFIG_CANDIDATES:
        if path.exists():
            return path
    return CONFIG_CANDIDATES[0]


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _patch_config(config_path: Path, hook_env: dict[str, str]) -> None:
    if config_path.exists():
        config = _load_json(config_path)
    else:
        config = {}

    hooks = config.setdefault("hooks", {})
    internal = hooks.setdefault("internal", {})
    internal["enabled"] = True
    entries = internal.setdefault("entries", {})
    entries["mt5-whatsapp-commands"] = {
        "enabled": True,
        "env": hook_env,
    }
    _save_json(config_path, config)


def _run_openclaw_enable() -> None:
    try:
        subprocess.run(
            ["openclaw", "hooks", "enable", "mt5-whatsapp-commands"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("NOTE: openclaw CLI not found; config was patched manually.")


def main() -> int:
    if not HOOK_SOURCE.exists():
        print(f"ERROR: hook source missing: {HOOK_SOURCE}", file=sys.stderr)
        return 1

    config = load_config()
    accounts = enabled_accounts(config)
    group_jids = command_group_jids(accounts)
    if not group_jids:
        print(
            "ERROR: No @g.us whatsapp_target found on enabled accounts in "
            "config/accounts.yaml",
            file=sys.stderr,
        )
        return 1

    hook_env = {
        "WHATSAPP_GROUP_JIDS": ",".join(group_jids),
        "MT5_TRIGGER_WEBHOOK_URL": _webhook_url(config),
    }
    token = config.settings.commands.api_token.strip()
    if token:
        hook_env["COMMAND_API_TOKEN"] = token

    OPENCLAW_HOME.mkdir(parents=True, exist_ok=True)
    (OPENCLAW_HOME / "hooks").mkdir(parents=True, exist_ok=True)

    if HOOK_DEST.exists() or HOOK_DEST.is_symlink():
        if HOOK_DEST.is_symlink() or HOOK_DEST.is_file():
            HOOK_DEST.unlink()
        else:
            shutil.rmtree(HOOK_DEST)

    try:
        HOOK_DEST.symlink_to(HOOK_SOURCE)
    except OSError:
        shutil.copytree(HOOK_SOURCE, HOOK_DEST)

    config_path = _find_config_path()
    _patch_config(config_path, hook_env)
    _run_openclaw_enable()

    print("Installed OpenClaw hook: mt5-whatsapp-commands")
    print(f"  hook dir   : {HOOK_DEST}")
    print(f"  config     : {config_path}")
    print(f"  group jids : {', '.join(group_jids)}")
    for account in accounts:
        if account.whatsapp_target in group_jids:
            print(f"    {account.whatsapp_target} -> {account.name}")
    print(f"  webhook    : {hook_env['MT5_TRIGGER_WEBHOOK_URL']}")
    print("")
    print("Restart the OpenClaw gateway so the hook loads:")
    print("  openclaw gateway")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
