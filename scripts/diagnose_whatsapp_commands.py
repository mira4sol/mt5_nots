#!/usr/bin/env python3
"""Check OpenClaw + mt5_trigger WhatsApp command wiring."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from mt5_trigger.config import (
    command_group_jids,
    enabled_accounts,
    load_config,
    resolve_command_api_token,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OPENCLAW_HOME = Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw"))
CONFIG_CANDIDATES = [
    OPENCLAW_HOME / "openclaw.json",
    OPENCLAW_HOME / "config.json",
]
PLUGIN_ID = "mt5-whatsapp-commands"


def _load_openclaw_config() -> tuple[Path | None, dict]:
    for path in CONFIG_CANDIDATES:
        if path.exists():
            with path.open(encoding="utf-8") as f:
                return path, json.load(f)
    return None, {}


def _check(label: str, ok: bool, detail: str = "") -> bool:
    status = "OK" if ok else "FAIL"
    line = f"[{status}] {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    return ok


def _webhook_url(config) -> str:
    host = config.settings.health_host
    port = config.settings.health_port
    if host == "0.0.0.0":
        host = "127.0.0.1"
    return f"http://{host}:{port}/webhooks/whatsapp/inbound"


def main() -> int:
    config = load_config()
    accounts = enabled_accounts(config)
    group_jids = command_group_jids(accounts)
    admins = config.settings.commands.whatsapp_admins
    webhook_url = _webhook_url(config)
    token = resolve_command_api_token(config)

    print("MT5 WhatsApp command diagnostics")
    print("=" * 40)

    ok = True
    ok &= _check(
        "commands.enabled",
        config.settings.commands.enabled,
        "set commands.enabled: true in settings.yaml",
    )
    ok &= _check(
        "whatsapp_admins",
        bool(admins),
        ", ".join(admins) if admins else "empty",
    )
    ok &= _check(
        "group jids in accounts.yaml",
        bool(group_jids),
        ", ".join(group_jids) if group_jids else "none",
    )

    config_path, openclaw_cfg = _load_openclaw_config()
    ok &= _check("openclaw config file", config_path is not None, str(config_path or OPENCLAW_HOME))

    whatsapp = (openclaw_cfg.get("channels") or {}).get("whatsapp") or {}
    plugin_hooks = whatsapp.get("pluginHooks") or {}
    ok &= _check(
        "channels.whatsapp.pluginHooks.messageReceived",
        plugin_hooks.get("messageReceived") is True,
        "run: make install-openclaw-hook",
    )

    groups = whatsapp.get("groups") or {}
    missing_groups = [jid for jid in group_jids if jid not in groups]
    ok &= _check(
        "channels.whatsapp.groups entries",
        not missing_groups,
        f"missing: {', '.join(missing_groups)}" if missing_groups else "all configured",
    )

    plugin_entry = ((openclaw_cfg.get("plugins") or {}).get("entries") or {}).get(PLUGIN_ID) or {}
    ok &= _check(
        f"plugins.entries.{PLUGIN_ID}.enabled",
        plugin_entry.get("enabled") is True,
        "run: make install-openclaw-hook",
    )
    plugin_config = plugin_entry.get("config") or {}
    ok &= _check(
        "plugin admins",
        bool(plugin_config.get("admins")),
        str(plugin_config.get("admins", "")),
    )
    ok &= _check(
        "plugin apiBaseUrl",
        bool(str(plugin_config.get("apiBaseUrl", "")).strip()),
        str(plugin_config.get("apiBaseUrl", "")),
    )
    ok &= _check(
        "plugin accountsByGroup",
        bool(plugin_config.get("accountsByGroup")),
        str(plugin_config.get("accountsByGroup", "")),
    )

    admins_cfg = ((openclaw_cfg.get("commands") or {}).get("allowFrom") or {}).get("whatsapp")
    if admins:
        ok &= _check(
            "commands.allowFrom.whatsapp",
            bool(admins_cfg),
            str(admins_cfg or "missing"),
        )

    group_policy = whatsapp.get("groupPolicy")
    ok &= _check(
        "channels.whatsapp.groupPolicy",
        group_policy in (None, "allowlist", "open"),
        str(group_policy or "unset"),
    )

    plugin_dir = OPENCLAW_HOME / "plugins" / PLUGIN_ID
    hook_dir = OPENCLAW_HOME / "hooks" / PLUGIN_ID
    ok &= _check("plugin installed", plugin_dir.exists(), str(plugin_dir))
    ok &= _check("internal hook installed", hook_dir.exists(), str(hook_dir))

    try:
        health_url = webhook_url.replace("/webhooks/whatsapp/inbound", "/health")
        with urllib.request.urlopen(health_url, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        ok &= _check(
            "mt5_trigger /health",
            body.get("commands_enabled") is True,
            f"status={body.get('status')}",
        )
    except urllib.error.URLError as exc:
        ok &= _check("mt5_trigger /health", False, str(exc))

    if admins and group_jids:
        payload = {
            "text": "/guide",
            "sender": admins[0],
            "group_jid": group_jids[0],
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-API-Token"] = token
        req = urllib.request.Request(webhook_url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            ok &= _check(
                "webhook /guide test",
                result.get("handled") is True,
                json.dumps(result),
            )
        except urllib.error.URLError as exc:
            ok &= _check("webhook /guide test", False, str(exc))

    try:
        proc = subprocess.run(
            ["openclaw", "plugins", "list"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode == 0:
            loaded = PLUGIN_ID in proc.stdout
            ok &= _check("openclaw plugins list", loaded, PLUGIN_ID)
        else:
            _check("openclaw plugins list", False, "openclaw CLI unavailable")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("[WARN] openclaw CLI not on PATH — restart gateway manually after install")

    print("=" * 40)
    if ok:
        print("All checks passed. Type /positions in the WhatsApp group.")
        print("If still silent, restart gateway: openclaw gateway restart")
        return 0

    print("Some checks failed. Run: make install-openclaw-hook && openclaw gateway restart")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
