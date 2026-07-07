#!/usr/bin/env python3
"""Connect to MT5 and print open positions (and pending orders) for verification."""

from __future__ import annotations

import argparse
import sys

from mt5_trigger.config import enabled_accounts, load_config
from mt5_trigger.mt5.backend import resolve_backend
from mt5_trigger.mt5.client import MT5Client


def _print_positions(client: MT5Client) -> None:
    positions = client.get_positions()
    print(f"\nOpen positions: {len(positions)}")
    if not positions:
        print("  (none)")
        return
    for p in positions:
        side = "BUY" if p.position_type == 0 else "SELL"
        print(
            f"  #{p.ticket} {p.symbol} {side} "
            f"vol={p.volume} open={p.price_open:.5f} "
            f"profit={p.profit:.2f} sl={p.sl} tp={p.tp}"
        )


def _print_pending(client: MT5Client) -> None:
    orders = client.get_pending_orders()
    print(f"\nPending orders: {len(orders)}")
    if not orders:
        print("  (none)")
        return
    for o in orders:
        print(
            f"  #{o.ticket} {o.symbol} {o.order_type_label} "
            f"vol={o.volume} price={o.price_open:.5f} sl={o.sl} tp={o.tp}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test MT5 connection and list open positions"
    )
    parser.add_argument(
        "--account",
        default=None,
        help="Account name from accounts.yaml (default: first enabled account)",
    )
    parser.add_argument(
        "--backend",
        default=None,
        choices=["auto", "native", "bridge", "mock"],
        help="Override MT5 backend for this test",
    )
    parser.add_argument(
        "--pending",
        action="store_true",
        help="Also list pending orders",
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

    if args.backend:
        account = account.model_copy(update={"mt5_backend": args.backend})

    backend = resolve_backend(account)
    print(f"Account  : {account.name}")
    print(f"Login    : {account.login}")
    print(f"Server   : {account.server}")
    print(f"Backend  : {backend}")
    if backend == "bridge":
        print(f"Bridge   : {account.bridge_host}:{account.bridge_port}")
    if account.terminal_path:
        print(f"Terminal : {account.terminal_path}")

    if not account.login or not account.password:
        print(
            "ERROR: MT5 login/password empty. Set MT5_LOGIN and MT5_PASSWORD in .env",
            file=sys.stderr,
        )
        return 1

    client = MT5Client(account)
    print("\nConnecting to MT5...")
    if not client.connect():
        print(
            "FAILED: Could not connect to MT5.\n"
            "Checklist:\n"
            "  Windows native: MT5 terminal running, investor password, pip install MetaTrader5\n"
            "  Mac/Linux bridge: MT5 + bridge running on bridge_host:bridge_port\n"
            "  Remote: SSH tunnel or set bridge_host to VPS IP\n"
            "  Dev only: --backend mock",
            file=sys.stderr,
        )
        return 1

    print("SUCCESS: Connected.")
    try:
        _print_positions(client)
        if args.pending:
            _print_pending(client)
    finally:
        client.disconnect()
        print("\nDisconnected.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
