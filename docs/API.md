# MT5 Trigger HTTP API

Base URL (deployed server):

**http://204.168.148.205:8080/**

All command endpoints support an optional `send=true` query parameter to deliver the response to WhatsApp via OpenClaw.

## Authentication

API token auth is **disabled** for now — `/api/commands` and `/webhooks/whatsapp/inbound` accept requests without a token.

<!--
When re-enabling, set in config/settings.yaml:
  api_token: "${COMMAND_API_TOKEN}"
and add COMMAND_API_TOKEN to .env, then restart the app.
-->

## WhatsApp commands

Commands are scoped **per WhatsApp group**. Each account's `whatsapp_target` in `config/accounts.yaml` is the group JID for that investor pool — `/positions` in Group A only returns Account A data. Only senders in `commands.whatsapp_admins` can trigger commands (when configured).

| Command | Description |
|---------|-------------|
| `/help` | List all commands |
| `/positions` | Open positions |
| `/close_price` | Nearest pending order trigger price and distance |
| `/tpd` | Today's closed trade profit/loss (NY day) |
| `/sld` | Stop-loss distance on open trades |
| `/cts` | Current trade status with floating P/L |

## Endpoints

### Health

```http
GET /health
```

Example:

```bash
curl http://204.168.148.205:8080/health
```

Response:

```json
{
  "status": "ok",
  "uptime_seconds": 3600,
  "market_open": true,
  "market_reason": "open",
  "accounts": [
    {
      "name": "valetax_main",
      "connected": true,
      "last_poll_at": "2026-07-07T20:00:00+00:00",
      "last_error": null
    }
  ],
  "db_ok": true,
  "commands_enabled": true,
  "command_groups": ["120363428584387160@g.us"]
}
```

---

### List commands

```http
GET /api/commands
```

```bash
curl -H "X-API-Token: YOUR_TOKEN" \
  http://204.168.148.205:8080/api/commands
```

---

### Run a command (GET)

```http
GET /api/commands/{command}?account={name}&send={true|false}&target={jid}
```

Commands: `help`, `positions`, `close_price`, `tpd`, `sld`, `cts`

Examples:

```bash
# Preview positions (no WhatsApp send)
curl -H "X-API-Token: YOUR_TOKEN" \
  "http://204.168.148.205:8080/api/commands/positions"

# Run /positions and send result to that account's group (requires ?account= with multiple accounts)
curl -H "X-API-Token: YOUR_TOKEN" \
  "http://204.168.148.205:8080/api/commands/positions?account=valetax_main&send=true"

# Today's P/L for a specific account
curl -H "X-API-Token: YOUR_TOKEN" \
  "http://204.168.148.205:8080/api/commands/tpd?account=valetax_main&send=true"

# Nearest pending trigger
curl -H "X-API-Token: YOUR_TOKEN" \
  "http://204.168.148.205:8080/api/commands/close_price?send=true"

# Stop-loss distances
curl -H "X-API-Token: YOUR_TOKEN" \
  "http://204.168.148.205:8080/api/commands/sld?send=true"

# Current trade status
curl -H "X-API-Token: YOUR_TOKEN" \
  "http://204.168.148.205:8080/api/commands/cts?send=true"

# Help text
curl -H "X-API-Token: YOUR_TOKEN" \
  "http://204.168.148.205:8080/api/commands/help?send=true"
```

Response:

```json
{
  "command": "positions",
  "account": "valetax_main",
  "message": "Open positions (1):\n#12345 EURUSD BUY vol=0.1 open=1.08500 P/L=$12.50",
  "sent": true
}
```

---

### Run a command (POST)

```http
POST /api/commands/{command}?account={name}&send={true|false}&target={jid}
```

Same behavior as GET. Useful for automation tools that prefer POST.

```bash
curl -X POST -H "X-API-Token: YOUR_TOKEN" \
  "http://204.168.148.205:8080/api/commands/positions?send=true"
```

---

### Run a command (JSON body)

```http
POST /api/commands/run
Content-Type: application/json
```

```bash
curl -X POST -H "X-API-Token: YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command":"/positions","send":true,"account":"valetax_main"}' \
  http://204.168.148.205:8080/api/commands/run
```

Body fields:

| Field | Type | Description |
|-------|------|-------------|
| `command` | string | Command name with or without `/` |
| `account` | string | Optional account from `accounts.yaml` |
| `send` | boolean | Send response to WhatsApp (default `false`) |
| `target` | string | Optional WhatsApp JID/phone override |

