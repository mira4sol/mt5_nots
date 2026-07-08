export type PluginRuntimeConfig = {
  apiBaseUrl: string;
  webhookUrl: string;
  groupJids: Set<string>;
  accountsByGroup: Record<string, string>;
  admins: string[];
  apiToken?: string;
};

export type InboundMessage = {
  channelId?: string;
  content?: string;
  sender?: string;
  groupJid?: string;
  messageId?: string | null;
  sessionKey?: string;
};

function readEnv(key: string): string {
  const value = process.env[key];
  return typeof value === "string" ? value.trim() : "";
}

function parseGroupJids(raw: unknown): Set<string> {
  const groupJids = new Set<string>();
  if (Array.isArray(raw)) {
    for (const jid of raw) {
      if (typeof jid === "string" && jid.endsWith("@g.us")) {
        groupJids.add(jid.trim());
      }
    }
  }
  return groupJids;
}

function parseAdmins(raw: unknown): string[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw
    .filter((entry): entry is string => typeof entry === "string" && entry.trim().length > 0)
    .map((entry) => normalizePhone(entry.trim()));
}

function parseAccountsByGroup(raw: unknown): Record<string, string> {
  if (!raw || typeof raw !== "object") {
    return {};
  }
  const out: Record<string, string> = {};
  for (const [jid, account] of Object.entries(raw)) {
    if (jid.endsWith("@g.us") && typeof account === "string" && account.trim()) {
      out[jid] = account.trim();
    }
  }
  return out;
}

export function configFromEnv(): PluginRuntimeConfig | null {
  const webhookUrl = readEnv("MT5_TRIGGER_WEBHOOK_URL");
  const apiBaseUrl = readEnv("MT5_TRIGGER_API_URL");
  if (!webhookUrl && !apiBaseUrl) {
    return null;
  }

  const groupJids = new Set<string>();
  const multi = readEnv("WHATSAPP_GROUP_JIDS");
  if (multi) {
    for (const jid of multi.split(",")) {
      const trimmed = jid.trim();
      if (trimmed.endsWith("@g.us")) {
        groupJids.add(trimmed);
      }
    }
  } else {
    const single = readEnv("WHATSAPP_GROUP_JID");
    if (single.endsWith("@g.us")) {
      groupJids.add(single);
    }
  }

  const apiToken = readEnv("COMMAND_API_TOKEN");
  const admins = parseAdmins(readEnv("WHATSAPP_ADMINS").split(",").filter(Boolean));
  return {
    apiBaseUrl: apiBaseUrl || webhookUrl.replace(/\/webhooks\/whatsapp\/inbound\/?$/, ""),
    webhookUrl: webhookUrl || `${apiBaseUrl}/webhooks/whatsapp/inbound`,
    groupJids,
    accountsByGroup: {},
    admins,
    apiToken: apiToken || undefined,
  };
}

export function configFromPlugin(
  pluginConfig: Record<string, unknown> | undefined,
): PluginRuntimeConfig | null {
  if (!pluginConfig) {
    return null;
  }

  const webhookUrl =
    typeof pluginConfig.webhookUrl === "string"
      ? pluginConfig.webhookUrl.trim()
      : "";
  const apiBaseUrl =
    typeof pluginConfig.apiBaseUrl === "string"
      ? pluginConfig.apiBaseUrl.trim()
      : webhookUrl.replace(/\/webhooks\/whatsapp\/inbound\/?$/, "");

  if (!apiBaseUrl) {
    return null;
  }

  const groupJids = parseGroupJids(pluginConfig.groupJids);
  const accountsByGroup = parseAccountsByGroup(pluginConfig.accountsByGroup);
  const admins = parseAdmins(pluginConfig.admins);
  const apiToken =
    typeof pluginConfig.apiToken === "string"
      ? pluginConfig.apiToken.trim()
      : undefined;

  return {
    apiBaseUrl,
    webhookUrl: webhookUrl || `${apiBaseUrl}/webhooks/whatsapp/inbound`,
    groupJids,
    accountsByGroup,
    admins,
    apiToken: apiToken || undefined,
  };
}

export function resolveConfig(
  pluginConfig?: Record<string, unknown>,
): PluginRuntimeConfig | null {
  return configFromPlugin(pluginConfig) ?? configFromEnv();
}

export function groupFromSessionKey(sessionKey?: string): string {
  const marker = ":whatsapp:group:";
  if (!sessionKey) {
    return "";
  }
  const idx = sessionKey.indexOf(marker);
  if (idx === -1) {
    return "";
  }
  return sessionKey.slice(idx + marker.length).trim();
}

export function resolveGroupJid(
  message: InboundMessage,
  metadata: Record<string, unknown> = {},
): string {
  const fromSession = groupFromSessionKey(message.sessionKey);
  if (fromSession.endsWith("@g.us")) {
    return fromSession;
  }

  const explicit = (message.groupJid ?? "").trim();
  if (explicit.endsWith("@g.us")) {
    return explicit;
  }

  const chatId = metadata.chatId ?? metadata.conversationId ?? metadata.groupId;
  if (typeof chatId === "string" && chatId.endsWith("@g.us")) {
    return chatId.trim();
  }

  return explicit;
}

