import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

import {
  accountForGroup,
  fetchMt5Command,
  groupFromSessionKey,
  isAllowedAdmin,
  isAllowedGroup,
  normalizePhone,
  resolveConfig,
  resolveGroupJid,
} from "./forward.js";

type PluginCommandContext = {
  senderId?: string;
  channel?: string;
  channelId?: string;
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
  { name: "guide", description: "List MT5 Trigger commands" },
  { name: "positions", description: "Open positions" },
  { name: "orders", description: "All pending orders" },
  { name: "nt", description: "Nearest pending trigger price" },
  { name: "tpd", description: "Today's closed P/L" },
  { name: "sld", description: "Stop-loss distance on open trades" },
  { name: "cts", description: "Current trade status" },
  { name: "chart", description: "Live XAUUSD M5 chart (image)" },
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
        const sendImage = command === "chart";
        const message = await fetchMt5Command(config, command, account, { send: sendImage });
        if (sendImage) {
          return { text: "📈 Live chart sent." };
        }
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
  },
});
