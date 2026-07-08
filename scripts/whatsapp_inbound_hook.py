#!/usr/bin/env python3
"""Forward an OpenClaw WhatsApp inbound event to mt5_trigger's webhook."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

from mt5_trigger.config import (
    command_group_jids,
    enabled_accounts,
    load_config,
    resolve_command_api_token,
)


def main() -> int:
    config = load_config()
    accounts = enabled_accounts(config)
    groups = command_group_jids(accounts)
    default_group = groups[0] if groups else ""
    admins = config.settings.commands.whatsapp_admins
    default_sender = admins[0] if admins else ""
    token = resolve_command_api_token(config)

    parser = argparse.ArgumentParser(description="POST WhatsApp inbound payload to mt5_trigger")
    parser.add_argument("--text", default="/help", help="Message body (default: /help)")
    parser.add_argument(
        "--sender",
        default=default_sender or None,
        help="Sender E.164 (default: first commands.whatsapp_admins entry)",
    )
    parser.add_argument(
        "--group-jid",
        default=default_group or None,
        help="WhatsApp group JID (default: first account @g.us whatsapp_target)",
    )
    parser.add_argument("--account", default=None, help="Optional account name override")
    parser.add_argument(
        "--api-url",
        default=None,
        help="Webhook URL (default: http://127.0.0.1:$HEALTH_PORT/webhooks/whatsapp/inbound)",
    )
    args = parser.parse_args()

    if not args.sender:
        print(
            "ERROR: --sender required (or set commands.whatsapp_admins in settings.yaml)",
            file=sys.stderr,
        )
        return 1
    if not args.group_jid:
        print(
            "ERROR: --group-jid required (or set whatsapp_target @g.us in accounts.yaml)",
            file=sys.stderr,
        )
        return 1

    host = config.settings.health_host
    port = config.settings.health_port
    if host == "0.0.0.0":
        host = "127.0.0.1"
    api_url = args.api_url or f"http://{host}:{port}/webhooks/whatsapp/inbound"

    if not token:
        print(
            "WARN: COMMAND_API_TOKEN is not set in .env — webhook auth is disabled on the server",
            file=sys.stderr,
        )

    payload = {
        "text": args.text,
        "sender": args.sender,
        "group_jid": args.group_jid,
        "account": args.account,
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-API-Token"] = token

    print(f"POST {api_url}")
    print(f"  group   : {args.group_jid}")
    print(f"  sender  : {args.sender}")
    print(f"  text    : {args.text}")
    print(f"  token   : {'set' if token else 'MISSING'}")

    req = urllib.request.Request(api_url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            print(body)
            return 0
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        if exc.code == 401:
            print(
                "\nFix: set COMMAND_API_TOKEN in .env (must match the running app), then:\n"
                "  pm2 restart mt5-trigger\n"
                "  make test-whatsapp-inbound",
                file=sys.stderr,
            )
        return exc.code if exc.code else 1
    except urllib.error.URLError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("Hint: start the app first (make prod) and check HEALTH_PORT", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
