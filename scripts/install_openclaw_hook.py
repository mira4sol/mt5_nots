#!/usr/bin/env python3
"""Install mt5-whatsapp-commands OpenClaw plugin + internal hook fallback."""

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
PLUGIN_SOURCE = PROJECT_ROOT / "openclaw-plugins" / "mt5-whatsapp-commands"
OPENCLAW_HOME = Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw"))
PLUGIN_DEST = OPENCLAW_HOME / "plugins" / "mt5-whatsapp-commands"
HOOK_DEST = OPENCLAW_HOME / "hooks" / "mt5-whatsapp-commands"
CONFIG_CANDIDATES = [
    OPENCLAW_HOME / "openclaw.json",
    OPENCLAW_HOME / "config.json",
]
PLUGIN_ID = "mt5-whatsapp-commands"


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


def _api_base_url(config) -> str:
    host = config.settings.health_host
    port = config.settings.health_port
    if host == "0.0.0.0":
        host = "127.0.0.1"
    return f"http://{host}:{port}"


def _accounts_by_group(accounts, group_jids: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for account in accounts:
        target = account.whatsapp_target.strip()
        if target in group_jids:
            mapping[target] = account.name
    return mapping


def _patch_config(
    config_path: Path,
    *,
    hook_env: dict[str, str],
    plugin_config: dict[str, object],
    group_jids: list[str],
    admins: list[str],
) -> None:
    if config_path.exists():
        config = _load_json(config_path)
    else:
        config = {}

    channels = config.setdefault("channels", {})
    whatsapp = channels.setdefault("whatsapp", {})
    whatsapp["enabled"] = whatsapp.get("enabled", True)
    if admins:
        whatsapp.setdefault("groupPolicy", "allowlist")
        existing_allow = whatsapp.get("groupAllowFrom")
        if not existing_allow:
            whatsapp["groupAllowFrom"] = admins
    plugin_hooks = whatsapp.setdefault("pluginHooks", {})
    plugin_hooks["messageReceived"] = True

    for group_jid in group_jids:
        groups = whatsapp.setdefault("groups", {})
        group_entry = groups.setdefault(group_jid, {})
        if "requireMention" not in group_entry:
            group_entry["requireMention"] = False

    plugins = config.setdefault("plugins", {})
    entries = plugins.setdefault("entries", {})
    entries[PLUGIN_ID] = {
        "enabled": True,
        "config": plugin_config,
    }
    load_paths = plugins.setdefault("load", {}).setdefault("paths", [])
    plugin_path = str(PLUGIN_DEST)
    if plugin_path not in load_paths:
        load_paths.append(plugin_path)

    hooks = config.setdefault("hooks", {})
    internal = hooks.setdefault("internal", {})
    internal["enabled"] = True
    internal_entries = internal.setdefault("entries", {})
    internal_entries[PLUGIN_ID] = {
        "enabled": True,
        "env": hook_env,
    }

    if admins:
        commands_oc = config.setdefault("commands", {})
        allow_from = commands_oc.setdefault("allowFrom", {})
        allow_from["whatsapp"] = admins

    _save_json(config_path, config)


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

    webhook_url = _webhook_url(config)
    api_base = _api_base_url(config)
    admins = config.settings.commands.whatsapp_admins
    accounts_by_group = _accounts_by_group(accounts, group_jids)
    hook_env = {
        "WHATSAPP_GROUP_JIDS": ",".join(group_jids),
        "MT5_TRIGGER_WEBHOOK_URL": webhook_url,
        "MT5_TRIGGER_API_URL": api_base,
    }
    plugin_config: dict[str, object] = {
        "apiBaseUrl": api_base,
        "webhookUrl": webhook_url,
        "groupJids": group_jids,
        "accountsByGroup": accounts_by_group,
    }
    token = config.settings.commands.api_token.strip()
    if token:
        hook_env["COMMAND_API_TOKEN"] = token
        plugin_config["apiToken"] = token

    OPENCLAW_HOME.mkdir(parents=True, exist_ok=True)
    (OPENCLAW_HOME / "plugins").mkdir(parents=True, exist_ok=True)
    (OPENCLAW_HOME / "hooks").mkdir(parents=True, exist_ok=True)

    plugin_method = _install_plugin()
    _link_or_copy(PLUGIN_SOURCE, HOOK_DEST)

    config_path = _find_config_path()
    _patch_config(
        config_path,
        hook_env=hook_env,
        plugin_config=plugin_config,
        group_jids=group_jids,
        admins=admins,
    )

    enable_hook = _run_openclaw("hooks", "enable", PLUGIN_ID)
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
    if admins:
        print(f"  admins     : {', '.join(admins)}")
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
