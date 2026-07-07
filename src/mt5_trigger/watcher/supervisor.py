from __future__ import annotations

import logging
import multiprocessing as mp
import signal
import time
from typing import Any

import uvicorn

from mt5_trigger.config import AppConfig, enabled_accounts, load_config
from mt5_trigger.market_hours import get_market_status, MarketHoursConfig
from mt5_trigger.storage.db import init_db
from mt5_trigger.storage.repository import EventRepository
from mt5_trigger.watcher.account_watcher import run_account_watcher

logger = logging.getLogger(__name__)

_processes: list[mp.Process] = []
_start_time = time.time()


def _start_watchers(config: AppConfig) -> list[mp.Process]:
    accounts = enabled_accounts(config)
    if not accounts:
        logger.warning("No enabled accounts found in config")
        return []

    processes: list[mp.Process] = []
    for account in accounts:
        proc = mp.Process(
            target=run_account_watcher,
            args=(account, config),
            name=f"watcher-{account.name}",
            daemon=True,
        )
        proc.start()
        processes.append(proc)
        logger.info("Started watcher process for %s (pid=%s)", account.name, proc.pid)
    return processes


def _shutdown(signum: int | None = None, frame: Any = None) -> None:
    logger.info("Shutting down watchers...")
    for proc in _processes:
        if proc.is_alive():
            proc.terminate()
    for proc in _processes:
        proc.join(timeout=5)
    raise SystemExit(0)


def run_supervisor(config: AppConfig) -> None:
    global _processes, _start_time
    _start_time = time.time()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    _processes = _start_watchers(config)

    account_by_name = {a.name: a for a in enabled_accounts(config)}

    while True:
        for i, proc in enumerate(list(_processes)):
            if proc.is_alive():
                continue
            account_name = proc.name.removeprefix("watcher-")
            account = account_by_name.get(account_name)
            if account is None:
                continue
            logger.error("Watcher %s died; restarting", proc.name)
            new_proc = mp.Process(
                target=run_account_watcher,
                args=(account, config),
                name=f"watcher-{account.name}",
                daemon=True,
            )
            new_proc.start()
            _processes[i] = new_proc
        time.sleep(5)


def get_uptime() -> float:
    return time.time() - _start_time


def create_health_app(config: AppConfig):
    from fastapi import FastAPI

    app = FastAPI(title="MT5 Trigger Monitor", version="0.1.0")
    db_path = config.settings.db_path_resolved
    conn = init_db(db_path)
    repo = EventRepository(conn)
    market_cfg = MarketHoursConfig(
        rollover_blackout_minutes=config.settings.near_trigger.rollover_blackout_minutes,
        daily_rollover_blackout_minutes=config.settings.near_trigger.daily_rollover_blackout_minutes,
    )

    @app.get("/health")
    def health():
        market = get_market_status(market_cfg)
        statuses = repo.get_all_watcher_status()
        account_map = {s["account"]: s for s in statuses}
        accounts_info = []
        for account in enabled_accounts(config):
            s = account_map.get(account.name, {})
            accounts_info.append(
                {
                    "name": account.name,
                    "connected": bool(s.get("connected")),
                    "last_poll_at": s.get("last_poll_at"),
                    "last_error": s.get("last_error"),
                }
            )
        all_ok = repo.ping()
        return {
            "status": "ok" if all_ok else "degraded",
            "uptime_seconds": round(get_uptime()),
            "market_open": market.is_open and not market.in_blackout,
            "market_reason": market.reason,
            "accounts": accounts_info,
            "db_ok": all_ok,
        }

    return app


def run_health_server(config: AppConfig) -> None:
    app = create_health_app(config)
    uvicorn.run(
        app,
        host=config.settings.health_host,
        port=config.settings.health_port,
        log_level="info",
    )
