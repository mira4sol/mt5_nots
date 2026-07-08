from __future__ import annotations

import time

_start_time = time.time()


def get_uptime() -> float:
    return time.time() - _start_time


def reset_uptime() -> None:
    global _start_time
    _start_time = time.time()
