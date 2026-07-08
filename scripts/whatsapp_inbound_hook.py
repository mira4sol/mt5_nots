#!/usr/bin/env python3
"""Forward an OpenClaw WhatsApp inbound event to mt5_trigger's webhook."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from dotenv import load_dotenv

from mt5_trigger.config import command_group_jids, enabled_accounts, load_config


def _defaults_from_config() -> tuple[str, str]:
    config = load_config()
    accounts = enabled_accounts(config)
    groups = command_group_jids(accounts)
    group_jid = groups[0] if groups else ""
    admins = config.settings.commands.whatsapp_admins
    sender = admins[0] if admins else ""
    return sender, group_jid


def main() -> int:
    load_dotenv()
    default_sender, default_group = _defaults_from_config()

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

    port = os.environ.get("HEALTH_PORT", "8080").strip() or "8080"
    host = os.environ.get("HEALTH_HOST", "127.0.0.1").strip() or "127.0.0.1"
    if host == "0.0.0.0":
        host = "127.0.0.1"
    api_url = args.api_url or f"http://{host}:{port}/webhooks/whatsapp/inbound"
    token = os.environ.get("COMMAND_API_TOKEN", "").strip()
    if not token:
        config = load_config()
        token = config.settings.commands.api_token.strip()

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

    req = urllib.request.Request(api_url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            print(body)
            return 0
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        return exc.code if exc.code else 1
    except urllib.error.URLError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("Hint: start the app first (make prod) and check HEALTH_PORT", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
