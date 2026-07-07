from __future__ import annotations

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


class NearTriggerSettings(BaseModel):
    min_pips: float = 12
    spread_multiplier: float = 3
    rollover_blackout_minutes: int = 30
    daily_rollover_blackout_minutes: int = 5


class OpenClawSettings(BaseModel):
    max_retries: int = 3
    retry_base_seconds: float = 2


class AppSettings(BaseModel):
    poll_interval_seconds: float = 2
    health_host: str = "0.0.0.0"
    health_port: int = 8080
    openclaw_bin: str = "openclaw"
    db_path: str = "data/mt5_trigger.db"
    near_trigger: NearTriggerSettings = Field(default_factory=NearTriggerSettings)
    openclaw: OpenClawSettings = Field(default_factory=OpenClawSettings)

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

    @field_validator("terminal_path", mode="before")
    @classmethod
    def blank_terminal_path(cls, v: Any) -> str | None:
        if v == "" or v is None:
            return None
        return v


class AppConfig(BaseModel):
    settings: AppSettings
    accounts: list[AccountConfig]


_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _interpolate_env(value: Any) -> Any:
    if isinstance(value, str):

        def repl(match: re.Match[str]) -> str:
            key = match.group(1)
            return os.environ.get(key, "")

        return _ENV_PATTERN.sub(repl, value)
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
    load_dotenv(env_file, override=False)

    settings_data = _load_yaml(settings_path or DEFAULT_SETTINGS_PATH)
    accounts_data = _load_yaml(accounts_path or DEFAULT_ACCOUNTS_PATH)

    settings = AppSettings.model_validate(settings_data)
    accounts = [
        AccountConfig.model_validate(a) for a in accounts_data.get("accounts", [])
    ]
    return AppConfig(settings=settings, accounts=accounts)


def enabled_accounts(config: AppConfig) -> list[AccountConfig]:
    return [normalize_account_config(a) for a in config.accounts if a.enabled]


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
