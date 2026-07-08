import { describe, expect, it } from "vitest";

import {
  clearMessageCacheForTests,
  lookupMessageId,
  messageCacheKey,
  rememberMessageId,
} from "./message-cache.js";

describe("message-cache", () => {
  it("stores and retrieves by session key", () => {
    clearMessageCacheForTests();
    const key = messageCacheKey({
      sessionKey: "agent:main:whatsapp:group:120363@g.us",
      body: "/orders",
    });
    rememberMessageId(key, "MSG123");
    expect(lookupMessageId(key)).toBe("MSG123");
  });

  it("stores and retrieves by channel/to/sender/body", () => {
    clearMessageCacheForTests();
    const key = messageCacheKey({
      channelId: "whatsapp",
      to: "120363@g.us",
      sender: "+15551234567",
      body: "/positions",
    });
    rememberMessageId(key, "MSG456");
    expect(lookupMessageId(key)).toBe("MSG456");
  });
});
