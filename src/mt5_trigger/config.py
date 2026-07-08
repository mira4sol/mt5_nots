from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
DEFAULT_ACCOUNTS_PATH = CONFIG_DIR / "accounts.yaml"

logger = logging.getLogger(__name__)


def _normalize_phone(number: str) -> str:
    number = strip_env_value(number)
    if not number:
        return number
    if "@" in number:
        number = number.split("@", 1)[0]
    number = number.strip()
    if number and not number.startswith("+"):
        return f"+{number}"
    return number


def _phone_digits(number: str) -> str:
    return re.sub(r"\D", "", _normalize_phone(number))


def whatsapp_admin_variants(admins: list[str]) -> list[str]:
    """Expand admin numbers for OpenClaw allowlists (E.164 + digits-only)."""
    seen: set[str] = set()
    out: list[str] = []
    for admin in admins:
        normalized = _normalize_phone(admin)
        digits = _phone_digits(admin)
        for variant in (normalized, f"+{digits}", digits):
            if variant and variant not in seen:
                seen.add(variant)
                out.append(variant)
    return out


class NearTriggerSettings(BaseModel):
    min_pips: float = 12
    spread_multiplier: float = 3
    rollover_blackout_minutes: int = 30
    daily_rollover_blackout_minutes: int = 5


class OpenClawSettings(BaseModel):
    max_retries: int = 3
    retry_base_seconds: float = 2


