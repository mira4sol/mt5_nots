from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from matplotlib.transforms import blended_transform_factory

from mt5_trigger.mt5.client import (
    OpenPosition,
    PendingOrder,
    RateBar,
    SymbolTick,
    distance_to_trigger,
)

NY = ZoneInfo("America/New_York")

# TradingView-inspired dark palette
BG = "#131722"
PANEL = "#131722"
GRID = "#2a2e39"
TEXT = "#d1d4dc"
MUTED = "#787b86"
UP = "#26a69a"
DOWN = "#ef5350"
LAST_PRICE = "#2962ff"
BID = "#787b86"
ASK = "#787b86"
PENDING = "#f7931a"
ENTRY = "#ab47bc"
SL_COLOR = "#ef5350"
TP_COLOR = "#26a69a"

MAX_CHART_WIDTH_PX = 2048
MAX_CHART_HEIGHT_PX = 2048
CHART_DPI = 130

MAX_PENDING_ON_CHART = 3


@dataclass(frozen=True)
class ChartLine:
    price: float
    tag: str
    color: str
    linestyle: str = "-"
    linewidth: float = 1.2
    alpha: float = 0.95
    zorder: int = 3


@dataclass
class OffChartSummary:
    pending_above: list[str]
    pending_below: list[str]


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


def _candle_bounds(df: pd.DataFrame, *, pad_ratio: float = 0.045) -> tuple[float, float]:
    low = float(df["Low"].min())
    high = float(df["High"].max())
    span = max(high - low, 0.01)
    pad = span * pad_ratio
    return low - pad, high + pad


def _in_range(price: float, y_min: float, y_max: float) -> bool:
    return y_min <= price <= y_max


def _maybe_extend_bounds(
    y_min: float,
    y_max: float,
    prices: list[float],
    *,
    max_extra_ratio: float = 0.12,
) -> tuple[float, float]:
    """Extend candle bounds slightly for nearby open-trade levels only."""
    if not prices:
        return y_min, y_max
    span = y_max - y_min
    extra = span * max_extra_ratio
    for price in prices:
        if price < y_min and (y_min - price) <= extra:
            y_min = price - span * 0.01
        elif price > y_max and (price - y_max) <= extra:
            y_max = price + span * 0.01
    return y_min, y_max


def _build_overlays(
    symbol: str,
    df: pd.DataFrame,
    *,
    tick: SymbolTick | None,
    pending_orders: list[PendingOrder],
    positions: list[OpenPosition],
    y_min: float,
    y_max: float,
) -> tuple[list[ChartLine], OffChartSummary]:
    lines: list[ChartLine] = []
    pending_above: list[str] = []
    pending_below: list[str] = []

    last_close = float(df["Close"].iloc[-1])
    lines.append(
        ChartLine(
            last_close,
            f"{last_close:.2f}",
            LAST_PRICE,
            linestyle="-",
            linewidth=2.2,
            zorder=10,
        )
    )

    symbol_pending = [o for o in pending_orders if o.symbol == symbol]
    if tick is not None and symbol_pending:
        ranked = sorted(
            symbol_pending,
            key=lambda o: distance_to_trigger(o, tick),
        )
    else:
        ranked = symbol_pending

    for order in ranked[:MAX_PENDING_ON_CHART]:
        label = f"#{order.ticket} {order.order_type_label.split()[0]} {order.price_open:.2f}"
        if _in_range(order.price_open, y_min, y_max):
            lines.append(
                ChartLine(
                    order.price_open,
                    label,
                    PENDING,
                    linestyle="--",
                    linewidth=1.4,
                    zorder=6,
                )
            )
        elif order.price_open > y_max:
            pending_above.append(label)
        else:
            pending_below.append(label)

    for order in ranked[MAX_PENDING_ON_CHART:]:
        label = f"#{order.ticket} {order.order_type_label.split()[0]} {order.price_open:.2f}"
        if order.price_open > y_max:
            pending_above.append(label)
        else:
            pending_below.append(label)

    position_prices: list[float] = []
    for pos in positions:
        if pos.symbol != symbol:
            continue
        side = "BUY" if pos.position_type == 0 else "SELL"
        position_prices.extend([p for p in (pos.price_open, pos.sl, pos.tp) if p > 0])

        if _in_range(pos.price_open, y_min, y_max):
            lines.append(
                ChartLine(
                    pos.price_open,
                    f"ENTRY {side} {pos.price_open:.2f}",
                    ENTRY,
                    linewidth=1.8,
                    zorder=7,
                )
            )
        if pos.sl > 0 and _in_range(pos.sl, y_min, y_max):
            lines.append(
                ChartLine(
                    pos.sl,
                    f"SL {pos.sl:.2f}",
                    SL_COLOR,
                    linewidth=1.6,
                    zorder=7,
                )
            )
        if pos.tp > 0 and _in_range(pos.tp, y_min, y_max):
            lines.append(
                ChartLine(
                    pos.tp,
                    f"TP {pos.tp:.2f}",
                    TP_COLOR,
                    linewidth=1.6,
                    zorder=7,
                )
            )

    # De-dupe lines at same price (keep highest zorder / first)
    seen: dict[float, ChartLine] = {}
    for line in sorted(lines, key=lambda item: item.zorder, reverse=True):
        key = round(line.price, 2)
        if key not in seen:
            seen[key] = line
    ordered = sorted(seen.values(), key=lambda item: item.price)

    summary = OffChartSummary(
        pending_above=pending_above[:6],
        pending_below=pending_below[:6],
    )
    return ordered, summary


