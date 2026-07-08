from __future__ import annotations

from mt5_trigger.messages import format_money, format_price
from mt5_trigger.mt5.client import OpenPosition, PendingOrder, SymbolTick


ORDER_SEPARATOR = "────────────────"


def symbol_price_line(symbol: str, tick: SymbolTick | None) -> str:
    if tick is None:
        return f"{symbol}: price unavailable"
    return f"{symbol}: bid {format_price(tick.bid)} · ask {format_price(tick.ask)}"


def _position_mark_price(position: OpenPosition, tick: SymbolTick | None) -> float | None:
    if tick is None:
        return None
    return tick.bid if position.position_type == 1 else tick.ask


def primary_symbol(symbols: list[str]) -> str | None:
    if not symbols:
        return None
    return max(set(symbols), key=symbols.count)


def guide_message() -> str:
    return (
        "MT5 Trigger — query your trading account from this group.\n"
        "Use /guide anytime for this list.\n"
        "\n"
        "Commands:\n"
        "/positions — open positions\n"
        "/orders — all pending orders\n"
        "/nt — nearest pending trigger price\n"
        "/tpd — today's closed P/L\n"
        "/sld — stop-loss distance on open trades\n"
        "/cts — current trade status\n"
        "/guide — this list"
    )


def help_message() -> str:
    return guide_message()


def positions_message(positions: list[OpenPosition]) -> str:
    if not positions:
        return "No open positions."
    lines = [f"Open positions ({len(positions)}):"]
    for p in positions:
        side = "BUY" if p.position_type == 0 else "SELL"
        lines.append(
            f"#{p.ticket} {p.symbol} {side} "
            f"vol={p.volume} open={format_price(p.price_open)} "
            f"P/L={format_money(p.profit)}"
        )
    return "\n".join(lines)


def orders_message(
    orders: list[PendingOrder],
    *,
    symbol: str | None = None,
    tick: SymbolTick | None = None,
) -> str:
    if not orders:
        return "No pending orders."
    lines: list[str] = []
    header_symbol = symbol or primary_symbol([o.symbol for o in orders])
    if header_symbol:
        lines.append(symbol_price_line(header_symbol, tick))
        lines.append("")
    lines.append(f"Pending orders ({len(orders)}):")
    for o in orders:
        sl = format_price(o.sl) if o.sl > 0 else "none"
        tp = format_price(o.tp) if o.tp > 0 else "none"
        lines.extend(
            [
                ORDER_SEPARATOR,
                f"#{o.ticket}  {o.symbol}",
                f"{o.order_type_label}  ·  vol {o.volume}",
                f"Price {format_price(o.price_open)}",
                f"SL {sl}  ·  TP {tp}",
            ]
        )
    return "\n".join(lines)


def close_price_message(
    order: PendingOrder | None,
    current_price: float | None,
    distance: float | None,
) -> str:
    if order is None:
        return "No pending orders."
    if current_price is None or distance is None:
        return (
            f"Nearest trigger: {order.symbol} {order.order_type_label} "
            f"at {format_price(order.price_open)} (price unavailable)"
        )
    return (
        f"Nearest trigger: {order.symbol} {order.order_type_label} "
        f"at {format_price(order.price_open)}\n"
        f"Current {format_price(current_price)} — distance {format_price(distance)}"
    )


def tpd_message(total: float, wins: int, losses: int, trade_count: int) -> str:
    if trade_count == 0:
        return "Today's closed trades: none."
    label = "profit" if total >= 0 else "loss"
    return (
        f"Today closed: {trade_count} trades "
        f"({wins} wins, {losses} losses)\n"
        f"Net {label}: {format_money(total)}"
    )


def sld_message(rows: list[tuple[OpenPosition, float | None, float | None]]) -> str:
    if not rows:
        return "No open positions with stop-loss info."
    lines = ["Stop-loss distance:"]
    for pos, current, distance in rows:
        side = "BUY" if pos.position_type == 0 else "SELL"
        if pos.sl <= 0:
            lines.append(f"#{pos.ticket} {pos.symbol} {side} — no SL set")
            continue
        if current is None or distance is None:
            lines.append(
                f"#{pos.ticket} {pos.symbol} {side} SL={format_price(pos.sl)} "
                f"(price unavailable)"
            )
            continue
        lines.append(
            f"#{pos.ticket} {pos.symbol} {side} "
            f"SL={format_price(pos.sl)} now={format_price(current)} "
            f"dist={format_price(distance)}"
        )
    return "\n".join(lines)


def cts_message(
    positions: list[OpenPosition],
    *,
    ticks: dict[str, SymbolTick | None] | None = None,
) -> str:
    if not positions:
        return "No active trades."
    ticks = ticks or {}
    total_pl = sum(p.profit for p in positions)
    lines: list[str] = []
    seen: set[str] = set()
    for p in positions:
        if p.symbol in seen:
            continue
        seen.add(p.symbol)
        lines.append(symbol_price_line(p.symbol, ticks.get(p.symbol)))
    if lines:
        lines.append("")
    lines.append(f"Active trades ({len(positions)}) — floating P/L {format_money(total_pl)}:")
    for p in positions:
        side = "BUY" if p.position_type == 0 else "SELL"
        sl = format_price(p.sl) if p.sl > 0 else "none"
        tp = format_price(p.tp) if p.tp > 0 else "none"
        current = _position_mark_price(p, ticks.get(p.symbol))
        now_part = f" now={format_price(current)}" if current is not None else ""
        lines.append(
            f"#{p.ticket} {p.symbol} {side} open={format_price(p.price_open)}"
            f"{now_part} P/L={format_money(p.profit)} SL={sl} TP={tp}"
        )
    return "\n".join(lines)