export function normalizePhone(sender: string): string {
  let value = sender.trim();
  if (!value) {
    return value;
  }
  if (value.includes("@")) {
    value = value.split("@", 1)[0] ?? value;
  }
  if (!value.startsWith("+")) {
    return `+${value}`;
  }
  return value;
}

export function resolveSender(
  message: InboundMessage,
  metadata: Record<string, unknown> = {},
): string {
  if (message.sender?.trim()) {
    return normalizePhone(message.sender.trim());
  }
  const senderId = metadata.senderId;
  if (typeof senderId === "string" && senderId.trim()) {
    return normalizePhone(senderId.trim());
  }
  return "";
}

export function isWhatsAppChannel(channelId?: string): boolean {
  const normalized = (channelId ?? "").trim().toLowerCase();
  return normalized === "whatsapp" || normalized === "wa";
}

export const PLUGIN_HANDLED_COMMANDS = new Set([
  "positions",
  "orders",
  "nt",
  "close_price",
  "tpd",
  "sld",
  "cts",
  "chart",
  "guide",
  "help",
  "mt5help",
]);

export function normalizeSlashCommand(text: string): string | null {
  const match = text.trim().match(/^\/([a-z0-9_-]+)\b/i);
  if (!match) {
    return null;
  }
  let cmd = match[1].toLowerCase().replace(/-/g, "_");
  if (cmd === "close_price") {
    cmd = "nt";
  }
  if (cmd === "help" || cmd === "mt5help") {
    cmd = "guide";
  }
  return cmd;
}

export function isPluginHandledCommand(text: string): boolean {
  const cmd = normalizeSlashCommand(text);
  return cmd !== null && PLUGIN_HANDLED_COMMANDS.has(cmd);
}

export function phoneDigits(sender: string): string {
  return normalizePhone(sender).replace(/\D/g, "");
}

export function isAllowedAdmin(sender: string | undefined, admins: string[]): boolean {
  if (!admins.length) {
    return true;
  }
  if (!sender?.trim()) {
    return false;
  }
  const senderDigits = phoneDigits(sender);
  return admins.some((admin) => phoneDigits(admin) === senderDigits);
}

export function isAllowedGroup(groupJid: string, allowed: Set<string>): boolean {
  if (!groupJid.endsWith("@g.us")) {
    return false;
  }
  if (allowed.size === 0) {
    return true;
  }
  return allowed.has(groupJid);
}

export function accountForGroup(
  groupJid: string,
  config: PluginRuntimeConfig,
): string | null {
  return config.accountsByGroup[groupJid] ?? null;
}

function authHeaders(config: PluginRuntimeConfig): Record<string, string> {
  const headers: Record<string, string> = {};
  if (config.apiToken) {
    headers["X-API-Token"] = config.apiToken;
  }
  return headers;
}

export async function fetchMt5Command(
  config: PluginRuntimeConfig,
  command: string,
  account: string,
  options: { send?: boolean } = {},
): Promise<string> {
  // OpenClaw displays the returned command text in chat; send=false avoids a
  // duplicate WhatsApp delivery from mt5_trigger's OpenClaw notifier.
  // /chart is the exception: send=true delivers the image via mt5_trigger.
  const send = options.send ?? false;
  const url =
    `${config.apiBaseUrl}/api/commands/${command}` +
    `?account=${encodeURIComponent(account)}&send=${send ? "true" : "false"}`;
  const response = await fetch(url, { headers: authHeaders(config) });
  const body = (await response.json()) as {
    message?: string;
    error?: string;
    detail?: string;
  };

  if (!response.ok) {
    throw new Error(body.detail || body.error || `mt5_trigger HTTP ${response.status}`);
  }
  if (body.error) {
    throw new Error(body.error);
  }
  return body.message || "OK";
}

export async function postInbound(
  config: PluginRuntimeConfig,
  payload: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...authHeaders(config),
  };

  const response = await fetch(config.webhookUrl, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });

  const body = (await response.json()) as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(
      `mt5_trigger webhook ${response.status}: ${JSON.stringify(body)}`,
    );
  }
  return body;
}

export async function forwardSlashCommand(
  config: PluginRuntimeConfig,
  message: InboundMessage,
  metadata: Record<string, unknown> = {},
  log?: (line: string) => void,
): Promise<boolean> {
  if (!isWhatsAppChannel(message.channelId)) {
    return false;
  }

  const groupJid = resolveGroupJid(message, metadata);
  if (!isAllowedGroup(groupJid, config.groupJids)) {
    log?.(`skip group ${groupJid || "(unknown)"}`);
    return false;
  }

  const text = (message.content ?? "").trim();
  if (!text.startsWith("/")) {
    return false;
  }
  if (isPluginHandledCommand(text)) {
    log?.(`skip webhook forward for plugin command ${text.split(/\s+/)[0]}`);
    return false;
  }

  const sender = resolveSender(message, metadata);
  if (!sender) {
    log?.(`skip slash command without sender in ${groupJid}`);
    return false;
  }
  if (!isAllowedAdmin(sender, config.admins)) {
    log?.(`skip unauthorized sender ${sender} in ${groupJid}`);
    return false;
  }

  const payload = {
    text,
    sender,
    group_jid: groupJid,
    message_id: message.messageId ?? null,
  };

  log?.(`forward ${text} from ${sender} in ${groupJid}`);
  await postInbound(config, payload);
  return true;
}
