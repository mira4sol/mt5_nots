# MT5 Trigger HTTP API

Base URL (deployed server):

**http://204.168.148.205:8080/**

All command endpoints **send to WhatsApp by default** (`send=true`). Pass `send=false` to return JSON only without delivering to the group.

The OpenClaw plugin sends via `send=true` with `reply_to` (quoted reply) and returns `suppressReply` to avoid duplicate messages.

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
| `/guide` | List all commands |
| `/positions` | Open positions |
| `/orders` | All pending (open) orders |
| `/nt` | Nearest pending trigger price and distance |
| `/tpd` | Today's closed trade profit/loss (NY day) |
| `/sld` | Stop-loss distance on open trades |
| `/cts` | Current trade status with floating P/L |
| `/chart` | Live XAUUSD M5 chart (sends image to WhatsApp) |

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

Commands: `guide`, `help` (alias), `positions`, `orders`, `nt`, `close_price` (alias), `tpd`, `sld`, `cts`, `chart`

`send` defaults to **`true`** (delivers to the account's `whatsapp_target` group). Use `send=false` to preview the message in JSON only.

**`/chart`:** Renders a live XAUUSD M5 candlestick chart from MT5 and sends a **WhatsApp image** (not plain text). With `send=false`, the API returns a preview caption only — no image is generated or delivered. Requires chart dependencies (`make install-charts`).

Examples:

```bash
# Pending orders → sent to WhatsApp by default
curl "http://204.168.148.205:8080/api/commands/orders?account=valetax_main"

# Open positions (preview only, no WhatsApp send)
curl "http://204.168.148.205:8080/api/commands/positions?account=valetax_main&send=false"

# Today's P/L for a specific account (sent to WhatsApp)
curl "http://204.168.148.205:8080/api/commands/tpd?account=valetax_main"

# Nearest pending trigger
curl "http://204.168.148.205:8080/api/commands/nt"

# Stop-loss distances
curl "http://204.168.148.205:8080/api/commands/sld"

# Current trade status
curl "http://204.168.148.205:8080/api/commands/cts"

# Guide text
curl "http://204.168.148.205:8080/api/commands/guide"

# Live XAUUSD chart → sends image to WhatsApp
curl "http://204.168.148.205:8080/api/commands/chart?account=valetax_main"

# Chart preview only (caption JSON, no image send)
curl "http://204.168.148.205:8080/api/commands/chart?account=valetax_main&send=false"
```

Response (text commands):

```json
{
  "command": "positions",
  "account": "valetax_main",
  "message": "Open positions (1):\n#12345 EURUSD BUY vol=0.1 open=1.08500 P/L=$12.50",
  "sent": true
}
```

Response (`/chart` with `send=true` — image delivered via OpenClaw; `message` is the image caption):

```json
{
  "command": "chart",
  "account": "valetax_main",
  "message": "📈 Live chart · XAUUSD.vx M5\nPending 2 · Open 1\nBid 4120.50 · Ask 4120.70",
  "sent": true
}
```

Response (`/chart` with `send=false` — preview only):

```json
{
  "command": "chart",
  "account": "valetax_main",
  "message": "Live XAUUSD M5 chart (preview only; send=true delivers image).",
  "sent": false
}
```

---

### Run a command (POST)

```http
POST /api/commands/{command}?account={name}&send={true|false}&target={jid}
```

Same behavior as GET. Useful for automation tools that prefer POST.

```bash
curl -X POST \
  "http://204.168.148.205:8080/api/commands/positions?account=valetax_main"

curl -X POST \
  "http://204.168.148.205:8080/api/commands/chart?account=valetax_main"
```

---

### Run a command (JSON body)

```http
POST /api/commands/run
Content-Type: application/json
```

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"command":"/orders","account":"valetax_main"}' \
  http://204.168.148.205:8080/api/commands/run

curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"command":"/chart","account":"valetax_main","send":true}' \
  http://204.168.148.205:8080/api/commands/run