class CommandsSettings(BaseModel):
    enabled: bool = True
    api_token: str = ""
    whatsapp_admins: list[str] = Field(default_factory=list)
    cooldown_seconds: float = 30

    @field_validator("whatsapp_admins", mode="before")
    @classmethod
    def parse_whatsapp_admins(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [_normalize_phone(n) for n in v.split(",") if n.strip()]
        if isinstance(v, list):
            return [_normalize_phone(str(n)) for n in v if str(n).strip()]
        return v

    @property
    def whatsapp_admin_numbers(self) -> list[str]:
        """Alias kept for existing call sites."""
        return self.whatsapp_admins


class AppSettings(BaseModel):
    poll_interval_seconds: float = 2
    health_host: str = "0.0.0.0"
    health_port: int = 8080  # override via HEALTH_PORT in .env
    openclaw_bin: str = "openclaw"
    db_path: str = "data/mt5_trigger.db"
    near_trigger: NearTriggerSettings = Field(default_factory=NearTriggerSettings)
    openclaw: OpenClawSettings = Field(default_factory=OpenClawSettings)
    commands: CommandsSettings = Field(default_factory=CommandsSettings)

    @field_validator("health_port", mode="before")
    @classmethod
    def parse_health_port(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = strip_env_value(v)
            if not v:
                return 8080
            return int(v)
        return v

    @property
    def db_path_resolved(self) -> Path:
        path = Path(self.db_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path


Mt5Backend = Literal["auto", "native", "bridge", "mock"]
BridgeClient = Literal["auto", "mt5linux", "mac-bridge"]


class AccountConfig(BaseModel):
    name: str
    login: str
    password: str
    server: str
    enabled: bool = True
    whatsapp_target: str = ""
    mt5_backend: Mt5Backend = "auto"
    bridge_client: BridgeClient = "auto"
    bridge_host: str = "localhost"
    bridge_port: int = 18813
    terminal_path: str | None = None

    @field_validator("mt5_backend", "bridge_client", mode="before")
    @classmethod
    def blank_literal(cls, v: Any) -> Any:
        if v == "" or v is None:
            return "auto"
        return v

    @field_validator("login", "password", "server", "whatsapp_target", "bridge_host", mode="before")
    @classmethod
    def strip_strings(cls, v: Any) -> Any:
        if isinstance(v, str):
            return strip_env_value(v)
        return v

    @field_validator("terminal_path", mode="before")
    @classmethod
    def blank_terminal_path(cls, v: Any) -> str | None:
        if v == "" or v is None:
            return None
        if isinstance(v, str):
            v = strip_env_value(v)
        if not v:
            return None
        return v

    @field_validator("bridge_port", mode="before")
    @classmethod
    def parse_bridge_port(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = strip_env_value(v)
            if not v:
                return 18813
            return int(v)
        return v


class AppConfig(BaseModel):
    settings: AppSettings
    accounts: list[AccountConfig]


_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def strip_env_value(value: str) -> str:
    """Remove surrounding quotes/whitespace from .env values (Make/dotenv safe)."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value.strip()


def _interpolate_env(value: Any) -> Any:
    if isinstance(value, str):

        def repl(match: re.Match[str]) -> str:
            key = match.group(1)
            raw = os.environ.get(key, "")
            return strip_env_value(raw) if raw else ""

        result = _ENV_PATTERN.sub(repl, value)
        # Literal strings without ${} — leave as-is
        return result
    if isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env(v) for v in value]
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return _interpolate_env(data)


def load_config(
    settings_path: Path | None = None,
    accounts_path: Path | None = None,
    env_path: Path | None = None,
) -> AppConfig:
    env_file = env_path or PROJECT_ROOT / ".env"
    # override=True so .env file wins over Make-exported quoted values
    load_dotenv(env_file, override=True)

    settings_data = _load_yaml(settings_path or DEFAULT_SETTINGS_PATH)
    accounts_data = _load_yaml(accounts_path or DEFAULT_ACCOUNTS_PATH)

    settings = AppSettings.model_validate(settings_data)
    settings = apply_env_to_settings(settings)
    accounts = [
        AccountConfig.model_validate(a) for a in accounts_data.get("accounts", [])
    ]
    return AppConfig(settings=settings, accounts=accounts)


def resolve_command_api_token(config: AppConfig | None = None) -> str:
    """API token from settings.yaml + .env (same source as the running app)."""
    if config is None:
        config = load_config()
    return config.settings.commands.api_token.strip()


def apply_env_to_settings(settings: AppSettings) -> AppSettings:
    """Overlay HEALTH_* and command secrets from .env onto app settings."""
    updates: dict[str, Any] = {}
    port = strip_env_value(os.environ.get("HEALTH_PORT", ""))
    if port:
        updates["health_port"] = int(port)
    host = strip_env_value(os.environ.get("HEALTH_HOST", ""))
    if host:
        updates["health_host"] = host

    cmd_updates: dict[str, Any] = {}
    # api_token auth disabled temporarily — skip COMMAND_API_TOKEN from .env
    cooldown = strip_env_value(os.environ.get("COMMAND_COOLDOWN_SECONDS", ""))
    if cooldown:
        cmd_updates["cooldown_seconds"] = float(cooldown)
    if cmd_updates:
        updates["commands"] = settings.commands.model_copy(update=cmd_updates)

    if updates:
        return settings.model_copy(update=updates)
    return settings


def command_group_jids(accounts: list[AccountConfig]) -> list[str]:
    """Unique WhatsApp group JIDs configured on accounts."""
    seen: set[str] = set()
    groups: list[str] = []
    for account in accounts:
        target = account.whatsapp_target.strip()
        if not target.endswith("@g.us") or target in seen:
            continue
        seen.add(target)
        groups.append(target)
    return groups


def resolve_account_for_group(
    config: AppConfig,
    group_jid: str,
) -> AccountConfig | None:
    """Map inbound group JID to the investor account for that trading group."""
    matches = [
        a
        for a in enabled_accounts(config)
        if a.whatsapp_target.strip() == group_jid.strip()
    ]
    if not matches:
        return None
    if len(matches) > 1:
        logger.warning(
            "Multiple accounts share whatsapp_target %s; using %s",
            group_jid,
            matches[0].name,
        )
    return matches[0]


def resolve_command_account(
    config: AppConfig,
    *,
    account_name: str | None = None,
    group_jid: str | None = None,
) -> AccountConfig | None:
    accounts = enabled_accounts(config)
    if not accounts:
        return None
    if account_name:
        matches = [a for a in accounts if a.name == account_name]
        return matches[0] if matches else None
    if group_jid:
        return resolve_account_for_group(config, group_jid)
    if len(accounts) == 1:
        return accounts[0]
    return None


def apply_env_to_account(account: AccountConfig) -> AccountConfig:
    """Overlay MT5_* environment variables onto an account (same as test script)."""
    updates: dict[str, Any] = {}
    backend = strip_env_value(os.environ.get("MT5_BACKEND", ""))
    if backend:
        if backend in _BACKEND_ALIASES:
            mapped, client = _BACKEND_ALIASES[backend]
            updates["mt5_backend"] = mapped
            if not strip_env_value(os.environ.get("MT5_BRIDGE_CLIENT", "")):
                updates["bridge_client"] = client
        else:
            updates["mt5_backend"] = backend
    for env_key, field in (
        ("MT5_BRIDGE_HOST", "bridge_host"),
        ("MT5_BRIDGE_CLIENT", "bridge_client"),
        ("MT5_LOGIN", "login"),
        ("MT5_PASSWORD", "password"),
        ("MT5_SERVER", "server"),
        ("MT5_TERMINAL_PATH", "terminal_path"),
    ):
        val = strip_env_value(os.environ.get(env_key, ""))
        if val:
            updates[field] = val
    port = strip_env_value(os.environ.get("MT5_BRIDGE_PORT", ""))
    if port:
        updates["bridge_port"] = int(port)
    if updates:
        account = account.model_copy(update=updates)
    return normalize_account_config(account)


def enabled_accounts(config: AppConfig) -> list[AccountConfig]:
    return [apply_env_to_account(a) for a in config.accounts if a.enabled]


# Aliases users often put in MT5_BACKEND by mistake
_BACKEND_ALIASES: dict[str, tuple[str, str | None]] = {
    "mt5linux": ("bridge", "mt5linux"),
    "mac-bridge": ("bridge", "mac-bridge"),
    "mt5-mac-bridge": ("bridge", "mac-bridge"),
}


def normalize_account_config(account: AccountConfig) -> AccountConfig:
    """Map common mistakes like MT5_BACKEND=mt5linux → bridge + bridge_client=mt5linux."""
    alias = _BACKEND_ALIASES.get(account.mt5_backend)
    if not alias:
        return account
    backend, client = alias
    bridge_client = account.bridge_client
    if bridge_client == "auto" and client:
        bridge_client = client  # type: ignore[assignment]
    return account.model_copy(
        update={"mt5_backend": backend, "bridge_client": bridge_client}
    )
