from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from mt5_trigger.config import AppSettings

logger = logging.getLogger(__name__)


class OpenClawNotifier:
    def __init__(self, settings: AppSettings, default_target: str) -> None:
        self.settings = settings
        self.default_target = default_target

    def send(self, message: str, target: str | None = None) -> bool:
        return self._run_send(message=message, media_path=None, target=target)

    def send_media(
        self,
        media_path: str | Path,
        message: str = "",
        target: str | None = None,
        *,
        force_document: bool = False,
    ) -> bool:
        return self._run_send(
            message=message,
            media_path=Path(media_path),
            target=target,
            force_document=force_document,
        )

    def _run_send(
        self,
        *,
        message: str,
        media_path: Path | None,
        target: str | None,
        force_document: bool = False,
    ) -> bool:
        dest = target or self.default_target
        if not dest:
            logger.error("No WhatsApp target configured; skipping send")
            return False
        if not message and media_path is None:
            logger.error("Nothing to send: message and media are both empty")
            return False

        cmd = [
            self.settings.openclaw_bin,
            "message",
            "send",
            "--channel",
            "whatsapp",
            "--target",
            dest,
        ]
        if media_path is not None:
            cmd.extend(["--media", str(media_path)])
        if message:
            cmd.extend(["--message", message])
        if force_document:
            cmd.append("--force-document")

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
