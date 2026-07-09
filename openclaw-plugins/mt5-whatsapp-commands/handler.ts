import {
  configFromEnv,
  forwardSlashCommand,
  isPluginHandledCommand,
  type InboundMessage,
} from "./forward.js";

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

const log = (line: string) => console.log(`[mt5-whatsapp-commands] ${line}`);

export default async function handler(event: HookEvent): Promise<void> {
  if (event.type !== "message" || event.action !== "received") {
    return;
  }

  const config = configFromEnv();
  if (!config) {
    log("internal hook missing MT5_TRIGGER_WEBHOOK_URL env");
    return;
  }

  const context = event.context ?? {};
  const text = (context.content ?? "").trim();
  if (!text.startsWith("/")) {
    return;
  }
  if (isPluginHandledCommand(text)) {
    log(`skip plugin-handled command ${text} (registerCommand owns delivery)`);
    return;
  }

  const metadata = context.metadata ?? {};
  const message: InboundMessage = {
    channelId: context.channelId,
    content: context.content,
    sender: context.from,
    groupJid: context.conversationId,
    messageId: context.messageId,
    sessionKey: event.sessionKey,
  };

  try {
    await forwardSlashCommand(config, message, metadata, log);
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    console.error("[mt5-whatsapp-commands] internal hook forward failed:", msg);
  }
}
