from __future__ import annotations

from mt5_trigger.mt5.client import (
    DEAL_REASON_SL,
    DEAL_REASON_TP,
    OpenPosition,
    PendingOrder,
)

ORDER_SEPARATOR = "────────────────"


def format_price(price: float, digits: int = 5) -> str:
    return f"{price:.{digits}f}"


def format_money(amount: float) -> str:
    if amount < 0:
        return f"-${abs(amount):,.2f}"
    return f"${amount:,.2f}"


def near_trigger_message(
    order: PendingOrder,
    *,
    current_price: float,
    distance: float,
) -> str:
    return "\n".join(
        [
            "⚠️ Order approaching trigger",
            ORDER_SEPARATOR,
            f"#{order.ticket}  {order.symbol}",
            f"{order.order_type_label}  ·  vol {order.volume}",
            f"Trigger {format_price(order.price_open)}",
            f"Market {format_price(current_price)}  ·  {format_price(distance)} away",
        ]
    )


def triggered_message(
    position: OpenPosition,
    *,
    pending_ticket: int | None = None,
) -> str:
    side = "BUY" if position.position_type == 0 else "SELL"
    sl = format_price(position.sl) if position.sl > 0 else "none"
    tp = format_price(position.tp) if position.tp > 0 else "none"
    lines = [
        "✅ Order triggered — trade is live",
        ORDER_SEPARATOR,
        f"#{position.ticket}  {position.symbol}",
        f"{side}  ·  vol {position.volume}",
        f"Entry {format_price(position.price_open)}",
        f"SL {sl}  ·  TP {tp}",
    ]
    if pending_ticket is not None:
        lines.append(f"From pending #{pending_ticket}")
    return "\n".join(lines)


def _close_outcome_label(
    *,
    net_profit: float,
    close_reason: int,
) -> str:
    if close_reason == DEAL_REASON_TP:
        return "Take profit hit ✅"
    if close_reason == DEAL_REASON_SL:
        return "Stop loss hit ❌"
    if net_profit > 0:
        return "Closed in profit ✅"
    if net_profit < 0:
        return "Closed in loss ❌"
    return "Closed at breakeven"


def closed_message(
    *,
    ticket: int,
    symbol: str,
    side: str,
    volume: float,
    open_price: float,
    close_price: float,
    net_profit: float,
    close_reason: int = 0,
    sl: float = 0.0,
    tp: float = 0.0,
) -> str:
    outcome = _close_outcome_label(net_profit=net_profit, close_reason=close_reason)
    sl_text = format_price(sl) if sl > 0 else "none"
    tp_text = format_price(tp) if tp > 0 else "none"
    return "\n".join(
        [
            f"🏁 Trade closed — {outcome}",
            ORDER_SEPARATOR,
            f"#{ticket}  {symbol}  {side}  ·  vol {volume}",
            f"Entry {format_price(open_price)}  →  Exit {format_price(close_price)}",
            f"SL {sl_text}  ·  TP {tp_text}",
            f"Result: {format_money(net_profit)}",
        ]
    )


def weekly_summary_message(
    total_trades: int,
    wins: int,
    profit_sum: float,
    losses: int,
    loss_sum: float,
) -> str:
    net = profit_sum - loss_sum
    net_label = "profit" if net >= 0 else "loss"
    return "\n".join(
        [
            "📊 Weekly trading summary",
            ORDER_SEPARATOR,
            f"Trades: {total_trades}  ({wins} wins · {losses} losses)",
            f"Gross profit: {format_money(profit_sum)}",
            f"Gross loss: {format_money(loss_sum)}",
            f"Net {net_label}: {format_money(net)}",
        ]
    )