def _draw_price_tag(
    ax: plt.Axes,
    line: ChartLine,
    *,
    highlight: bool = False,
) -> None:
    trans = blended_transform_factory(ax.transAxes, ax.transData)
    ax.axhline(
        line.price,
        color=line.color,
        linestyle=line.linestyle,
        linewidth=line.linewidth,
        alpha=line.alpha,
        zorder=line.zorder,
        xmin=0.0,
        xmax=0.996,
    )

    fontsize = 9 if highlight else 7.5
    weight = "bold" if highlight else "normal"
    face = line.color if highlight else "#1e222d"
    edge = line.color
    text_color = "#ffffff" if highlight else line.color

    ax.text(
        1.002,
        line.price,
        f" {line.tag} ",
        transform=trans,
        color=text_color,
        fontsize=fontsize,
        fontweight=weight,
        va="center",
        ha="left",
        clip_on=True,
        zorder=line.zorder + 1,
        bbox={
            "boxstyle": "round,pad=0.25",
            "facecolor": face if highlight else "#1e222d",
            "edgecolor": edge,
            "linewidth": 1.2 if highlight else 0.8,
            "alpha": 0.98,
        },
    )


def _draw_offscreen_note(ax: plt.Axes, summary: OffChartSummary) -> None:
    parts: list[str] = []
    if summary.pending_above:
        parts.append(f"↑ {len(summary.pending_above)} pending above")
    if summary.pending_below:
        parts.append(f"↓ {len(summary.pending_below)} pending below")
    if not parts:
        return
    ax.text(
        0.01,
        0.98,
        "  ·  ".join(parts),
        transform=ax.transAxes,
        color=MUTED,
        fontsize=8,
        va="top",
        ha="left",
        bbox={
            "boxstyle": "round,pad=0.35",
            "facecolor": "#1e222d",
            "edgecolor": GRID,
            "alpha": 0.9,
        },
    )


