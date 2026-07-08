from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from mt5_trigger.commands import format as cmd_format
from mt5_trigger.config import (
    AccountConfig,
    AppConfig,
    _normalize_phone,
    _phone_digits,
    command_group_jids,
    enabled_accounts,
    resolve_command_account,
)
from mt5_trigger.mt5.client import (
    MT5Client,
    distance_to_trigger,
    is_buy_order,
)
from mt5_trigger.notify.openclaw import OpenClawNotifier

logger = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")

COMMAND_ALIASES: dict[str, str] = {
    "positions": "positions",
    "orders": "orders",
    "nt": "nt",
    "close_price": "nt",
    "close-price": "nt",
    "tpd": "tpd",
    "sld": "sld",
    "cts": "cts",
    "help": "help",
    "mt5help": "help",
}

COMMAND_PATTERN = re.compile(r"^/([a-z_-]+)\b", re.IGNORECASE)


@dataclass
class CommandResult:
    command: str
    account: str
    message: str
    sent: bool = False
    error: str | None = None


class CommandService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._cooldowns: dict[str, float] = {}
        self._clients: dict[str, MT5Client] = {}

    def list_commands(self) -> list[str]:
        return ["/" + name for name in COMMAND_ALIASES.values()]

    def list_command_groups(self) -> list[str]:
        return command_group_jids(enabled_accounts(self.config))

    def parse_command(self, text: str) -> str | None:
        text = text.strip()
        if not text.startswith("/"):
            return None
        match = COMMAND_PATTERN.match(text)
        if not match:
            return None
        raw = match.group(1).lower().replace("-", "_")
        return COMMAND_ALIASES.get(raw)

    def is_allowed_sender(self, sender: str) -> bool:
        admins = self.config.settings.commands.whatsapp_admins
        if not admins:
            return True
        sender_digits = _phone_digits(sender)
        for admin in admins:
            if sender_digits and sender_digits == _phone_digits(admin):
                return True
            normalized = _normalize_phone(sender)
            if normalized in admins or sender in admins:
                return True
        return False

    def is_allowed_group(self, group_jid: str) -> bool:
        return resolve_command_account(self.config, group_jid=group_jid) is not None

    def in_cooldown(self, sender: str, group_jid: str) -> bool:
        key = f"{_normalize_phone(sender) or sender}:{group_jid}"
        last = self._cooldowns.get(key, 0.0)
        return (time.time() - last) < self.config.settings.commands.cooldown_seconds

    def mark_cooldown(self, sender: str, group_jid: str) -> None:
        key = f"{_normalize_phone(sender) or sender}:{group_jid}"
        self._cooldowns[key] = time.time()

    def _send_reply(
        self,
        *,
        message: str,
        account: AccountConfig,
        target: str,
    ) -> bool:
        notifier = OpenClawNotifier(self.config.settings, target)
        return notifier.send(message, target=target)

    def handle_inbound(
        self,
        *,
        text: str,
        sender: str,
        group_jid: str,
        account_name: str | None = None,
    ) -> CommandResult | None:
        if not self.config.settings.commands.enabled:
            return None
        if not self.is_allowed_group(group_jid):
            logger.info("Ignoring message from unknown group %s", group_jid)
            return None
        command = self.parse_command(text)
        if command is None:
            return None
        logger.info(
            "Inbound WhatsApp command %s from %s in %s",
            command,
            sender,
            group_jid,
        )
        if not self.is_allowed_sender(sender):
            logger.warning("Ignoring command from non-admin sender %s", sender)
            return None
        if self.in_cooldown(sender, group_jid):
            logger.info("Cooldown active for sender %s in %s", sender, group_jid)
            account = resolve_command_account(
                self.config,
                account_name=account_name,
                group_jid=group_jid,
            )
            if account is None:
                return None
            self._send_reply(
                message="Please wait before sending another command.",
                account=account,
                target=group_jid,
            )
            return CommandResult(
                command=command,
                account=account.name,
                message="Please wait before sending another command.",
                sent=True,
            )

        account = resolve_command_account(
            self.config,
            account_name=account_name,
            group_jid=group_jid,
        )
        if account is None:
            logger.warning("No account mapped to group %s", group_jid)
            return None

        result = self.run_command(
            command,
            account_name=account.name,
            send=True,
            target=group_jid,
        )
        if result.error:
            self._send_reply(
                message=f"MT5 error: {result.error}",
                account=account,
                target=group_jid,
            )
            result.sent = True
        elif result.error is None:
            self.mark_cooldown(sender, group_jid)
        return result

    def run_command(
        self,
        command: str,
        *,
        account_name: str | None = None,
        group_jid: str | None = None,
        send: bool = False,
        target: str | None = None,
    ) -> CommandResult:
        account = resolve_command_account(
            self.config,
            account_name=account_name,
            group_jid=group_jid,
        )
        if account is None:
            accounts = enabled_accounts(self.config)
            if len(accounts) > 1:
                error = "Multiple accounts configured; specify ?account=<name>"
            else:
                error = "No enabled account found"
            return CommandResult(
                command=command,
                account=account_name or "",
                message="",
                error=error,
            )

        try:
            message = self._execute(command, account)
        except Exception as exc:
            logger.exception("Command %s failed for %s", command, account.name)
            return CommandResult(
                command=command,
                account=account.name,
                message="",
                error=str(exc),
            )

        sent = False
        if send:
            dest = target or account.whatsapp_target
            if not dest:
                return CommandResult(
                    command=command,
                    account=account.name,
                    message=message,
                    error="No whatsapp_target configured for account",
                )
            sent = self._send_reply(message=message, account=account, target=dest)
            if not sent and message:
                return CommandResult(
                    command=command,
                    account=account.name,
                    message=message,
                    error="Failed to send WhatsApp reply via OpenClaw",
                )

        return CommandResult(
            command=command,
            account=account.name,
            message=message,
            sent=sent,
        )

    def _execute(self, command: str, account: AccountConfig) -> str:
        if command == "help":
            return cmd_format.help_message()
        client = self._get_client(account)
        if command == "positions":
            return cmd_format.positions_message(client.get_positions())
        if command == "orders":
            return cmd_format.orders_message(client.get_pending_orders())
        if command == "nt":
            return self._nearest_trigger(client)
        if command == "tpd":
            return self._tpd(client)
        if command == "sld":
            return self._sld(client)
        if command == "cts":
            return cmd_format.cts_message(client.get_positions())
        raise ValueError(f"Unknown command: {command}")

    def _nearest_trigger(self, client: MT5Client) -> str:
        orders = client.get_pending_orders()
        if not orders:
            return cmd_format.close_price_message(None, None, None)

        best_order = None
        best_distance = None
        best_price = None
        for order in orders:
            tick = client.get_tick(order.symbol)
            if tick is None:
                continue
            distance = distance_to_trigger(order, tick)
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_order = order
                best_price = tick.ask if is_buy_order(order.order_type) else tick.bid

        return cmd_format.close_price_message(best_order, best_price, best_distance)

    def _tpd(self, client: MT5Client) -> str:
        now_et = datetime.now(NY)
        day_start = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        deals = client.get_daily_closed_deals(day_start, day_end)
        if not deals:
            return cmd_format.tpd_message(0.0, 0, 0, 0)

        profits = [d.net_profit for d in deals]
        wins = sum(1 for p in profits if p > 0)
        losses = sum(1 for p in profits if p <= 0)
        total = sum(profits)
        return cmd_format.tpd_message(total, wins, losses, len(deals))

    def _sld(self, client: MT5Client) -> str:
        positions = client.get_positions()
        rows: list[tuple] = []
        for pos in positions:
            tick = client.get_tick(pos.symbol)
            if tick is None:
                rows.append((pos, None, None))
                continue
            current = tick.bid if pos.position_type == 0 else tick.ask
            if pos.sl <= 0:
                rows.append((pos, current, None))
                continue
            distance = abs(current - pos.sl)
            rows.append((pos, current, distance))
        return cmd_format.sld_message(rows)

    def _get_client(self, account: AccountConfig) -> MT5Client:
        if account.name not in self._clients:
            client = MT5Client(account)
            if not client.connect():
                raise RuntimeError(f"MT5 connect failed for {account.name}")
            self._clients[account.name] = client
        return self._clients[account.name]
