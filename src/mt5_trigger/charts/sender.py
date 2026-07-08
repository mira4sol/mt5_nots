from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from mt5_trigger.config import AppSettings
from mt5_trigger.mt5.backend import TIMEFRAME_M5
from mt5_trigger.mt5.client import MT5Client, SymbolTick
from mt5_trigger.notify.openclaw import OpenClawNotifier

DEFAULT_SYMBOL_CANDIDATES = ("XAUUSD.vx", "XAUUSD", "XAUUSDm", "GOLD")
DEFAULT_BAR_COUNT = 100


@dataclass(frozen=True)
class ChartSendResult:
    symbol: str
    output_path: Path
    caption: str
    pending_count: int
    open_count: int
    sent: bool = False


def _ensure_chart_deps() -> None:
    try:
        import mplfinance  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "Chart dependencies missing. Run: make install-charts"
        ) from exc


def resolve_gold_symbol(client: MT5Client, preferred: str | None = None) -> str:
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


def build_chart_caption(
    *,
    symbol: str,
    pending_count: int,
    open_count: int,
    tick: SymbolTick | None,
) -> str:
    caption = (
        f"📈 Live chart · {symbol} M5\n"
        f"Pending {pending_count} · Open {open_count}"
    )
    if tick is not None:
        caption += f"\nBid {tick.bid:.2f} · Ask {tick.ask:.2f}"
    return caption


def send_live_chart(
    *,
    client: MT5Client,
    settings: AppSettings,
    charts_dir: Path,
    symbol: str | None = None,
    bars: int = DEFAULT_BAR_COUNT,
    whatsapp_target: str | None = None,
    send: bool = True,
    force_document: bool = False,
) -> ChartSendResult:
    """Render the current live chart and optionally send it to WhatsApp."""
    _ensure_chart_deps()

    resolved = resolve_gold_symbol(client, symbol)
    rates = client.get_rates(resolved, TIMEFRAME_M5, count=bars)
    if not rates:
        raise RuntimeError(f"No M5 candle data returned for {resolved}")

    tick = client.get_tick(resolved)
    pending = [o for o in client.get_pending_orders() if o.symbol == resolved]
    positions = [p for p in client.get_positions() if p.symbol == resolved]

    charts_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = charts_dir / f"{resolved}_{ts}.png"

    from mt5_trigger.charts.renderer import render_symbol_chart

    render_symbol_chart(
        symbol=resolved,
        rates=rates,
        output_path=output_path,
        tick=tick,
        pending_orders=pending,
        positions=positions,
        timeframe_minutes=5,
    )

    caption = build_chart_caption(
        symbol=resolved,
        pending_count=len(pending),
        open_count=len(positions),
        tick=tick,
    )

    sent = False
    if send:
        if not whatsapp_target:
            raise RuntimeError("No WhatsApp target configured for chart send")
        notifier = OpenClawNotifier(settings, whatsapp_target)
        sent = notifier.send_media(
            output_path,
            message=caption,
            target=whatsapp_target,
            force_document=force_document,
        )
        if not sent:
            raise RuntimeError("Failed to send chart via OpenClaw")

    return ChartSendResult(
        symbol=resolved,
        output_path=output_path,
        caption=caption,
        pending_count=len(pending),
        open_count=len(positions),
        sent=sent,
    )
