from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class MarketHoursConfig:
    rollover_blackout_minutes: int = 30
    daily_rollover_blackout_minutes: int = 5


@dataclass(frozen=True)
class MarketStatus:
    is_open: bool
    in_blackout: bool
    reason: str
    now_et: datetime


def _to_et(dt: datetime | None = None) -> datetime:
    if dt is None:
        dt = datetime.now(tz=NY)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=NY)
    else:
        dt = dt.astimezone(NY)
    return dt


def _within_minutes(target: datetime, now: datetime, minutes: int) -> bool:
    delta = abs((now - target).total_seconds())
    return delta <= minutes * 60


def _week_open_close(now_et: datetime) -> tuple[datetime, datetime]:
    """Return (week_open, week_close) for the trading week containing now_et."""
    weekday = now_et.weekday()  # Mon=0 .. Sun=6
    week_open_day = now_et - timedelta(days=(weekday + 1) % 7)
    week_open = datetime.combine(
        week_open_day.date(), time(17, 0), tzinfo=NY
    )
    if weekday == 6 and now_et < week_open:
        week_open -= timedelta(days=7)
    week_close = week_open + timedelta(days=5)
    return week_open, week_close


def get_market_status(
    cfg: MarketHoursConfig | None = None,
    now: datetime | None = None,
) -> MarketStatus:
    cfg = cfg or MarketHoursConfig()
    now_et = _to_et(now)
    week_open, week_close = _week_open_close(now_et)

    if now_et < week_open or now_et >= week_close:
        return MarketStatus(
            is_open=False,
            in_blackout=True,
            reason="market_closed_weekend",
            now_et=now_et,
        )

    blackout_targets = [
        (week_open, "weekly_open"),
        (week_close, "weekly_close"),
    ]
    for day_offset in range(5):
        day = (week_open + timedelta(days=day_offset)).date()
        blackout_targets.append(
            (datetime.combine(day, time(17, 0), tzinfo=NY), "daily_rollover")
        )

    for target, label in blackout_targets:
        minutes = (
            cfg.rollover_blackout_minutes
            if label.startswith("weekly")
            else cfg.daily_rollover_blackout_minutes
        )
        if _within_minutes(target, now_et, minutes):
            return MarketStatus(
                is_open=False,
                in_blackout=True,
                reason=label,
                now_et=now_et,
            )

    return MarketStatus(
        is_open=True,
        in_blackout=False,
        reason="open",
        now_et=now_et,
    )


def should_send_trade_alerts(
    cfg: MarketHoursConfig | None = None,
    now: datetime | None = None,
) -> bool:
    """Near-trigger, triggered, and close alerts — only while FX market is open."""
    status = get_market_status(cfg, now)
    return status.is_open and not status.in_blackout


def should_send_near_trigger_alerts(
    cfg: MarketHoursConfig | None = None,
    now: datetime | None = None,
) -> bool:
    return should_send_trade_alerts(cfg, now)


def should_send_weekly_summary(
    cfg: MarketHoursConfig | None = None,
    now: datetime | None = None,
) -> bool:
    status = get_market_status(cfg, now)
    return not status.is_open and status.reason == "market_closed_weekend"


def week_start_for(now: datetime | None = None) -> str:
    """ISO date string (Sunday) for the trading week containing now."""
    now_et = _to_et(now)
    week_open, _ = _week_open_close(now_et)
    return week_open.date().isoformat()
