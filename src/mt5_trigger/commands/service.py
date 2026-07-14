from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from mt5_trigger.commands import format as cmd_format
from mt5_trigger.commands.admins import (
    add_whatsapp_admin,
    parse_admin_phone,
    remove_whatsapp_admin,
    sync_openclaw_allowlist,
)
from mt5_trigger.config import (
    AccountConfig,
    AppConfig,
    _normalize_phone,
    command_group_jids,
    enabled_accounts,
    phone_digit_variants,
    phones_match,
    resolve_command_account,
)
from mt5_trigger.mt5.client import (
    MT5Client,
    distance_to_trigger,
    is_buy_order,
)
from mt5_trigger.notify.openclaw import OpenClawNotifier
from mt5_trigger.storage.db import init_db
from mt5_trigger.storage.repository import EventRepository

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
    "chart": "chart",
    "guide": "guide",
    "help": "guide",
    "mt5help": "guide",
    "authorize": "authorize",
    "unauthorize": "unauthorize",
}

ADMIN_COMMANDS = frozenset({"authorize", "unauthorize"})

COMMAND_PATTERN = re.compile(r"^/([a-z0-9_-]+)\b", re.IGNORECASE)


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
        db_path = config.settings.db_path_resolved
        self._conn = init_db(db_path)
        self._repo = EventRepository(self._conn)

    @staticmethod
    def _inbound_dedupe_key(
        *,
        message_id: str | None,
        reply_to: str | None,
        command: str,
        target: str,
        sender: str | None = None,
        group_jid: str | None = None,
    ) -> str | None:
        delivery_id = (message_id or reply_to or "").strip()
        if delivery_id:
            return f"delivery:{delivery_id}:{command}:{target}"
        if sender and group_jid:
            return f"sender:{sender}:{group_jid}:{command}"
        return None

    def _claim_delivery(
        self,
        *,
        message_id: str | None = None,
        reply_to: str | None = None,
        command: str,
        target: str,
        sender: str | None = None,
        group_jid: str | None = None,
    ) -> bool:
        dedupe_key = self._inbound_dedupe_key(
            message_id=message_id,
            reply_to=reply_to,
            command=command,
            target=target,
            sender=sender,
            group_jid=group_jid,
        )
        if dedupe_key is None:
            return True
        return self._repo.claim_inbound_command(dedupe_key)

    def list_commands(self) -> list[str]:
        seen: set[str] = set()
        names: list[str] = []
        for name in COMMAND_ALIASES.values():
            if name in seen:
                continue
            seen.add(name)
            names.append("/" + name)
        return names

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
        for admin in admins:
            if phones_match(sender, admin):
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
        reply_to: str | None = None,
        command: str | None = None,
    ) -> bool:
        notifier = OpenClawNotifier(self.config.settings, target)
        sent = notifier.send(message, target=target, reply_to=reply_to)
        if not sent:
            logger.error(
                "Command reply not delivered: command=%s account=%s target=%s "
                "reply_to=%s message_len=%d",
                command or "-",
                account.name,
                target,
                reply_to or "-",
                len(message),
            )
        return sent

    def handle_inbound(
        self,
        *,
        text: str,
        sender: str,
        group_jid: str,
        account_name: str | None = None,
        message_id: str | None = None,
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
            logger.warning(
                "Ignoring command from non-admin sender %s (digits=%s)",
                sender,
                ",".join(sorted(phone_digit_variants(sender))) or "-",
            )
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
            cooldown_sent = self._send_reply(
                message="Please wait before sending another command.",
                account=account,
                target=group_jid,
                reply_to=message_id,
                command=command,
            )
            return CommandResult(
                command=command,
                account=account.name,
                message="Please wait before sending another command.",
                sent=cooldown_sent,
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
            reply_to=message_id,
            command_text=text,
            sender=sender,
        )
        if result.error:
            logger.error(
                "Command %s failed for %s in %s: %s",
                command,
                account.name,
                group_jid,
                result.error,
            )
            prefix = "Error" if command in ADMIN_COMMANDS else "MT5 error"
            self._send_reply(
                message=f"{prefix}: {result.error}",
                account=account,
                target=group_jid,
                reply_to=message_id,
                command=command,
            )
        elif not result.sent:
            logger.error(
                "Command %s completed but WhatsApp delivery failed for %s in %s",
                command,
                account.name,
                group_jid,
            )
        else:
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
        reply_to: str | None = None,
        message_id: str | None = None,
        command_text: str | None = None,
        sender: str | None = None,
    ) -> CommandResult:
        if command in ADMIN_COMMANDS:
            return self._run_admin_command(
                command,
                command_text=command_text or "",
                sender=sender or "",
                account_name=account_name,
                group_jid=group_jid,
                send=send,
                target=target,
                reply_to=reply_to,
                message_id=message_id,
            )

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
            if command == "chart":
                return self._run_chart_command(
                    account,
                    send=send,
                    target=target or account.whatsapp_target,
                    reply_to=reply_to,
                )
            message = self._execute(command, account)
        except ImportError as exc:
            return CommandResult(
                command=command,
                account=account.name,
                message="",
                error=str(exc),
            )
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
            if not self._claim_delivery(
                message_id=message_id,
                reply_to=reply_to,
                command=command,
                target=dest,
            ):
                logger.info(
                    "Skipping duplicate command delivery: command=%s target=%s "
                    "reply_to=%s message_id=%s",
                    command,
                    dest,
                    reply_to or "-",
                    message_id or "-",
                )
                return CommandResult(
                    command=command,
                    account=account.name,
                    message=message,
                    sent=True,
                )
            sent = self._send_reply(
                message=message,
                account=account,
                target=dest,
                reply_to=reply_to,
                command=command,
            )

        return CommandResult(
            command=command,
            account=account.name,
            message=message,
            sent=sent,
        )

    def _execute(self, command: str, account: AccountConfig) -> str:
        if command in {"guide", "help"}:
            return cmd_format.guide_message()
        client = self._get_client(account)
        if command == "positions":
            return cmd_format.positions_message(client.get_positions())
        if command == "orders":
            orders = client.get_pending_orders()
            symbol = cmd_format.primary_symbol([o.symbol for o in orders])
            tick = client.get_tick(symbol) if symbol else None
            return cmd_format.orders_message(orders, symbol=symbol, tick=tick)
        if command == "nt":
            return self._nearest_trigger(client)
        if command == "tpd":
            return self._tpd(client)
        if command == "sld":
            return self._sld(client)
        if command == "cts":
            positions = client.get_positions()
            symbols = {p.symbol for p in positions}
            ticks = {s: client.get_tick(s) for s in symbols}
            return cmd_format.cts_message(positions, ticks=ticks)
        raise ValueError(f"Unknown command: {command}")

    def _run_admin_command(
        self,
        command: str,
        *,
        command_text: str,
        sender: str,
        account_name: str | None,
        group_jid: str | None,
        send: bool,
        target: str | None,
        reply_to: str | None,
        message_id: str | None,
    ) -> CommandResult:
        account = resolve_command_account(
            self.config,
            account_name=account_name,
            group_jid=group_jid,
        )
        if account is None:
            return CommandResult(
                command=command,
                account=account_name or "",
                message="",
                error="No account mapped to this group",
            )

        phone = parse_admin_phone(command_text)
        if phone is None:
            usage = f"Usage: /{command} +234XXXXXXXXXX"
            return CommandResult(
                command=command,
                account=account.name,
                message=usage,
                error=usage,
            )

        try:
            if command == "authorize":
                admins, added = add_whatsapp_admin(phone)
                if not added:
                    message = f"{phone} is already authorized."
                else:
                    sync_note = sync_openclaw_allowlist()
                    message = f"Authorized {phone}. {sync_note}"
            else:
                current = self.config.settings.commands.whatsapp_admins
                if not any(phones_match(phone, admin) for admin in current):
                    message = f"{phone} is not in the admin list."
                    admins = current
                else:
                    remaining = [
                        admin for admin in current if not phones_match(phone, admin)
                    ]
                    if not remaining:
                        error = "Cannot remove the last admin."
                        return CommandResult(
                            command=command,
                            account=account.name,
                            message=error,
                            error=error,
                        )
                    _, removed = remove_whatsapp_admin(phone)
                    admins = remaining
                    sync_note = sync_openclaw_allowlist()
                    message = f"Unauthorized {phone}. {sync_note}"
            self.config.settings.commands.whatsapp_admins = admins
        except Exception as exc:
            logger.exception("Admin command %s failed", command)
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
            if self._claim_delivery(
                message_id=message_id,
                reply_to=reply_to,
                command=command,
                target=dest,
            ):
                sent = self._send_reply(
                    message=message,
                    account=account,
                    target=dest,
                    reply_to=reply_to,
                    command=command,
                )
            else:
                sent = True

        return CommandResult(
            command=command,
            account=account.name,
            message=message,
            sent=sent,
        )

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

    def _run_chart_command(
        self,
        account: AccountConfig,
        *,
        send: bool,
        target: str | None,
        reply_to: str | None = None,
    ) -> CommandResult:
        if not send:
            return CommandResult(
                command="chart",
                account=account.name,
                message="Live XAUUSD M5 chart (preview only; send=true delivers image).",
                sent=False,
            )

        dest = target or account.whatsapp_target
        if not dest:
            return CommandResult(
                command="chart",
                account=account.name,
                message="",
                error="No whatsapp_target configured for account",
            )

        client = self._get_client(account)
        charts_dir = self.config.settings.db_path_resolved.parent / "charts"
        from mt5_trigger.charts.sender import send_live_chart

        try:
            result = send_live_chart(
                client=client,
                settings=self.config.settings,
                charts_dir=charts_dir,
                whatsapp_target=dest,
                send=True,
                reply_to=reply_to,
            )
        except RuntimeError as exc:
            logger.error(
                "Chart command delivery failed for %s (target=%s reply_to=%s): %s",
                account.name,
                dest,
                reply_to or "-",
                exc,
            )
            return CommandResult(
                command="chart",
                account=account.name,
                message="",
                sent=False,
            )
        if not result.sent:
            logger.error(
                "Chart command delivery failed for %s (target=%s reply_to=%s)",
                account.name,
                dest,
                reply_to or "-",
            )
        return CommandResult(
            command="chart",
            account=account.name,
            message=result.caption,
            sent=result.sent,
        )

    def _get_client(self, account: AccountConfig) -> MT5Client:
        if account.name not in self._clients:
            client = MT5Client(account)
            if not client.connect():
                raise RuntimeError(f"MT5 connect failed for {account.name}")
            self._clients[account.name] = client
        return self._clients[account.name]
