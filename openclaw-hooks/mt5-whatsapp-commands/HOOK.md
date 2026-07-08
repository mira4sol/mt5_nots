---
name: mt5-whatsapp-commands
description: "Forward WhatsApp group slash commands to mt5_trigger"
metadata:
  {
    "openclaw":
      {
        "emoji": "📈",
        "events": ["message:received"],
        "requires":
          {
            "env": ["WHATSAPP_GROUP_JIDS", "MT5_TRIGGER_WEBHOOK_URL"],
          },
      },
  }
---

# MT5 WhatsApp Commands

Forwards inbound WhatsApp group messages that start with `/` to the mt5_trigger
webhook (`/webhooks/whatsapp/inbound`). mt5_trigger validates admin senders,
runs the MT5 command, and replies to the group.

Install from the mt5_trigger repo:

```bash
make install-openclaw-hook
```

Then restart the OpenClaw gateway:

```bash
openclaw gateway
```

Required hook env (set by the install script from `.env`):

| Variable | Description |
|----------|-------------|
| `WHATSAPP_GROUP_JIDS` | Comma-separated group JIDs from `accounts.yaml` (`whatsapp_target`) |
| `MT5_TRIGGER_WEBHOOK_URL` | mt5_trigger inbound webhook URL |
| `COMMAND_API_TOKEN` | Optional API token for the webhook |

Works best when WhatsApp group replies require a mention (OpenClaw default), so
`/positions` is handled by mt5_trigger without also waking the OpenClaw agent.
