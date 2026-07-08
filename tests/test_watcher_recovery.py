from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from mt5_trigger.config import AccountConfig, AppConfig, AppSettings
from mt5_trigger.mt5.client import ClosedDeal
from mt5_trigger.storage.db import init_db
from mt5_trigger.storage.repository import EventRepository
from mt5_trigger.watcher.account_watcher import AccountWatcher

NY = ZoneInfo("America/New_York")


def _watcher(tmp_path) -> AccountWatcher:
    settings = AppSettings(db_path=str(tmp_path / "test.db"))
    config = AppConfig(
        settings=settings,
        accounts=[
            AccountConfig(
                name="test",
                login="1",
                password="x",
                server="srv",
                whatsapp_target="+10000000000",
            )
        ],
    )
    watcher = AccountWatcher(config.accounts[0], config)
    watcher.client = MagicMock()
    watcher.notifier = MagicMock()
    return watcher


def test_close_alert_recorded_before_send_prevents_duplicates(tmp_path) -> None:
    watcher = _watcher(tmp_path)
    tracked = {
        "ticket": 100,
        "symbol": "XAUUSD.vx",
        "open_price": 4100.0,
        "position_type": 0,
        "volume": 0.01,
        "sl": 0.0,
        "tp": 0.0,
    }
    deals = [
        ClosedDeal(
            ticket=1,
            position_id=100,
            symbol="XAUUSD.vx",
            price=4110.0,
            profit=10.0,
            swap=0.0,
            commission=0.0,
            time=0,
            reason=0,
        )
    ]

    watcher._notify_closed_position(tracked, deals, trade_alerts=True)
    watcher._notify_closed_position(tracked, deals, trade_alerts=True)

    assert watcher.notifier.send.call_count == 1
    assert watcher.repo.event_exists("test", "closed", 100)


def test_recovery_skips_untracked_historical_closes(tmp_path) -> None:
    watcher = _watcher(tmp_path)
    watcher.client.get_recent_closed_positions.return_value = {
        98537561: [
            ClosedDeal(
                ticket=1,
                position_id=98537561,
                symbol="XAUUSD.vx",
                price=4170.17,
                profit=5.1,
                swap=0.0,
                commission=0.0,
                time=0,
                reason=0,
            )
        ]
    }

    watcher._recover_missed_closes(datetime(2026, 7, 8, 6, 57, tzinfo=NY))

    watcher.notifier.send.assert_not_called()
    assert not watcher.repo.event_exists("test", "closed", 98537561)


def test_recovery_alerts_only_tracked_positions(tmp_path) -> None:
    watcher = _watcher(tmp_path)
    watcher.repo.track_position(
        "test",
        200,
        "XAUUSD.vx",
        4100.0,
        pending_ticket=None,
        position_type=0,
        volume=0.01,
    )
    watcher.client.get_recent_closed_positions.return_value = {
        200: [
            ClosedDeal(
                ticket=2,
                position_id=200,
                symbol="XAUUSD.vx",
                price=4110.0,
                profit=8.0,
                swap=0.0,
                commission=0.0,
                time=0,
                reason=0,
            )
        ]
    }

    watcher._recover_missed_closes(datetime(2026, 7, 8, 6, 57, tzinfo=NY))

    watcher.notifier.send.assert_called_once()
    assert watcher.repo.event_exists("test", "closed", 200)
