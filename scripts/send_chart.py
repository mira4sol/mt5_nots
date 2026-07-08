#!/usr/bin/env python3
"""Fetch live XAUUSD candles from MT5, render a chart, and send to WhatsApp."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from mt5_trigger.charts.renderer import render_symbol_chart
from mt5_trigger.config import enabled_accounts, load_config
from mt5_trigger.mt5.backend import TIMEFRAME_M5, _port_open, resolve_backend
from mt5_trigger.mt5.client import MT5Client
from mt5_trigger.notify.openclaw import OpenClawNotifier

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SYMBOL_CANDIDATES = ("XAUUSD.vx", "XAUUSD", "XAUUSDm", "GOLD")


def _resolve_symbol(client: MT5Client, preferred: str | None) -> str:
    candidates: list[str] = []
    if preferred:
        candidates.append(preferred)
    for sym in DEFAULT_SYMBOL_CANDIDATES:
        if sym not in candidates:
            candidates.append(sym)

    for symbol in candidates:
        tick = client.get_tick(symbol)
        rates = client.get_rates(symbol, TIMEFRAME_M5, count=10)
        if tick is not None and rates:
            return symbol

    tried = ", ".join(candidates)
    raise RuntimeError(
        f"Could not load live data for any symbol candidate ({tried}). "
        "Pass --symbol with your broker's exact gold symbol."
    )


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
        help="Save PNG locally to this path (default: data/charts/<symbol>_<ts>.png)",
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

    try:
        import mplfinance  # noqa: F401
    except ImportError:
        print(
            "ERROR: Chart dependencies missing.\n"
            "Run: make install-charts",
            file=sys.stderr,
        )
        return 1

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

    try:
        symbol = _resolve_symbol(client, args.symbol)
        print(f"Symbol   : {symbol}")

        rates = client.get_rates(symbol, TIMEFRAME_M5, count=args.bars)
        if not rates:
            print(f"ERROR: No M5 candle data returned for {symbol}", file=sys.stderr)
            return 1

        tick = client.get_tick(symbol)
        pending = [o for o in client.get_pending_orders() if o.symbol == symbol]
        positions = [p for p in client.get_positions() if p.symbol == symbol]

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output = Path(args.output) if args.output else PROJECT_ROOT / "data" / "charts" / f"{symbol}_{ts}.png"

        print(f"Bars     : {len(rates)} x M5")
        print(f"Pending  : {len(pending)}")
        print(f"Open     : {len(positions)}")
        if tick:
            print(f"Bid/Ask  : {tick.bid:.2f} / {tick.ask:.2f}")

        print("Rendering chart...")
        render_symbol_chart(
            symbol=symbol,
            rates=rates,
            output_path=output,
            tick=tick,
            pending_orders=pending,
            positions=positions,
            timeframe_minutes=5,
        )
        print(f"Saved    : {output}")

        if args.no_send:
            print("Skipped WhatsApp send (--no-send).")
            return 0

        caption = (
            f"📈 Live chart · {symbol} M5\n"
            f"Pending {len(pending)} · Open {len(positions)}"
        )
        if tick:
            caption += f"\nBid {tick.bid:.2f} · Ask {tick.ask:.2f}"

        print(f"Sending to : {target}")
        notifier = OpenClawNotifier(config.settings, target)
        ok = notifier.send_media(
            output,
            message=caption,
            target=target,
            force_document=args.force_document,
        )
        if ok:
            print("SUCCESS: Chart sent to WhatsApp.")
            return 0

        print(
            "FAILED: Could not send chart via OpenClaw.\n"
            "Checklist:\n"
            "  1. openclaw gateway is running\n"
            "  2. WhatsApp channel is linked\n"
            "  3. whatsapp_target group JID is correct",
            file=sys.stderr,
        )
        return 1
    finally:
        client.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
