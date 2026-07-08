import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

import {
  accountForGroup,
  fetchMt5Command,
  forwardSlashCommand,
  groupFromSessionKey,
  isAllowedGroup,
  resolveConfig,
  resolveGroupJid,
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
  config?: PluginCommandContext["config"];
};

type PluginCommandContext = {
  senderId?: string;
  channel?: string;
  channelId?: string;
  isAuthorizedSender?: boolean;
  commandBody?: string;
  to?: string;
  from?: string;
  sessionKey?: string;
  pluginConfig?: Record<string, unknown>;
  config?: {
    plugins?: {
      entries?: Record<string, { config?: Record<string, unknown> }>;
    };
  };
};

const PLUGIN_ID = "mt5-whatsapp-commands";

function pluginConfigFromContext(
  ctx: { pluginConfig?: Record<string, unknown>; config?: PluginCommandContext["config"] },
): Record<string, unknown> | undefined {
  if (ctx.pluginConfig) {
    return ctx.pluginConfig;
  }
  return ctx.config?.plugins?.entries?.[PLUGIN_ID]?.config;
}

const MT5_COMMANDS = [
  { name: "positions", description: "Open positions" },
  { name: "close_price", description: "Nearest pending trigger price" },
  { name: "tpd", description: "Today's closed P/L" },
  { name: "sld", description: "Stop-loss distance on open trades" },
  { name: "cts", description: "Current trade status" },
] as const;

function resolveCommandGroup(ctx: PluginCommandContext): string {
  const to = (ctx.to ?? "").trim();
  if (to.endsWith("@g.us")) {
    return to;
  }
  const fromSession = groupFromSessionKey(ctx.sessionKey);
  if (fromSession.endsWith("@g.us")) {
    return fromSession;
  }
  return resolveGroupJid({
    channelId: ctx.channelId ?? ctx.channel,
    groupJid: to,
    sessionKey: ctx.sessionKey,
  });
}

function helpText(): string {
  return (
    "MT5 Trigger commands:\n" +
    "/positions — open positions\n" +
    "/close_price — nearest pending trigger price\n" +
    "/tpd — today's closed P/L\n" +
    "/sld — stop-loss distance on open trades\n" +
    "/cts — current trade status\n" +
    "/mt5help — this list"
  );
}

export default definePluginEntry({
  id: "mt5-whatsapp-commands",
  name: "MT5 WhatsApp Commands",
  register(api) {
    const log = (line: string) => api.logger.info(`[mt5-whatsapp-commands] ${line}`);

    const runRegisteredCommand = async (
      command: string,
      ctx: PluginCommandContext,
    ): Promise<{ text: string }> => {
      const config = resolveConfig(pluginConfigFromContext(ctx));
      if (!config) {
        return { text: "MT5 plugin not configured. Run: make install-openclaw-hook" };
      }

      const groupJid = resolveCommandGroup(ctx);
      if (!isAllowedGroup(groupJid, config.groupJids)) {
        return { text: `Commands are not enabled for this group (${groupJid || "unknown"}).` };
      }

      const account = accountForGroup(groupJid, config);
      if (!account) {
        return { text: `No MT5 account mapped to group ${groupJid}.` };
      }

      try {
        log(`command /${command} group=${groupJid} account=${account}`);
        const message = await fetchMt5Command(config, command, account);
        return { text: message };
      } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        api.logger.error(`[mt5-whatsapp-commands] /${command} failed: ${msg}`);
        return { text: `MT5 error: ${msg}` };
      }
    };

    for (const command of MT5_COMMANDS) {
      api.registerCommand({
        name: command.name,
        description: command.description,
        requireAuth: true,
        handler: async (ctx: PluginCommandContext) =>
          runRegisteredCommand(command.name, ctx),
      });
    }

    api.registerCommand({
      name: "mt5help",
      description: "List MT5 Trigger commands",
      requireAuth: true,
      handler: async () => ({ text: helpText() }),
    });

    api.on("message_received", async (event: MessageReceivedEvent, ctx: MessageReceivedContext) => {
      const config = resolveConfig(pluginConfigFromContext(ctx));
      if (!config) {
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
