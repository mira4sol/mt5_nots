from __future__ import annotations

from mt5_trigger.messages import format_money, format_price
from mt5_trigger.mt5.client import OpenPosition, PendingOrder


def help_message() -> str:
    return (
        "MT5 Trigger commands:\n"
        "/positions — open positions\n"
        "/close_price — nearest pending trigger price\n"
        "/tpd — today's closed P/L\n"
        "/sld — stop-loss distance on open trades\n"
        "/cts — current trade status\n"
        "/help — this list\n"
        "/mt5help — same list"
    )


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


def cts_message(positions: list[OpenPosition]) -> str:
    if not positions:
        return "No active trades."
    total_pl = sum(p.profit for p in positions)
    lines = [f"Active trades ({len(positions)}) — floating P/L {format_money(total_pl)}:"]
    for p in positions:
        side = "BUY" if p.position_type == 0 else "SELL"
        sl = format_price(p.sl) if p.sl > 0 else "none"
        tp = format_price(p.tp) if p.tp > 0 else "none"
        lines.append(
            f"#{p.ticket} {p.symbol} {side} open={format_price(p.price_open)} "
            f"P/L={format_money(p.profit)} SL={sl} TP={tp}"
        )
    return "\n".join(lines)
