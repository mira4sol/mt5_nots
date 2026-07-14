"""Patch OpenClaw config from mt5_trigger settings (no gateway restart by default)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from dotenv import dotenv_values

from mt5_trigger.config import (
    PROJECT_ROOT,
    command_group_jids,
    enabled_accounts,
    load_config,
    whatsapp_admin_variants,
)

logger = logging.getLogger(__name__)

PLUGIN_ID = "mt5-whatsapp-commands"
OPENCLAW_HOME = Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw"))
CONFIG_CANDIDATES = [
    OPENCLAW_HOME / "openclaw.json",
    OPENCLAW_HOME / "config.json",
]


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


def build_openclaw_patch(config=None) -> tuple[dict[str, str], dict[str, object], list[str], list[str]]:
    config = config or load_config()
    accounts = enabled_accounts(config)
    group_jids = command_group_jids(accounts)
    admins = config.settings.commands.whatsapp_admins
    webhook_url = _webhook_url(config)
    api_base = _api_base_url(config)
    hook_env = {
        "WHATSAPP_GROUP_JIDS": ",".join(group_jids),
        "MT5_TRIGGER_WEBHOOK_URL": webhook_url,
        "MT5_TRIGGER_API_URL": api_base,
        "WHATSAPP_ADMINS": ",".join(admins),
    }
    plugin_config: dict[str, object] = {
        "apiBaseUrl": api_base,
        "webhookUrl": webhook_url,
        "groupJids": group_jids,
        "accountsByGroup": _accounts_by_group(accounts, group_jids),
        "admins": admins,
    }
    token = config.settings.commands.api_token.strip()
    if token:
        hook_env["COMMAND_API_TOKEN"] = token
        plugin_config["apiToken"] = token
    return hook_env, plugin_config, group_jids, admins


def patch_openclaw_config(
    *,
    config=None,
    restart_gateway: bool = False,
) -> tuple[bool, str]:
    """Update ~/.openclaw/openclaw.json allowlists + plugin admins (no plugin reinstall)."""
    config = config or load_config()
    hook_env, plugin_config, group_jids, admins = build_openclaw_patch(config)
    if not group_jids:
        return False, "No WhatsApp group JIDs configured in accounts.yaml"

    config_path = _find_config_path()
    if config_path.exists():
        openclaw_cfg = _load_json(config_path)
    else:
        openclaw_cfg = {}

    channels = openclaw_cfg.setdefault("channels", {})
    whatsapp = channels.setdefault("whatsapp", {})
    whatsapp["enabled"] = whatsapp.get("enabled", True)
    whatsapp["replyToMode"] = whatsapp.get("replyToMode", "first")
    allow_variants = whatsapp_admin_variants(admins) if admins else []
    if allow_variants:
        whatsapp["groupPolicy"] = "allowlist"
        whatsapp["groupAllowFrom"] = allow_variants
    plugin_hooks = whatsapp.setdefault("pluginHooks", {})
    plugin_hooks["messageReceived"] = True

    for group_jid in group_jids:
        groups = whatsapp.setdefault("groups", {})
        group_entry = groups.setdefault(group_jid, {})
        if "requireMention" not in group_entry:
            group_entry["requireMention"] = False

    plugins = openclaw_cfg.setdefault("plugins", {})
    entries = plugins.setdefault("entries", {})
    plugin_entry = entries.setdefault(PLUGIN_ID, {})
    plugin_entry["enabled"] = True
    plugin_entry["config"] = plugin_config

    hooks = openclaw_cfg.setdefault("hooks", {})
    internal = hooks.setdefault("internal", {})
    internal["enabled"] = True
    internal_entries = internal.setdefault("entries", {})
    internal_entries[PLUGIN_ID] = {
        "enabled": False,
        "env": hook_env,
    }

    if allow_variants:
        commands_oc = openclaw_cfg.setdefault("commands", {})
        allow_from = commands_oc.setdefault("allowFrom", {})
        allow_from["whatsapp"] = allow_variants

    _save_json(config_path, openclaw_cfg)
    logger.info("Patched OpenClaw config at %s (%d admins)", config_path, len(admins))

    if restart_gateway:
        try:
            proc = subprocess.run(
                ["openclaw", "gateway", "restart"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return True, (
                f"Config saved to {config_path}, but gateway restart failed: {exc}. "
                "Run: openclaw gateway restart"
            )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            return True, (
                f"Config saved, but gateway restart failed: {detail or 'unknown error'}. "
                "Run: openclaw gateway restart"
            )
        return True, "OpenClaw config saved and gateway restarted."

    return True, (
        "OpenClaw config saved. Run: openclaw gateway restart "
        "(needed for new admins; existing commands keep working)."
    )
