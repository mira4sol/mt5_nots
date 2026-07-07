from __future__ import annotations

import argparse
import logging
import multiprocessing as mp
import shutil
import sys
from pathlib import Path

from mt5_trigger.config import PROJECT_ROOT, load_config
from mt5_trigger.watcher.supervisor import run_health_server, run_supervisor

logger = logging.getLogger(__name__)


def _ensure_accounts_config() -> None:
    accounts_path = PROJECT_ROOT / "config" / "accounts.yaml"
    example_path = PROJECT_ROOT / "config" / "accounts.yaml.example"
    if not accounts_path.exists() and example_path.exists():
        shutil.copy(example_path, accounts_path)
        logger.info("Created config/accounts.yaml from example — edit with your credentials")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="MT5 Trigger Monitor")
    parser.add_argument(
        "--settings",
        type=Path,
        default=None,
        help="Path to settings.yaml",
    )
    parser.add_argument(
        "--accounts",
        type=Path,
        default=None,
        help="Path to accounts.yaml",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    _ensure_accounts_config()
    config = load_config(
        settings_path=args.settings,
        accounts_path=args.accounts,
    )

    mp.set_start_method("spawn", force=True)

    health_proc = mp.Process(
        target=run_health_server,
        args=(config,),
        name="health-server",
        daemon=True,
    )
    health_proc.start()
    logger.info(
        "Health endpoint at http://%s:%s/health",
        config.settings.health_host,
        config.settings.health_port,
    )

    try:
        run_supervisor(config)
    except KeyboardInterrupt:
        logger.info("Interrupted")
        sys.exit(0)


if __name__ == "__main__":
    main()