---

### WhatsApp inbound webhook

OpenClaw POSTs group messages here. Only groups matching an account's `whatsapp_target` are processed. Non-commands and non-admin senders are ignored silently.

```http
POST /webhooks/whatsapp/inbound
Content-Type: application/json
```

```bash
curl -X POST -H "X-API-Token: YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "/positions",
    "sender": "+15551234567",
    "group_jid": "120363428584387160@g.us"
  }' \
  http://204.168.148.205:8080/webhooks/whatsapp/inbound
```

Body fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | string | yes | Message body |
| `sender` | string | yes | Sender E.164 |
| `group_jid` | string | yes | WhatsApp group JID |
| `account` | string | no | Account override |
| `message_id` | string | no | Optional dedupe id |

Handled command response:

```json
{
  "handled": true,
  "command": "positions",
  "account": "valetax_main",
  "message": "Open positions (0):\n...",
  "sent": true
}
```

Ignored (not a command, wrong group, or non-admin):

```json
{
  "handled": false
}
```

---

## WhatsApp group commands (automatic)

After install, group slash commands work end-to-end:

```text
Admin sends /positions in WhatsApp group
        ↓
OpenClaw gateway (message:received hook)
        ↓
POST /webhooks/whatsapp/inbound
        ↓
mt5_trigger runs command + replies to group
```

### One-time setup on the server

```bash
# From the mt5_trigger repo (reads .env for group JID, token, webhook URL)
make install-openclaw-hook

# Restart OpenClaw so the hook loads
openclaw gateway
```

This installs `openclaw-hooks/mt5-whatsapp-commands` into `~/.openclaw/hooks/`,
enables it in OpenClaw config, and forwards only:

- WhatsApp channel messages
- From any account `whatsapp_target` group JID in `config/accounts.yaml`
- That start with `/`

`make deploy` runs the hook install automatically.

Verify:

```bash
openclaw hooks list | grep mt5-whatsapp-commands
openclaw hooks info mt5-whatsapp-commands
```

Then in the group (as an admin in `commands.whatsapp_admins`):

```text
/help
/positions
```

---

## Wiring OpenClaw to the webhook (manual / advanced)

The hook above replaces manual wiring. For debugging you can still POST directly:

```bash
.venv/bin/python scripts/whatsapp_inbound_hook.py \
  --text "/positions" \
  --sender "+15551234567" \
  --group-jid "120363428584387160@g.us"
```

Configure OpenClaw WhatsApp access (in `~/.openclaw/openclaw.json`):

```json5
{
  channels: {
    whatsapp: {
      groupPolicy: "allowlist",
      groupAllowFrom: ["+15551234567"],
      groups: {
        "120363428584387160@g.us": {
          requireMention: false,
        },
      },
    },
  },
}
```

## Configuration

### `config/settings.yaml` (global commands)

```yaml
commands:
  enabled: true
  whatsapp_admins:
    - "+15551234567"
  cooldown_seconds: 30
```

### `config/accounts.yaml` (per investor group)

```yaml
accounts:
  - name: valetax_main
    whatsapp_target: "120363428584387160@g.us"   # Group A → only this account's data
  - name: second_account
    whatsapp_target: "120363999999999999@g.us"   # Group B → separate investor pool
```

**Routing rule:** inbound `group_jid` must match exactly one account's `whatsapp_target`.

### `.env` (optional deployment overrides)

| Variable | Description |
|----------|-------------|
| `MT5_TRIGGER_WEBHOOK_URL` | Optional OpenClaw hook → mt5_trigger webhook override |
| `HEALTH_HOST` / `HEALTH_PORT` | HTTP server bind (optional) |

## Quick reference

| Action | URL |
|--------|-----|
| Health | `GET http://204.168.148.205:8080/health` |
| List commands | `GET http://204.168.148.205:8080/api/commands` |
| Positions | `GET http://204.168.148.205:8080/api/commands/positions?send=true` |
| Close price | `GET http://204.168.148.205:8080/api/commands/close_price?send=true` |
| Today P/L | `GET http://204.168.148.205:8080/api/commands/tpd?send=true` |
| SL distance | `GET http://204.168.148.205:8080/api/commands/sld?send=true` |
| Trade status | `GET http://204.168.148.205:8080/api/commands/cts?send=true` |
| Help | `GET http://204.168.148.205:8080/api/commands/help?send=true` |
| WhatsApp inbound | `POST http://204.168.148.205:8080/webhooks/whatsapp/inbound` |
