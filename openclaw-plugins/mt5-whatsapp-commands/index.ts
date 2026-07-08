import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

import {
  forwardSlashCommand,
  resolveConfig,
  type InboundMessage,
} from "./forward.js";

type MessageReceivedEvent = {
  content?: string;
  messageId?: string;
  senderId?: string;
  threadId?: string;
  metadata?: Record<string, unknown>;
};

type MessageReceivedContext = {
  channelId?: string;
  sessionKey?: string;
  senderId?: string;
  messageId?: string;
  threadId?: string;
  pluginConfig?: Record<string, unknown>;
};

export default definePluginEntry({
  id: "mt5-whatsapp-commands",
  name: "MT5 WhatsApp Commands",
  register(api) {
    const log = (line: string) => api.logger.info(`[mt5-whatsapp-commands] ${line}`);

    api.on("message_received", async (event: MessageReceivedEvent, ctx: MessageReceivedContext) => {
      const config = resolveConfig(ctx.pluginConfig);
      if (!config) {
        log("missing webhook config (plugin config or env)");
        return;
      }

      const metadata = {
        ...(event.metadata ?? {}),
        senderId: event.senderId ?? ctx.senderId,
        chatId: event.threadId ?? ctx.threadId,
      };

      const message: InboundMessage = {
        channelId: ctx.channelId,
        content: event.content,
        sender: event.senderId ?? ctx.senderId,
        groupJid: event.threadId ?? ctx.threadId,
        messageId: event.messageId ?? ctx.messageId,
        sessionKey: ctx.sessionKey,
      };

      try {
        await forwardSlashCommand(config, message, metadata, log);
      } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        api.logger.error(`[mt5-whatsapp-commands] forward failed: ${msg}`);
      }
    });
  },
});