def _save_figure(fig: plt.Figure, output_path: Path) -> None:
    fig.savefig(
        output_path,
        dpi=CHART_DPI,
        facecolor=BG,
        edgecolor="none",
        bbox_inches=None,
        pad_inches=0.05,
    )

    try:
        from PIL import Image
    except ImportError:
        return

    with Image.open(output_path) as img:
        width, height = img.size
        if width <= MAX_CHART_WIDTH_PX and height <= MAX_CHART_HEIGHT_PX:
            return
        scale = min(
            MAX_CHART_WIDTH_PX / width,
            MAX_CHART_HEIGHT_PX / height,
            1.0,
        )
        resized = img.resize(
            (int(width * scale), int(height * scale)),
            Image.Resampling.LANCZOS,
        )
        resized.save(output_path, format="PNG", optimize=True)


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
    """Render a TradingView-style candlestick chart focused on live price action."""
    if not rates:
        raise ValueError("No rate bars to chart")

    pending_orders = pending_orders or []
    positions = positions or []
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df = _build_dataframe(rates)
    y_min, y_max = _candle_bounds(df)

    position_prices: list[float] = []
    for pos in positions:
        if pos.symbol == symbol:
            position_prices.extend(
                p for p in (pos.price_open, pos.sl, pos.tp) if p > 0
            )
    y_min, y_max = _maybe_extend_bounds(y_min, y_max, position_prices)

    lines, offscreen = _build_overlays(
        symbol,
        df,
        tick=tick,
        pending_orders=pending_orders,
        positions=positions,
        y_min=y_min,
        y_max=y_max,
    )

    mc = mpf.make_marketcolors(
        up=UP,
        down=DOWN,
        edge={"up": UP, "down": DOWN},
        wick={"up": UP, "down": DOWN},
        volume={"up": "#26a69a", "down": "#ef5350"},
        inherit=True,
    )
    style = mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        marketcolors=mc,
        facecolor=PANEL,
        figcolor=BG,
        edgecolor=GRID,
        gridcolor=GRID,
        gridstyle="-",
        gridaxis="horizontal",
        rc={
            "axes.labelcolor": MUTED,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "axes.edgecolor": GRID,
            "font.size": 9,
        },
    )

    last_close = float(df["Close"].iloc[-1])
    change = last_close - float(df["Open"].iloc[0])
    change_pct = (change / float(df["Open"].iloc[0])) * 100 if df["Open"].iloc[0] else 0.0
    tf = _timeframe_label(timeframe_minutes)
    change_color = UP if change >= 0 else DOWN
    title = f"{symbol}  ·  {tf}"

    fig, axes = mpf.plot(
        df,
        type="candle",
        style=style,
        volume=True,
        figsize=(13.5, 7.5),
        returnfig=True,
        datetime_format="%H:%M",
        xrotation=0,
        warn_too_much_data=10000,
    )
    ax = axes[0]
    ax.set_facecolor(PANEL)
    ax.set_ylim(y_min, y_max)
    ax.grid(True, which="major", axis="y", alpha=0.35)
    ax.grid(False, axis="x")

    # Title row like TradingView (stacked so long prices don't overlap change text)
    fig.text(0.03, 0.965, title, color=TEXT, fontsize=15, fontweight="bold", ha="left", va="top")
    fig.text(
        0.03,
        0.918,
        f"{last_close:.2f}",
        color=change_color,
        fontsize=22,
        fontweight="bold",
        ha="left",
        va="top",
    )
    fig.text(
        0.03,
        0.882,
        f"{'+' if change >= 0 else ''}{change:.2f}  ({change_pct:+.2f}%)",
        color=change_color,
        fontsize=11,
        ha="left",
        va="top",
    )
    if tick is not None:
        fig.text(
            0.03,
            0.852,
            f"Bid {tick.bid:.2f}   Ask {tick.ask:.2f}",
            color=MUTED,
            fontsize=9,
            ha="left",
            va="top",
        )

    # Highlight latest candle column
    x_end = len(df) - 1
    ax.axvspan(x_end - 0.5, x_end + 0.5, color=LAST_PRICE, alpha=0.06, zorder=1)

    for line in lines:
        highlight = line.color == LAST_PRICE
        _draw_price_tag(ax, line, highlight=highlight)

    _draw_offscreen_note(ax, offscreen)

    # Compact legend
    legend = "Last price  ·  Pending (nearest)  ·  Entry / SL / TP"
    fig.text(0.03, 0.03, legend, color=MUTED, fontsize=8, ha="left")

    fig.subplots_adjust(left=0.06, right=0.74, top=0.80, bottom=0.10, hspace=0.04)
    _save_figure(fig, output_path)
    plt.close(fig)
    return output_path
