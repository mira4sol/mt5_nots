const TTL_MS = 60_000;

type CacheEntry = { messageId: string; at: number };

const cache = new Map<string, CacheEntry>();

export function messageCacheKey(parts: {
  channelId?: string;
  to?: string;
  sender?: string;
  sessionKey?: string;
  body?: string;
}): string {
  const body = (parts.body ?? "").trim();
  if (parts.sessionKey) {
    return `session:${parts.sessionKey}|${body}`;
  }
  return [
    parts.channelId ?? "",
    parts.to ?? "",
    parts.sender ?? "",
    body,
  ].join("|");
}

export function rememberMessageId(key: string, messageId: string): void {
  if (!key || !messageId) {
    return;
  }
  cache.set(key, { messageId, at: Date.now() });
  prune();
}

export function lookupMessageId(...keys: string[]): string | null {
  const now = Date.now();
  for (const key of keys) {
    if (!key) {
      continue;
    }
    const hit = cache.get(key);
    if (!hit) {
      continue;
    }
    if (now - hit.at > TTL_MS) {
      cache.delete(key);
      continue;
    }
    return hit.messageId;
  }
  return null;
}

function prune(): void {
  const now = Date.now();
  for (const [key, entry] of cache) {
    if (now - entry.at > TTL_MS) {
      cache.delete(key);
    }
  }
}

export function clearMessageCacheForTests(): void {
  cache.clear();
}
