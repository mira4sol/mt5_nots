from __future__ import annotations

import logging
import re
from pathlib import Path

from mt5_trigger.config import (
    DEFAULT_SETTINGS_PATH,
    _normalize_phone,
    phones_match,
)

logger = logging.getLogger(__name__)

ADMIN_PHONE_PATTERN = re.compile(
    r"^/(?:authorize|unauthorize)\s+(\+?\d[\d\s-]{8,})\s*$",
    re.IGNORECASE,
)
ADMIN_LIST_ITEM = re.compile(r"^(\s*-\s*)(['\"]?)(\+?\d[\d\s-]+)\2(?:\s*#.*)?$")
WHATSAPP_ADMINS_KEY = re.compile(r"^(\s*)whatsapp_admins:\s*(?:\[\])?\s*(?:#.*)?$")


def parse_admin_phone(text: str) -> str | None:
    """Extract E.164 phone from `/authorize +234...` or `/unauthorize +234...`."""
    match = ADMIN_PHONE_PATTERN.match(text.strip())
    if not match:
        return None
    phone = re.sub(r"[\s-]", "", match.group(1))
    normalized = _normalize_phone(phone)
    digits = re.sub(r"\D", "", normalized)
    if len(digits) < 10:
        return None
    return normalized


def _read_settings_lines(settings_path: Path) -> list[str]:
    if not settings_path.exists():
        raise FileNotFoundError(f"Config file not found: {settings_path}")
    return settings_path.read_text(encoding="utf-8").splitlines()


def _phone_from_list_line(line: str) -> str | None:
    match = ADMIN_LIST_ITEM.match(line.strip())
    if not match:
        return None
    return _normalize_phone(match.group(3))


def read_whatsapp_admin_lines(settings_path: Path | None = None) -> list[str]:
    """Return normalized admin numbers from settings.yaml."""
    path = settings_path or DEFAULT_SETTINGS_PATH
    lines = _read_settings_lines(path)
    admins: list[str] = []
    in_list = False
    list_indent = 0
    for line in lines:
        key_match = WHATSAPP_ADMINS_KEY.match(line)
        if key_match:
            in_list = True
            list_indent = len(key_match.group(1))
            continue
        if not in_list:
            continue
        if line.strip() == "" or line.lstrip().startswith("#"):
            continue
        current_indent = len(line) - len(line.lstrip())
        if current_indent <= list_indent:
            break
        phone = _phone_from_list_line(line)
        if phone:
            admins.append(phone)
    return admins


def _find_admin_list_bounds(lines: list[str]) -> tuple[int, int, int] | None:
    """Return (key_line_idx, first_item_idx, last_item_idx) for whatsapp_admins."""
    key_idx = -1
    list_indent = 0
    first_item = -1
    last_item = -1
    for idx, line in enumerate(lines):
        key_match = WHATSAPP_ADMINS_KEY.match(line)
        if key_match:
            key_idx = idx
            list_indent = len(key_match.group(1))
            continue
        if key_idx == -1:
            continue
        if line.strip() == "" or line.lstrip().startswith("#"):
            continue
        current_indent = len(line) - len(line.lstrip())
        if current_indent <= list_indent:
            break
        if ADMIN_LIST_ITEM.match(line.strip()):
            if first_item == -1:
                first_item = idx
            last_item = idx
    if key_idx == -1:
        return None
    return key_idx, first_item, last_item


def add_whatsapp_admin(
    phone: str,
    settings_path: Path | None = None,
) -> tuple[list[str], bool]:
    """Append admin to settings.yaml. Returns (admins, added)."""
    path = settings_path or DEFAULT_SETTINGS_PATH
    normalized = _normalize_phone(phone)
    lines = _read_settings_lines(path)
    bounds = _find_admin_list_bounds(lines)
    if bounds is None:
        raise RuntimeError("whatsapp_admins section not found in settings.yaml")

    _, first_item, last_item = bounds
    current = read_whatsapp_admin_lines(path)
    if any(phones_match(normalized, admin) for admin in current):
        return current, False

    new_line = f"    - '{normalized}'"
    insert_at = last_item + 1 if last_item >= 0 else bounds[0] + 1
    lines.insert(insert_at, new_line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return current + [normalized], True


def remove_whatsapp_admin(
    phone: str,
    settings_path: Path | None = None,
) -> tuple[list[str], bool]:
    """Remove admin from settings.yaml. Returns (admins, removed)."""
    path = settings_path or DEFAULT_SETTINGS_PATH
    normalized = _normalize_phone(phone)
    lines = _read_settings_lines(path)
    bounds = _find_admin_list_bounds(lines)
    if bounds is None:
        raise RuntimeError("whatsapp_admins section not found in settings.yaml")

    _, first_item, last_item = bounds
    if first_item == -1:
        return [], False

    remove_idx = -1
    for idx in range(first_item, last_item + 1):
        line_phone = _phone_from_list_line(lines[idx])
        if line_phone and phones_match(normalized, line_phone):
            remove_idx = idx
            break

    if remove_idx == -1:
        return read_whatsapp_admin_lines(path), False

    del lines[remove_idx]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    remaining = read_whatsapp_admin_lines(path)
    return remaining, True


def sync_openclaw_allowlist() -> str:
    """Patch OpenClaw allowlists on disk without restarting the gateway."""
    from mt5_trigger.openclaw_sync import patch_openclaw_config

    ok, message = patch_openclaw_config(restart_gateway=False)
    if not ok:
        logger.error("OpenClaw allowlist sync failed: %s", message)
        return message
    logger.info("OpenClaw allowlist synced: %s", message)
    return message
