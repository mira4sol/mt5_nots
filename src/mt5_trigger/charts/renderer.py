from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd

from mt5_trigger.mt5.client import OpenPosition, PendingOrder, RateBar, SymbolTick

NY = ZoneInfo("America/New_York")

# Dark trading-terminal palette
BG = "#0d1117"
PANEL = "#161b22"
GRID = "#30363d"
TEXT = "#e6edf3"
MUTED = "#8b949e"
UP = "#3fb950"
DOWN = "#f85149"
BID = "#58a6ff"
ASK = "#79c0ff"
TRIGGER = "#ffa657"
ENTRY = "#a371f7"
SL_COLOR = "#f85149"
TP_COLOR = "#3fb950"


@dataclass(frozen=True)
class PriceLevel:
    price: float
    label: str
    color: str
    linestyle: str = "--"
    linewidth: float = 1.4
    alpha: float = 0.95


def _timeframe_label(minutes: int) -> str:
    mapping = {5: "M5", 15: "M15", 60: "H1", 240: "H4", 1440: "D1"}
    return mapping.get(minutes, f"M{minutes}")


def _build_dataframe(rates: list[RateBar]) -> pd.DataFrame:
    rows = [
        {
            "Open": bar.open,
            "High": bar.high,
            "Low": bar.low,
            "Close": bar.close,
            "Volume": bar.tick_volume,
            "time": datetime.fromtimestamp(bar.time, tz=NY),
        }
        for bar in rates
    ]
    df = pd.DataFrame(rows)
    return df.set_index("time")


def _levels_for_symbol(
    symbol: str,
    *,
    tick: SymbolTick | None,
    pending_orders: list[PendingOrder],
    positions: list[OpenPosition],
) -> list[PriceLevel]:
    levels: list[PriceLevel] = []

    if tick is not None:
        levels.append(
            PriceLevel(tick.bid, f"Bid {tick.bid:.2f}", BID, linestyle=":", linewidth=1.0)
        )
        levels.append(
            PriceLevel(tick.ask, f"Ask {tick.ask:.2f}", ASK, linestyle=":", linewidth=1.0)
        )

    for order in pending_orders:
        if order.symbol != symbol:
            continue
        levels.append(
            PriceLevel(
                order.price_open,
                f"Pending #{order.ticket} {order.order_type_label} @ {order.price_open:.2f}",
                TRIGGER,
                linestyle="--",
            )
        )
        if order.sl > 0:
            levels.append(
                PriceLevel(
                    order.sl,
                    f"Order SL #{order.ticket} {order.sl:.2f}",
                    SL_COLOR,
                    linestyle=":",
                    linewidth=1.0,
                    alpha=0.7,
                )
            )
        if order.tp > 0:
            levels.append(
                PriceLevel(
                    order.tp,
                    f"Order TP #{order.ticket} {order.tp:.2f}",
                    TP_COLOR,
                    linestyle=":",
                    linewidth=1.0,
                    alpha=0.7,
                )
            )

    for pos in positions:
        if pos.symbol != symbol:
            continue
        side = "BUY" if pos.position_type == 0 else "SELL"
        levels.append(
            PriceLevel(
                pos.price_open,
                f"Entry #{pos.ticket} {side} @ {pos.price_open:.2f}",
                ENTRY,
                linestyle="-",
                linewidth=1.8,
            )
        )
        if pos.sl > 0:
            levels.append(
                PriceLevel(
                    pos.sl,
                    f"SL #{pos.ticket} {pos.sl:.2f}",
                    SL_COLOR,
                    linestyle="-",
                    linewidth=1.6,
                )
            )
        if pos.tp > 0:
            levels.append(
                PriceLevel(
                    pos.tp,
                    f"TP #{pos.ticket} {pos.tp:.2f}",
                    TP_COLOR,
                    linestyle="-",
                    linewidth=1.6,
                )
            )

    # De-dupe near-identical prices (keep first label)
    seen: set[float] = set()
    unique: list[PriceLevel] = []
    for level in levels:
        key = round(level.price, 2)
        if key in seen:
            continue
        seen.add(key)
        unique.append(level)
    return unique


def render_symbol_chart(
    *,
    symbol: str,
    rates: list[RateBar],
    output_path: Path,
    tick: SymbolTick | None = None,
    pending_orders: list[PendingOrder] | None = None,
    positions: list[OpenPosition] | None = None,
    timeframe_minutes: int = 5,
) -> Path:
    """Render a dark candlestick chart with live levels overlaid."""
    if not rates:
        raise ValueError("No rate bars to chart")

    pending_orders = pending_orders or []
    positions = positions or []
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df = _build_dataframe(rates)
    levels = _levels_for_symbol(
        symbol,
        tick=tick,
        pending_orders=pending_orders,
        positions=positions,
    )

    mc = mpf.make_marketcolors(
        up=UP,
        down=DOWN,
        edge={"up": UP, "down": DOWN},
        wick={"up": UP, "down": DOWN},
        volume={"up": "#238636", "down": "#da3633"},
        inherit=True,
    )
    style = mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        marketcolors=mc,
        facecolor=BG,
        figcolor=BG,
        edgecolor=GRID,
        gridcolor=GRID,
        gridstyle="--",
        gridaxis="both",
        rc={
            "axes.labelcolor": TEXT,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "axes.edgecolor": GRID,
        },
    )

    last_close = df["Close"].iloc[-1]
    change = last_close - df["Open"].iloc[0]
    change_pct = (change / df["Open"].iloc[0]) * 100 if df["Open"].iloc[0] else 0.0
    tf = _timeframe_label(timeframe_minutes)
    title = (
        f"{symbol}  ·  {tf}  ·  {last_close:.2f}  "
        f"({'+' if change >= 0 else ''}{change:.2f} / {change_pct:+.2f}%)"
    )

    fig, axes = mpf.plot(
        df,
        type="candle",
        style=style,
        volume=True,
        figsize=(13, 7.5),
        returnfig=True,
        datetime_format="%H:%M",
        xrotation=0,
        tight_layout=True,
        scale_padding={"left": 0.35, "top": 0.8, "right": 1.0, "bottom": 0.5},
    )
    ax = axes[0]
    ax.set_title(title, color=TEXT, fontsize=14, fontweight="bold", pad=14)
    ax.set_facecolor(PANEL)

    x_end = len(df) - 1
    x_label = x_end + 0.6

    for level in levels:
        ax.axhline(
            level.price,
            color=level.color,
            linestyle=level.linestyle,
            linewidth=level.linewidth,
            alpha=level.alpha,
        )
        ax.text(
            x_label,
            level.price,
            f"  {level.label}",
            color=level.color,
            fontsize=8.5,
            va="center",
            ha="left",
            clip_on=False,
            bbox={
                "boxstyle": "round,pad=0.25",
                "facecolor": PANEL,
                "edgecolor": level.color,
                "alpha": 0.92,
            },
        )

    # Highlight latest candle
    ax.axvspan(x_end - 0.45, x_end + 0.45, color=TEXT, alpha=0.04)

    legend_lines = [
        "■ Live bid/ask",
        "■ Pending trigger",
        "■ Open entry / SL / TP",
    ]
    fig.text(
        0.015,
        0.02,
        "   ".join(legend_lines),
        color=MUTED,
        fontsize=8,
        ha="left",
    )

    fig.savefig(output_path, dpi=150, facecolor=BG, edgecolor="none", bbox_inches="tight")
    plt.close(fig)
    return output_path
