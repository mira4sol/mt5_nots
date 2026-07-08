from __future__ import annotations

import logging
import subprocess
import time

from mt5_trigger.config import AppSettings

logger = logging.getLogger(__name__)


class OpenClawNotifier:
    def __init__(self, settings: AppSettings, default_target: str) -> None:
        self.settings = settings
        self.default_target = default_target

    def send(self, message: str, target: str | None = None) -> bool:
        dest = target or self.default_target
        if not dest:
            logger.error("No WhatsApp target configured; skipping send")
            return False

        cmd = [
            self.settings.openclaw_bin,
            "message",
            "send",
            "--channel",
            "whatsapp",
            "--target",
            dest,
            "--message",
            message,
        ]
        max_retries = self.settings.openclaw.max_retries
        base = self.settings.openclaw.retry_base_seconds

        for attempt in range(max_retries):
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.settings.openclaw.send_timeout_seconds,
                    check=False,
                )
                if result.returncode == 0:
                    logger.info("WhatsApp message sent via OpenClaw")
                    return True
                logger.warning(
                    "OpenClaw send failed (attempt %d/%d): %s",
                    attempt + 1,
                    max_retries,
                    result.stderr or result.stdout,
                )
            except (subprocess.SubprocessError, OSError) as exc:
                logger.warning(
                    "OpenClaw send error (attempt %d/%d): %s",
                    attempt + 1,
                    max_retries,
                    exc,
                )
            if attempt < max_retries - 1:
                time.sleep(base * (2**attempt))
        return False
