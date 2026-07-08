from __future__ import annotations

from fastapi import Header, HTTPException

from mt5_trigger.config import AppSettings


def verify_api_token(
    settings: AppSettings,
    x_api_token: str | None = Header(default=None, alias="X-API-Token"),
    authorization: str | None = Header(default=None),
) -> None:
    expected = settings.commands.api_token
    if not expected:
        return

    token = x_api_token
    if not token and authorization:
        prefix = "Bearer "
        if authorization.startswith(prefix):
            token = authorization.removeprefix(prefix).strip()

    if token != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API token")
