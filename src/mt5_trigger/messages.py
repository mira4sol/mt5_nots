from __future__ import annotations


def format_price(price: float, digits: int = 5) -> str:
    return f"{price:.{digits}f}"


def format_money(amount: float) -> str:
    return f"${abs(amount):,.2f}"


def near_trigger_message(
    symbol: str,
    order_type_label: str,
    trigger_price: float,
    current_price: float,
) -> str:
    return (
        f"{symbol} pending {order_type_label} at {format_price(trigger_price)} "
        f"about to trigger (current {format_price(current_price)})"
    )


def closed_profit_message(open_price: float, close_price: float, profit: float) -> str:
    return (
        f"order {format_price(open_price)} closed at {format_price(close_price)},\n"
        f"secured ✅\n"
        f"profit: {format_money(profit)}"
    )


def closed_loss_message(open_price: float, close_price: float, loss: float) -> str:
    return (
        f"order {format_price(open_price)} closed at {format_price(close_price)},\n"
        f"lost ❌\n"
        f"lost: {format_money(loss)}"
    )


def weekly_summary_message(
    total_trades: int,
    wins: int,
    profit_sum: float,
    losses: int,
    loss_sum: float,
) -> str:
    return (
        f"we made {total_trades} trades this week\n"
        f"we secured {wins} and made profit of {format_money(profit_sum)}\n"
        f"we lost {losses} trades and lost total of {format_money(loss_sum)}"
    )
