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


def main() -> int:
    parser = argparse.ArgumentParser(description="POST WhatsApp inbound payload to mt5_trigger")
    parser.add_argument("--text", required=True, help="Message body")
    parser.add_argument("--sender", required=True, help="Sender E.164 or JID")
    parser.add_argument("--group-jid", required=True, help="WhatsApp group JID")
    parser.add_argument("--account", default=None, help="Optional account name override")
    parser.add_argument(
        "--api-url",
        default=None,
        help="Webhook URL (default: http://127.0.0.1:$HEALTH_PORT/webhooks/whatsapp/inbound)",
    )
    args = parser.parse_args()

    load_dotenv()
    port = os.environ.get("HEALTH_PORT", "8080").strip() or "8080"
    host = os.environ.get("HEALTH_HOST", "127.0.0.1").strip() or "127.0.0.1"
    if host == "0.0.0.0":
        host = "127.0.0.1"
    api_url = args.api_url or f"http://{host}:{port}/webhooks/whatsapp/inbound"
    token = os.environ.get("COMMAND_API_TOKEN", "").strip()

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

    req = urllib.request.Request(api_url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            print(body)
            return 0
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        return exc.code
    except urllib.error.URLError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
