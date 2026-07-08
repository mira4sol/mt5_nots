import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

import {
  accountForGroup,
  fetchMt5Command,
  forwardSlashCommand,
  groupFromSessionKey,
  isAllowedAdmin,
  isAllowedGroup,
  normalizePhone,
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

type BeforeDispatchEvent = {
  content?: string;
  body?: string;
  channel?: string;
  sessionKey?: string;
  senderId?: string;
};

type BeforeDispatchContext = {
  channelId?: string;
  conversationId?: string;
  sessionKey?: string;
  senderId?: string;
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

type OpenClawApi = {
  logger: { info: (msg: string) => void; error: (msg: string) => void };
  config?: PluginCommandContext["config"];
  registerCommand: (def: {
    name: string;
    description: string;
    requireAuth?: boolean;
    handler: (ctx: PluginCommandContext) => Promise<{ text: string }>;
  }) => void;
  on: (
    hook: string,
    handler: (...args: unknown[]) => Promise<void | { handled: boolean; text?: string }>,
  ) => void;
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
  { name: "orders", description: "All pending orders" },
  { name: "nt", description: "Nearest pending trigger price" },
  { name: "tpd", description: "Today's closed P/L" },
  { name: "sld", description: "Stop-loss distance on open trades" },
  { name: "cts", description: "Current trade status" },
] as const;

function resolveCommandSender(ctx: PluginCommandContext): string {
  const raw = ctx.senderId ?? ctx.from ?? "";
  return normalizePhone(raw);
}

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

function dispatchContext(
  event: BeforeDispatchEvent,
  ctx: BeforeDispatchContext,
): PluginCommandContext {
  return {
    senderId: event.senderId ?? ctx.senderId,
    from: event.senderId ?? ctx.senderId,
    to: ctx.conversationId,
    sessionKey: event.sessionKey ?? ctx.sessionKey,
    channelId: ctx.channelId,
    channel: event.channel,
  };
}

export default definePluginEntry({
  id: "mt5-whatsapp-commands",
  name: "MT5 WhatsApp Commands",
  register(api: OpenClawApi) {
    const log = (line: string) => api.logger.info(`[mt5-whatsapp-commands] ${line}`);
    const baseConfig = () =>
      resolveConfig(pluginConfigFromContext({ config: api.config }));

    const runRegisteredCommand = async (
      command: string,
      ctx: PluginCommandContext,
    ): Promise<{ text: string }> => {
      const config = resolveConfig(pluginConfigFromContext(ctx)) ?? baseConfig();
      if (!config) {
        return { text: "MT5 plugin not configured. Run: make install-openclaw-hook" };
      }

      const sender = resolveCommandSender(ctx);
      if (!isAllowedAdmin(sender, config.admins)) {
        log(`denied /${command} sender=${sender || "(unknown)"}`);
        return { text: "You are not authorized to run MT5 commands." };
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
        log(`command /${command} sender=${sender} group=${groupJid} account=${account}`);
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
        requireAuth: false,
        handler: async (ctx: PluginCommandContext) =>
          runRegisteredCommand(command.name, ctx),
      });
    }

    // OpenClaw reserves /help — intercept before native dispatch.
    api.on(
      "before_dispatch",
      async (event: BeforeDispatchEvent, ctx: BeforeDispatchContext) => {
        const text = (event.content ?? event.body ?? "").trim();
        if (!/^\/help\b/i.test(text)) {
          return;
        }
        log(`before_dispatch /help sender=${event.senderId ?? ctx.senderId ?? "(unknown)"}`);
        const result = await runRegisteredCommand("help", dispatchContext(event, ctx));
        return { handled: true, text: result.text };
      },
    );

    api.on("message_received", async (event: MessageReceivedEvent, ctx: MessageReceivedContext) => {
      const config = resolveConfig(pluginConfigFromContext(ctx)) ?? baseConfig();
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
