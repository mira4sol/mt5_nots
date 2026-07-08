type MessageReceivedContext = {
  from?: string;
  content?: string;
  channelId?: string;
  conversationId?: string;
  messageId?: string;
  metadata?: Record<string, unknown>;
};

type HookEvent = {
  type: string;
  action: string;
  sessionKey?: string;
  context: MessageReceivedContext;
};

function readEnv(key: string): string {
  const value = process.env[key];
  return typeof value === "string" ? value.trim() : "";
}

function configuredGroupJids(): Set<string> {
  const multi = readEnv("WHATSAPP_GROUP_JIDS");
  if (multi) {
    return new Set(
      multi
        .split(",")
        .map((jid) => jid.trim())
        .filter((jid) => jid.endsWith("@g.us")),
    );
  }
  const single = readEnv("WHATSAPP_GROUP_JID");
  if (single.endsWith("@g.us")) {
    return new Set([single]);
  }
  return new Set();
}

function resolveSender(context: MessageReceivedContext): string {
  const metadata = context.metadata ?? {};
  const senderId = metadata.senderId;
  if (typeof senderId === "string" && senderId.trim()) {
    return senderId.trim();
  }
  return (context.from ?? "").trim();
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

function resolveGroupJid(
  context: MessageReceivedContext,
  sessionKey?: string,
): string {
  const fromSession = groupFromSessionKey(sessionKey);
  if (fromSession.endsWith("@g.us")) {
    return fromSession;
  }
  const conversationId = (context.conversationId ?? "").trim();
  if (conversationId.endsWith("@g.us")) {
    return conversationId;
  }
  const metadata = context.metadata ?? {};
  const chatId = metadata.chatId ?? metadata.conversationId ?? metadata.groupId;
  if (typeof chatId === "string" && chatId.endsWith("@g.us")) {
    return chatId.trim();
  }
  return conversationId;
}

function isAllowedGroup(groupJid: string, allowed: Set<string>): boolean {
  if (!groupJid.endsWith("@g.us")) {
    return false;
  }
  if (allowed.size === 0) {
    return true;
  }
  return allowed.has(groupJid);
}

async function postInbound(payload: Record<string, unknown>): Promise<void> {
  const webhookUrl = readEnv("MT5_TRIGGER_WEBHOOK_URL");
  const token = readEnv("COMMAND_API_TOKEN");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["X-API-Token"] = token;
  }

  const response = await fetch(webhookUrl, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`mt5_trigger webhook ${response.status}: ${body}`);
  }
}

export default async function handler(event: HookEvent): Promise<void> {
  if (event.type !== "message" || event.action !== "received") {
    return;
  }

  const context = event.context ?? {};
  if ((context.channelId ?? "").toLowerCase() !== "whatsapp") {
    return;
  }

  const groupJid = resolveGroupJid(context, event.sessionKey);
  const allowedGroups = configuredGroupJids();
  if (!isAllowedGroup(groupJid, allowedGroups)) {
    return;
  }

  const text = (context.content ?? "").trim();
  if (!text.startsWith("/")) {
    return;
  }

  const sender = resolveSender(context);
  if (!sender) {
    return;
  }

  const payload = {
    text,
    sender,
    group_jid: groupJid,
    message_id: context.messageId ?? null,
  };

  try {
    await postInbound(payload);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error("[mt5-whatsapp-commands] forward failed:", message);
  }
}
