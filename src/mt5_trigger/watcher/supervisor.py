from __future__ import annotations

import logging
import multiprocessing as mp
import signal
import time
from typing import Any

import uvicorn

from mt5_trigger.api.app import create_app
from mt5_trigger.config import AppConfig, enabled_accounts
from mt5_trigger.runtime import reset_uptime
from mt5_trigger.watcher.account_watcher import run_account_watcher

logger = logging.getLogger(__name__)

_processes: list[mp.Process] = []


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
    global _processes

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


def run_health_server(config: AppConfig) -> None:
    reset_uptime()
    app = create_app(config)
    uvicorn.run(
        app,
        host=config.settings.health_host,
        port=config.settings.health_port,
        log_level="info",
    )
