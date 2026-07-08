from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel

from mt5_trigger.api.auth import verify_api_token
from mt5_trigger.commands.service import CommandService
from mt5_trigger.config import AppConfig, enabled_accounts, resolve_command_account
from mt5_trigger.market_hours import MarketHoursConfig, get_market_status
from mt5_trigger.storage.db import init_db
from mt5_trigger.storage.repository import EventRepository
from mt5_trigger.runtime import get_uptime

COMMAND_NAMES = frozenset({"help", "positions", "orders", "nt", "close_price", "tpd", "sld", "cts"})


def _normalize_command_name(command_name: str) -> str:
    normalized = command_name.lower().replace("-", "_")
    if normalized == "close_price":
        return "nt"
    return normalized


class WhatsAppInbound(BaseModel):
    text: str
    sender: str
    group_jid: str
    account: str | None = None
    message_id: str | None = None


class CommandRunRequest(BaseModel):
    command: str
    account: str | None = None
    send: bool = True
    target: str | None = None


def create_app(config: AppConfig) -> FastAPI:
    app = FastAPI(title="MT5 Trigger Monitor", version="0.1.0")
    db_path = config.settings.db_path_resolved
    conn = init_db(db_path)
    repo = EventRepository(conn)
    market_cfg = MarketHoursConfig(
        rollover_blackout_minutes=config.settings.near_trigger.rollover_blackout_minutes,
        daily_rollover_blackout_minutes=config.settings.near_trigger.daily_rollover_blackout_minutes,
    )
    command_service = CommandService(config)

    def _auth() -> None:
        verify_api_token(config.settings)

    def _command_response(result) -> dict[str, Any]:
        if result.error:
            raise HTTPException(status_code=400, detail=result.error)
        return {
            "command": result.command,
            "account": result.account,
            "message": result.message,
            "sent": result.sent,
        }

    @app.get("/health")
    def health():
        market = get_market_status(market_cfg)
        statuses = repo.get_all_watcher_status()
        account_map = {s["account"]: s for s in statuses}
        accounts_info = []
        for account in enabled_accounts(config):
            s = account_map.get(account.name, {})
            accounts_info.append(
                {
                    "name": account.name,
                    "connected": bool(s.get("connected")),
                    "last_poll_at": s.get("last_poll_at"),
                    "last_error": s.get("last_error"),
                }
            )
        all_ok = repo.ping()
        return {
            "status": "ok" if all_ok else "degraded",
            "uptime_seconds": round(get_uptime()),
            "market_open": market.is_open and not market.in_blackout,
            "market_reason": market.reason,
            "accounts": accounts_info,
            "db_ok": all_ok,
            "commands_enabled": config.settings.commands.enabled,
            "command_groups": command_service.list_command_groups(),
        }

    @app.get("/api/commands")
    def list_commands(_: None = Depends(_auth)):
        accounts = enabled_accounts(config)
        return {
            "commands": command_service.list_commands(),
            "command_groups": command_service.list_command_groups(),
            "accounts_by_group": {
                a.whatsapp_target: a.name
                for a in accounts
                if a.whatsapp_target.endswith("@g.us")
            },
        }

    @app.get("/api/commands/{command_name}")
    def get_command(
        command_name: str,
        account: str | None = Query(default=None),
        send: bool = Query(default=True),
        target: str | None = Query(default=None),
        _: None = Depends(_auth),
    ):
        raw = command_name.lower().replace("-", "_")
        if raw not in COMMAND_NAMES:
            raise HTTPException(status_code=404, detail=f"Unknown command: {command_name}")
        result = command_service.run_command(
            _normalize_command_name(command_name),
            account_name=account,
            send=send,
            target=target,
        )
        return _command_response(result)

    @app.post("/api/commands/{command_name}")
    def post_command(
        command_name: str,
        account: str | None = Query(default=None),
        send: bool = Query(default=True),
        target: str | None = Query(default=None),
        _: None = Depends(_auth),
    ):
        return get_command(
            command_name=command_name,
            account=account,
            send=send,
            target=target,
            _=None,
        )

    @app.post("/api/commands/run")
    def run_command(body: CommandRunRequest, _: None = Depends(_auth)):
        raw = body.command.strip().lstrip("/").lower().replace("-", "_")
        if raw not in COMMAND_NAMES:
            raise HTTPException(status_code=400, detail=f"Unknown command: {body.command}")
        result = command_service.run_command(
            _normalize_command_name(raw),
            account_name=body.account,
            send=body.send,
            target=body.target,
        )
        return _command_response(result)

    @app.post("/webhooks/whatsapp/inbound")
    def whatsapp_inbound(body: WhatsAppInbound, _: None = Depends(_auth)):
        result = command_service.handle_inbound(
            text=body.text,
            sender=body.sender,
            group_jid=body.group_jid,
            account_name=body.account,
        )
        if result is None:
            return {"handled": False}
        if result.error:
            return {
                "handled": True,
                "error": result.error,
                "command": result.command,
                "account": result.account,
            }
        return {
            "handled": True,
            "command": result.command,
            "account": result.account,
            "message": result.message,
            "sent": result.sent,
        }

    return app
