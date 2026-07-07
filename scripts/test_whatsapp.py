#!/usr/bin/env python3
"""Send a test WhatsApp message via OpenClaw to verify the integration."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from mt5_trigger.config import enabled_accounts, load_config
from mt5_trigger.notify.openclaw import OpenClawNotifier


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send a test WhatsApp message through OpenClaw"
    )
    parser.add_argument(
        "--message",
        default=None,
        help="Custom message text (default: auto-generated test message)",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="WhatsApp target override (E.164 or group JID). Defaults to WHATSAPP_TARGET / account config.",
    )
    parser.add_argument(
        "--account",
        default=None,
        help="Account name from accounts.yaml (uses its whatsapp_target if --target not set)",
    )
    args = parser.parse_args()

    config = load_config()
    accounts = enabled_accounts(config)
    if not accounts:
        print("ERROR: No enabled accounts in config/accounts.yaml", file=sys.stderr)
        return 1

    account = accounts[0]
    if args.account:
        matches = [a for a in accounts if a.name == args.account]
        if not matches:
            names = ", ".join(a.name for a in accounts)
            print(f"ERROR: Account '{args.account}' not found. Available: {names}", file=sys.stderr)
            return 1
        account = matches[0]

    target = args.target or account.whatsapp_target
    if not target:
        print(
            "ERROR: No WhatsApp target. Set WHATSAPP_TARGET in .env or pass --target",
            file=sys.stderr,
        )
        return 1

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    message = args.message or (
        f"MT5 Trigger Monitor test message\n"
        f"account: {account.name}\n"
        f"time: {ts}\n"
        f"If you see this, OpenClaw WhatsApp is working."
    )

    print(f"OpenClaw binary : {config.settings.openclaw_bin}")
    print(f"WhatsApp target : {target}")
    print(f"Account         : {account.name}")
    print(f"Message         : {message!r}")
    print()
    print("Sending... (ensure `openclaw gateway` is running and WhatsApp is linked)")

    notifier = OpenClawNotifier(config.settings, target)
    ok = notifier.send(message, target=target)

    if ok:
        print("SUCCESS: Message sent.")
        return 0

    print(
        "FAILED: Could not send message.\n"
        "Checklist:\n"
        "  1. openclaw gateway is running\n"
        "  2. WhatsApp channel is linked (openclaw channels login --channel whatsapp)\n"
        "  3. WHATSAPP_TARGET is correct E.164 or group JID\n"
        "  4. openclaw is on PATH (or set openclaw_bin in config/settings.yaml)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
