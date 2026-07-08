export type ForwardConfig = {
  webhookUrl: string;
  groupJids: Set<string>;
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

export function configFromEnv(): ForwardConfig | null {
  const webhookUrl = readEnv("MT5_TRIGGER_WEBHOOK_URL");
  if (!webhookUrl) {
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
  return {
    webhookUrl,
    groupJids,
    apiToken: apiToken || undefined,
  };
}

export function configFromPlugin(
  pluginConfig: Record<string, unknown> | undefined,
): ForwardConfig | null {
  if (!pluginConfig) {
    return null;
  }

  const webhookUrl =
    typeof pluginConfig.webhookUrl === "string"
      ? pluginConfig.webhookUrl.trim()
      : "";
  if (!webhookUrl) {
    return null;
  }

  const groupJids = new Set<string>();
  const rawJids = pluginConfig.groupJids;
  if (Array.isArray(rawJids)) {
    for (const jid of rawJids) {
      if (typeof jid === "string" && jid.endsWith("@g.us")) {
        groupJids.add(jid.trim());
      }
    }
  }

  const apiToken =
    typeof pluginConfig.apiToken === "string"
      ? pluginConfig.apiToken.trim()
      : undefined;

  return {
    webhookUrl,
    groupJids,
    apiToken: apiToken || undefined,
  };
}

export function resolveConfig(
  pluginConfig?: Record<string, unknown>,
): ForwardConfig | null {
  return configFromPlugin(pluginConfig) ?? configFromEnv();
}

function groupFromSessionKey(sessionKey?: string): string {
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

export function isAllowedGroup(groupJid: string, allowed: Set<string>): boolean {
  if (!groupJid.endsWith("@g.us")) {
    return false;
  }
  if (allowed.size === 0) {
    return true;
  }
  return allowed.has(groupJid);
}

export async function postInbound(
  config: ForwardConfig,
  payload: Record<string, unknown>,
): Promise<void> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (config.apiToken) {
    headers["X-API-Token"] = config.apiToken;
  }

  const response = await fetch(config.webhookUrl, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`mt5_trigger webhook ${response.status}: ${body}`);
  }
}

export async function forwardSlashCommand(
  config: ForwardConfig,
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

  const sender = resolveSender(message, metadata);
  if (!sender) {
    log?.(`skip slash command without sender in ${groupJid}`);
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
