---
name: mt5-whatsapp-commands
description: "Forward WhatsApp group slash commands to mt5_trigger (fallback internal hook)"
metadata:
  {
    "openclaw":
      {
        "emoji": "📈",
        "events": ["message:received"],
      },
  }
---

# MT5 WhatsApp Commands (internal hook fallback)

Primary delivery uses the **OpenClaw plugin** in
`openclaw-plugins/mt5-whatsapp-commands` with
`channels.whatsapp.pluginHooks.messageReceived: true`.

This internal hook is kept as a fallback on OpenClaw builds where workspace
hooks work. Install everything with:

```bash
make install-openclaw-hook
openclaw gateway restart
```

Required env when using the internal hook fallback:

| Variable | Description |
|----------|-------------|
| `WHATSAPP_GROUP_JIDS` | Comma-separated group JIDs from `accounts.yaml` |
| `MT5_TRIGGER_WEBHOOK_URL` | mt5_trigger inbound webhook URL |
| `COMMAND_API_TOKEN` | Optional API token for the webhook |