```

Body fields:

| Field | Type | Description |
|-------|------|-------------|
| `command` | string | Command name with or without `/` |
| `account` | string | Optional account from `accounts.yaml` |
| `send` | boolean | Send response to WhatsApp (default `true`) |
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
OpenClaw plugin registerCommand (primary — bypasses LLM)
        ↓
GET http://127.0.0.1:8080/api/commands/positions?account=valetax_main
        ↓
Plugin returns { text } → OpenClaw delivers to group

Plugin `registerCommand` handles all slash commands (no webhook duplicate).
```

### One-time setup on the server

```bash
# From the mt5_trigger repo (reads accounts.yaml + settings.yaml)
make install-openclaw-hook

# Restart OpenClaw so the plugin loads
openclaw gateway restart
```

This installs `openclaw-plugins/mt5-whatsapp-commands` which registers native
slash commands (`/positions`, `/tpd`, etc.) via `api.registerCommand`, plus a
webhook fallback for legacy paths only.

enables `channels.whatsapp.pluginHooks.messageReceived`, and configures:

- Native plugin commands: `/guide`, `/positions`, `/orders`, `/nt`, `/tpd`, `/sld`, `/cts`, `/chart`
- Only from configured `whatsapp_target` group JIDs

`make deploy` runs the hook install automatically.

Verify:

```bash
make diagnose-whatsapp
openclaw plugins list | grep mt5-whatsapp-commands
```

Then in the group (as an admin in `commands.whatsapp_admins`):

```text
/guide
/positions
/chart
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

Configure OpenClaw WhatsApp access (in `~/.openclaw/openclaw.json`).
`make install-openclaw-hook` sets `pluginHooks.messageReceived` and group entries
automatically; merge with your existing config:

```json5
{
  channels: {
    whatsapp: {
      enabled: true,
      dmPolicy: "disabled",
      groupPolicy: "allowlist",
      groupAllowFrom: ["+2349050273391"],
      pluginHooks: {
        messageReceived: true,  // required — WhatsApp hides inbound from plugins by default
      },
      groups: {
        "120363428584387160@g.us": {
          requireMention: false,
        },
      },
    },
  },
  plugins: {
    entries: {
      "mt5-whatsapp-commands": {
        enabled: true,
        config: {
          webhookUrl: "http://127.0.0.1:8080/webhooks/whatsapp/inbound",
          groupJids: ["120363428584387160@g.us"],
        },
      },
    },
  },
}
```

---

## Charts

Live charts use the same pipeline as `make send-chart` and `/chart`:

1. Fetch live M5 candles from MT5 (auto-detects `XAUUSD.vx` / `XAUUSD`)
2. Overlay nearest pending orders and open position levels
3. Render PNG and send via OpenClaw `--media`

**Requirements:** `make install-charts` (included in `make setup`)

**CLI (server):**

```bash
make send-chart
```

**WhatsApp:** `/chart` in the group (admins only)

**HTTP API:**

```bash
curl "http://204.168.148.205:8080/api/commands/chart?account=valetax_main"
```

---

## Configuration

### `config/settings.yaml` (global commands — single source of truth)

```yaml
commands:
  enabled: true
  whatsapp_admins:        # ONLY edit admins here
    - "+2349050273391"
  cooldown_seconds: 30
```

After changing admins, run `make install-openclaw-hook && openclaw gateway restart` to sync into OpenClaw.

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
| Positions | `GET http://204.168.148.205:8080/api/commands/positions` |
| Pending orders | `GET http://204.168.148.205:8080/api/commands/orders` |
| Nearest trigger | `GET http://204.168.148.205:8080/api/commands/nt` |
| Today P/L | `GET http://204.168.148.205:8080/api/commands/tpd` |
| SL distance | `GET http://204.168.148.205:8080/api/commands/sld` |
| Trade status | `GET http://204.168.148.205:8080/api/commands/cts` |
| Live chart (image) | `GET http://204.168.148.205:8080/api/commands/chart` |
| Guide | `GET http://204.168.148.205:8080/api/commands/guide` |
| WhatsApp inbound | `POST http://204.168.148.205:8080/webhooks/whatsapp/inbound` |
