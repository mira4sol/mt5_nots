from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable

from mt5_trigger.notify.openclaw import OpenClawNotifier

logger = logging.getLogger(__name__)


class AsyncNotifier:
    """Send WhatsApp alerts on a background thread so MT5 polling never blocks."""

    def __init__(self, notifier: OpenClawNotifier) -> None:
        self._notifier = notifier
        self._queue: queue.Queue[tuple[str, Callable[[], None] | None] | None] = queue.Queue()
        self._thread = threading.Thread(target=self._worker, name="alert-sender", daemon=True)
        self._thread.start()

    def send(self, message: str, on_success: Callable[[], None] | None = None) -> None:
        self._queue.put((message, on_success))

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            message, on_success = item
            try:
                if self._notifier.send(message):
                    if on_success is not None:
                        on_success()
            except Exception:
                logger.exception("Async alert send failed")
