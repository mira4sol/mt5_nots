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

    def send(
        self,
        message: str,
        target: str | None = None,
        *,
        reply_to: str | None = None,
    ) -> bool:
        return self._run_send(
            message=message,
            media_path=None,
            target=target,
            reply_to=reply_to,
        )

    def send_media(
        self,
        media_path: str | Path,
        message: str = "",
        target: str | None = None,
        *,
        force_document: bool = False,
        reply_to: str | None = None,
    ) -> bool:
        return self._run_send(
            message=message,
            media_path=Path(media_path),
            target=target,
            force_document=force_document,
            reply_to=reply_to,
        )

    def _run_send(
        self,
        *,
        message: str,
        media_path: Path | None,
        target: str | None,
        force_document: bool = False,
        reply_to: str | None = None,
    ) -> bool:
        dest = target or self.default_target
        if not dest:
            logger.error("WhatsApp send skipped: no target configured")
            return False
        if not message and media_path is None:
            logger.error(
                "WhatsApp send skipped: empty message and no media (target=%s)",
                dest,
            )
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
        if reply_to:
            cmd.extend(["--reply-to", reply_to])
        if force_document:
            cmd.append("--force-document")

        max_retries = self.settings.openclaw.max_retries
        base = self.settings.openclaw.retry_base_seconds
        kind = "media" if media_path is not None else "text"
        last_detail = ""

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
                    logger.info(
                        "WhatsApp %s sent via OpenClaw (target=%s reply_to=%s)",
                        kind,
                        dest,
                        reply_to or "-",
                    )
                    return True
                last_detail = (result.stderr or result.stdout or "").strip()
                logger.warning(
                    "OpenClaw send failed (attempt %d/%d, kind=%s, target=%s, "
                    "reply_to=%s, timeout=%ss): %s",
                    attempt + 1,
                    max_retries,
                    kind,
                    dest,
                    reply_to or "-",
                    self.settings.openclaw.send_timeout_seconds,
                    last_detail or "(no output)",
                )
            except (subprocess.SubprocessError, OSError) as exc:
                last_detail = str(exc)
                logger.warning(
                    "OpenClaw send error (attempt %d/%d, kind=%s, target=%s, "
                    "reply_to=%s, timeout=%ss): %s",
                    attempt + 1,
                    max_retries,
                    kind,
                    dest,
                    reply_to or "-",
                    self.settings.openclaw.send_timeout_seconds,
                    exc,
                )
            if attempt < max_retries - 1:
                time.sleep(base * (2**attempt))
        logger.error(
            "WhatsApp %s not delivered after %d attempts (target=%s reply_to=%s): %s",
            kind,
            max_retries,
            dest,
            reply_to or "-",
            last_detail or "unknown error",
        )
        return False
