#!/usr/bin/env python3
"""Connect to MT5 and print open positions (and pending orders) for verification."""

from __future__ import annotations

import argparse
import os
import sys

from mt5_trigger.config import enabled_accounts, load_config
from mt5_trigger.mt5.backend import _port_open, resolve_backend, resolve_bridge_client
from mt5_trigger.mt5.client import MT5Client


def _apply_env_overrides(account):
    """Apply MT5_* env vars from .env over account config."""
    updates: dict = {}
    if os.environ.get("MT5_BACKEND"):
        updates["mt5_backend"] = os.environ["MT5_BACKEND"]
    if os.environ.get("MT5_BRIDGE_HOST"):
        updates["bridge_host"] = os.environ["MT5_BRIDGE_HOST"]
    if os.environ.get("MT5_BRIDGE_PORT"):
        updates["bridge_port"] = int(os.environ["MT5_BRIDGE_PORT"])
    if os.environ.get("MT5_BRIDGE_CLIENT"):
        updates["bridge_client"] = os.environ["MT5_BRIDGE_CLIENT"]
    if os.environ.get("MT5_TERMINAL_PATH"):
        updates["terminal_path"] = os.environ["MT5_TERMINAL_PATH"]
    if updates:
        return account.model_copy(update=updates)
    return account


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

    account = _apply_env_overrides(account)

    if args.backend:
        account = account.model_copy(update={"mt5_backend": args.backend})

    backend = resolve_backend(account)
    bridge_client = resolve_bridge_client(account) if backend == "bridge" else None
    print(f"Account  : {account.name}")
    print(f"Login    : {account.login}")
    print(f"Server   : {account.server}")
    print(f"Backend  : {backend}")
    if backend == "bridge":
        reachable = _port_open(account.bridge_host, account.bridge_port)
        print(f"Bridge   : {account.bridge_host}:{account.bridge_port} ({'reachable' if reachable else 'NOT reachable'})")
        print(f"Client   : {bridge_client}")
    if backend == "mock":
        print("WARNING  : Using mock backend — not a real MT5 server. Omit --backend mock for real connection.")
    if account.terminal_path:
        print(f"Terminal : {account.terminal_path}")

    if backend == "mock" and args.backend != "mock":
        print("ERROR: Refusing mock backend. Use --backend mock only for offline tests.", file=sys.stderr)
        return 1

    if backend == "bridge" and not _port_open(account.bridge_host, account.bridge_port):
        print(
            f"ERROR: MT5 bridge not reachable at {account.bridge_host}:{account.bridge_port}.\n"
            "Start MT5 terminal + bridge, then retry.\n"
            "  Linux (mt5linux): python -m mt5linux <path/to/wine/python.exe> --port {port}\n"
            "  Mac: mt5-mac-bridge serve\n"
            "  Remote: ssh -L {port}:127.0.0.1:{port} user@vps\n"
            "Check MT5_BRIDGE_HOST / MT5_BRIDGE_PORT in .env match your bridge.\n"
            "If using mt5linux server: MT5_BRIDGE_CLIENT=mt5linux and pip install mt5linux".format(
                port=account.bridge_port
            ),
            file=sys.stderr,
        )
        return 1

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
            "  Linux bridge: pip install mt5linux, MT5_BRIDGE_CLIENT=mt5linux, mt5linux server running\n"
            "  Mac bridge: mt5-mac-bridge serve (MT5_BRIDGE_CLIENT=mac-bridge)\n"
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
