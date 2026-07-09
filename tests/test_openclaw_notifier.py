from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from mt5_trigger.config import AppSettings
from mt5_trigger.notify.openclaw import OpenClawNotifier, clear_send_dedupe_for_tests


def test_send_includes_reply_to_flag() -> None:
    settings = AppSettings(openclaw_bin="/usr/bin/openclaw")
    notifier = OpenClawNotifier(settings, "+10000000000")

    with patch("mt5_trigger.notify.openclaw.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        ok = notifier.send("positions summary", reply_to="ABC123")

    assert ok is True
    cmd = run.call_args.args[0]
    assert "--reply-to" in cmd
    assert "ABC123" in cmd


def test_send_media_includes_reply_to_flag(tmp_path: Path) -> None:
    settings = AppSettings(openclaw_bin="/usr/bin/openclaw")
    notifier = OpenClawNotifier(settings, "120363428584387160@g.us")
    image = tmp_path / "chart.png"
    image.write_bytes(b"png")

    with patch("mt5_trigger.notify.openclaw.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        ok = notifier.send_media(image, reply_to="MSG456")

    assert ok is True
    cmd = run.call_args.args[0]
    assert "--reply-to" in cmd
    assert "MSG456" in cmd


def test_send_skips_duplicate_payload() -> None:
    clear_send_dedupe_for_tests()
    settings = AppSettings(openclaw_bin="/usr/bin/openclaw")
    notifier = OpenClawNotifier(settings, "+10000000000")

    with patch("mt5_trigger.notify.openclaw.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        assert notifier.send("Trade closed", reply_to="MSG789") is True
        assert notifier.send("Trade closed", reply_to="MSG789") is True

    assert run.call_count == 1


def test_send_does_not_retry_nonzero_exit() -> None:
    clear_send_dedupe_for_tests()
    settings = AppSettings(openclaw_bin="/usr/bin/openclaw", openclaw={"max_retries": 3})
    notifier = OpenClawNotifier(settings, "+10000000000")

    with patch("mt5_trigger.notify.openclaw.subprocess.run") as run:
        run.return_value = MagicMock(returncode=1, stdout="", stderr="failed")
        assert notifier.send("positions summary") is False

    assert run.call_count == 1
