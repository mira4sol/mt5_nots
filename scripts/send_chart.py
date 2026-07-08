#!/usr/bin/env python3
"""Fetch live XAUUSD candles from MT5, render a chart, and send to WhatsApp."""

from __future__ import annotations

import argparse
import sys

from mt5_trigger.charts.sender import send_live_chart
from mt5_trigger.config import enabled_accounts, load_config
from mt5_trigger.mt5.backend import _port_open, resolve_backend
from mt5_trigger.mt5.client import MT5Client

PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render a live MT5 chart and send it to WhatsApp via OpenClaw"
    )
    parser.add_argument(
        "--symbol",
        default=None,
        help="Symbol to chart (default: auto-detect XAUUSD.vx / XAUUSD)",
    )
    parser.add_argument(
        "--account",
        default=None,
        help="Account name from accounts.yaml (default: first enabled account)",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="WhatsApp group JID override (default: account whatsapp_target)",
    )
    parser.add_argument(
        "--bars",
        type=int,
        default=100,
        help="Number of M5 candles to fetch (default: 100)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Unused override kept for compatibility; charts save under data/charts/",
    )
    parser.add_argument(
        "--no-send",
        action="store_true",
        help="Only render the chart locally; do not send to WhatsApp",
    )
    parser.add_argument(
        "--force-document",
        action="store_true",
        help="Send image as document to avoid WhatsApp compression",
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

    backend = resolve_backend(account)
    if backend == "mock":
        print("ERROR: Refusing mock backend — this script requires a live MT5 connection.", file=sys.stderr)
        return 1

    if backend == "bridge" and not _port_open(account.bridge_host, account.bridge_port):
        print(
            f"ERROR: MT5 bridge not reachable at {account.bridge_host}:{account.bridge_port}.",
            file=sys.stderr,
        )
        return 1

    if not account.login or not account.password:
        print("ERROR: MT5 login/password empty. Set MT5_LOGIN and MT5_PASSWORD in .env", file=sys.stderr)
        return 1

    target = args.target or account.whatsapp_target
    if not args.no_send and not target:
        print("ERROR: No WhatsApp target. Set whatsapp_target or pass --target", file=sys.stderr)
        return 1

    client = MT5Client(account)
    print(f"Account  : {account.name}")
    print(f"Backend  : {backend}")
    print("Connecting to MT5...")
    if not client.connect():
        print("FAILED: Could not connect to MT5.", file=sys.stderr)
        return 1

    charts_dir = config.settings.db_path_resolved.parent / "charts"

    try:
        print("Rendering chart...")
        result = send_live_chart(
            client=client,
            settings=config.settings,
            charts_dir=charts_dir,
            symbol=args.symbol,
            bars=args.bars,
            whatsapp_target=target,
            send=not args.no_send,
            force_document=args.force_document,
        )
        print(f"Symbol   : {result.symbol}")
        print(f"Bars     : {args.bars} x M5")
        print(f"Pending  : {result.pending_count}")
        print(f"Open     : {result.open_count}")
        print(f"Saved    : {result.output_path}")

        if args.no_send:
            print("Skipped WhatsApp send (--no-send).")
            return 0

        print(f"Sending to : {target}")
        print("SUCCESS: Chart sent to WhatsApp.")
        return 0
    except ImportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        client.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
