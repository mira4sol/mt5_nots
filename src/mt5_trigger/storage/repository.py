from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def event_exists(self, account: str, event_type: str, ticket: int | None) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM events WHERE account=? AND event_type=? AND ticket IS ?",
            (account, event_type, ticket),
        ).fetchone()
        return row is not None

    def record_event(
        self,
        account: str,
        event_type: str,
        message: str,
        ticket: int | None = None,
        symbol: str | None = None,
        open_price: float | None = None,
        close_price: float | None = None,
        profit: float | None = None,
    ) -> bool:
        try:
            self.conn.execute(
                """
                INSERT INTO events
                (account, event_type, ticket, symbol, open_price, close_price, profit, message, sent_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account,
                    event_type,
                    ticket,
                    symbol,
                    open_price,
                    close_price,
                    profit,
                    message,
                    _utcnow(),
                ),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_pending_near_alert_sent(self, account: str, ticket: int) -> bool:
        row = self.conn.execute(
            "SELECT near_alert_sent FROM pending_state WHERE account=? AND ticket=?",
            (account, ticket),
        ).fetchone()
        return bool(row and row["near_alert_sent"])

    def set_pending_near_alert(
        self, account: str, ticket: int, sent: bool, distance: float | None
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO pending_state (account, ticket, near_alert_sent, last_distance, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(account, ticket) DO UPDATE SET
                near_alert_sent=excluded.near_alert_sent,
                last_distance=excluded.last_distance,
                updated_at=excluded.updated_at
            """,
            (account, ticket, int(sent), distance, _utcnow()),
        )
        self.conn.commit()

    def clear_pending_state(self, account: str, ticket: int) -> None:
        self.conn.execute(
            "DELETE FROM pending_state WHERE account=? AND ticket=?",
            (account, ticket),
        )
        self.conn.commit()

    def prune_stale_pending(self, account: str, active_tickets: set[int]) -> None:
        rows = self.conn.execute(
            "SELECT ticket FROM pending_state WHERE account=?", (account,)
        ).fetchall()
        for row in rows:
            if row["ticket"] not in active_tickets:
                self.clear_pending_state(account, row["ticket"])

    def track_position(
        self,
        account: str,
        ticket: int,
        symbol: str,
        open_price: float,
        pending_ticket: int | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO position_state (account, ticket, symbol, open_price, pending_ticket, triggered_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(account, ticket) DO NOTHING
            """,
            (account, ticket, symbol, open_price, pending_ticket, _utcnow()),
        )
        self.conn.commit()

    def get_tracked_positions(self, account: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM position_state WHERE account=?", (account,)
        ).fetchall()
        return [dict(r) for r in rows]

    def remove_tracked_position(self, account: str, ticket: int) -> None:
        self.conn.execute(
            "DELETE FROM position_state WHERE account=? AND ticket=?",
            (account, ticket),
        )
        self.conn.commit()

    def weekly_summary_sent(self, account: str, week_start: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM weekly_summary_sent WHERE account=? AND week_start=?",
            (account, week_start),
        ).fetchone()
        return row is not None

    def mark_weekly_summary_sent(self, account: str, week_start: str) -> None:
        self.conn.execute(
            """
            INSERT INTO weekly_summary_sent (account, week_start, sent_at)
            VALUES (?, ?, ?)
            ON CONFLICT(account, week_start) DO NOTHING
            """,
            (account, week_start, _utcnow()),
        )
        self.conn.commit()

    def update_watcher_status(
        self,
        account: str,
        connected: bool,
        last_error: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO watcher_status (account, connected, last_poll_at, last_error)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(account) DO UPDATE SET
                connected=excluded.connected,
                last_poll_at=excluded.last_poll_at,
                last_error=excluded.last_error
            """,
            (account, int(connected), _utcnow(), last_error),
        )
        self.conn.commit()

    def get_all_watcher_status(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM watcher_status").fetchall()
        return [dict(r) for r in rows]

    def get_week_stats_from_events(self, account: str, week_start: str) -> dict[str, Any]:
        rows = self.conn.execute(
            """
            SELECT profit, event_type FROM events
            WHERE account=? AND event_type='closed' AND sent_at >= ?
            """,
            (account, week_start),
        ).fetchall()
        total = len(rows)
        wins = sum(1 for r in rows if r["profit"] and r["profit"] > 0)
        losses = sum(1 for r in rows if r["profit"] is not None and r["profit"] <= 0)
        profit_sum = sum(r["profit"] for r in rows if r["profit"] and r["profit"] > 0)
        loss_sum = sum(abs(r["profit"]) for r in rows if r["profit"] is not None and r["profit"] <= 0)
        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "profit_sum": profit_sum or 0.0,
            "loss_sum": loss_sum or 0.0,
        }

    def ping(self) -> bool:
        try:
            self.conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False
