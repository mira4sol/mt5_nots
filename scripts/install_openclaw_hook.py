#!/usr/bin/env python3
"""Install mt5-whatsapp-commands OpenClaw plugin + internal hook fallback."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from mt5_trigger.config import (
    command_group_jids,
    enabled_accounts,
    load_config,
    whatsapp_admin_variants,
)
from mt5_trigger.openclaw_sync import build_openclaw_patch, patch_openclaw_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SOURCE = PROJECT_ROOT / "openclaw-plugins" / "mt5-whatsapp-commands"
OPENCLAW_HOME = Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw"))
PLUGIN_DEST = OPENCLAW_HOME / "plugins" / "mt5-whatsapp-commands"
HOOK_DEST = OPENCLAW_HOME / "hooks" / "mt5-whatsapp-commands"
CONFIG_CANDIDATES = [
    OPENCLAW_HOME / "openclaw.json",
    OPENCLAW_HOME / "config.json",
]
PLUGIN_ID = "mt5-whatsapp-commands"


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


def _link_or_copy(source: Path, dest: Path) -> None:
    if dest.exists() or dest.is_symlink():
        if dest.is_symlink() or dest.is_file():
            dest.unlink()
        else:
            shutil.rmtree(dest)
    try:
        dest.symlink_to(source)
    except OSError:
        if source.is_dir():
            shutil.copytree(source, dest)
        else:
            shutil.copy2(source, dest)


def _run_openclaw(*args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["openclaw", *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None


def _install_plugin() -> str:
    result = _run_openclaw("plugins", "install", "--link", str(PLUGIN_SOURCE))
    if result is not None and result.returncode == 0:
        return "openclaw plugins install --link"

    _link_or_copy(PLUGIN_SOURCE, PLUGIN_DEST)
    return f"symlink {PLUGIN_DEST}"


def main() -> int:
    if not PLUGIN_SOURCE.exists():
        print(f"ERROR: plugin source missing: {PLUGIN_SOURCE}", file=sys.stderr)
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

    hook_env, plugin_config, group_jids, admins = build_openclaw_patch(config)

    OPENCLAW_HOME.mkdir(parents=True, exist_ok=True)
    (OPENCLAW_HOME / "plugins").mkdir(parents=True, exist_ok=True)
    (OPENCLAW_HOME / "hooks").mkdir(parents=True, exist_ok=True)

    plugin_method = _install_plugin()
    _link_or_copy(PLUGIN_SOURCE, HOOK_DEST)

    config_path = _find_config_path()
    # Ensure plugin load path is present without wiping other plugin settings.
    if config_path.exists():
        openclaw_cfg = _load_json(config_path)
    else:
        openclaw_cfg = {}
    plugins = openclaw_cfg.setdefault("plugins", {})
    load_paths = plugins.setdefault("load", {}).setdefault("paths", [])
    plugin_path = str(PLUGIN_DEST)
    if plugin_path not in load_paths:
        load_paths.append(plugin_path)
        _save_json(config_path, openclaw_cfg)

    allow_variants = whatsapp_admin_variants(admins)
    webhook_url = str(plugin_config.get("webhookUrl", ""))

    ok, sync_message = patch_openclaw_config(config=config, restart_gateway=False)
    if not ok:
        print(f"ERROR: {sync_message}", file=sys.stderr)
        return 1

    enable_hook = _run_openclaw("hooks", "disable", PLUGIN_ID)
    enable_plugin = _run_openclaw("plugins", "enable", PLUGIN_ID)
    restart = _run_openclaw("gateway", "restart")

    print("Installed MT5 WhatsApp command bridge")
    print(f"  plugin     : {PLUGIN_DEST} ({plugin_method})")
    print(f"  hook dir   : {HOOK_DEST}")
    print(f"  config     : {config_path}")
    print(f"  group jids : {', '.join(group_jids)}")
    for account in accounts:
        if account.whatsapp_target in group_jids:
            print(f"    {account.whatsapp_target} -> {account.name}")
    print(f"  webhook    : {webhook_url}")
    print("  whatsapp   : pluginHooks.messageReceived = true")
    print("  whatsapp   : replyToMode = first (quote command replies)")
    if admins:
        print(f"  admins     : {', '.join(admins)} (from config/settings.yaml)")
        print(f"  allowlist  : {', '.join(allow_variants)}")
    if restart is not None and restart.returncode == 0:
        print("  gateway    : restarted")
    elif enable_hook is None or enable_plugin is None:
        print("")
        print("NOTE: openclaw CLI not found; config was patched manually.")
    print("")
    print("Restart the OpenClaw gateway so the plugin loads:")
    print("  openclaw gateway restart")
    print("")
    print("Then verify:")
    print("  make diagnose-whatsapp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
