import { definePluginEntry } from 'openclaw/plugin-sdk/plugin-entry'

import {
  accountForGroup,
  fetchMt5Command,
  groupFromSessionKey,
  isAllowedAdmin,
  isAllowedGroup,
  isWhatsAppChannel,
  normalizePhone,
  resolveConfig,
  resolveGroupJid,
} from './forward.js'
import {
  lookupMessageId,
  messageCacheKey,
  rememberMessageId,
} from './message-cache.js'

type PluginCommandContext = {
  senderId?: string
  channel?: string
  channelId?: string
  commandBody?: string
  to?: string
  from?: string
  sessionKey?: string
  messageId?: string
  pluginConfig?: Record<string, unknown>
  config?: {
    plugins?: {
      entries?: Record<string, { config?: Record<string, unknown> }>
    }
  }
}

type MessageHookContext = {
  channelId?: string
  senderId?: string
  messageId?: string
  sessionKey?: string
  to?: string
  from?: string
  content?: string
  metadata?: Record<string, unknown>
}

type MessageReceivedEvent = {
  channelId?: string
  content?: string
  senderId?: string
  messageId?: string
  to?: string
  from?: string
}

type OpenClawApi = {
  logger: { info: (msg: string) => void; error: (msg: string) => void }
  config?: PluginCommandContext['config']
  on?: (
    hook: string,
    handler: (
      event: MessageReceivedEvent,
      ctx: MessageHookContext,
    ) => Promise<void> | void,
  ) => void
  registerCommand: (def: {
    name: string
    description: string
    requireAuth?: boolean
    handler: (
      ctx: PluginCommandContext,
    ) => Promise<{ text?: string; suppressReply?: boolean }>
  }) => void
}

const PLUGIN_ID = 'mt5-whatsapp-commands'

function pluginConfigFromContext(ctx: {
  pluginConfig?: Record<string, unknown>
  config?: PluginCommandContext['config']
}): Record<string, unknown> | undefined {
  if (ctx.pluginConfig) {
    return ctx.pluginConfig
  }
  return ctx.config?.plugins?.entries?.[PLUGIN_ID]?.config
}

const MT5_COMMANDS = [
  { name: 'guide', description: 'List MT5 Trigger commands' },
  { name: 'positions', description: 'Open positions' },
  { name: 'orders', description: 'All pending orders' },
  { name: 'nt', description: 'Nearest pending trigger price' },
  { name: 'tpd', description: "Today's closed P/L" },
  { name: 'sld', description: 'Stop-loss distance on open trades' },
  { name: 'cts', description: 'Current trade status' },
  { name: 'chart', description: 'Live XAUUSD M5 chart (image)' },
  { name: 'authorize', description: 'Grant command access to a phone number' },
  { name: 'unauthorize', description: 'Revoke command access from a phone number' },
] as const

const ADMIN_COMMANDS = new Set(['authorize', 'unauthorize'])

function resolveCommandSender(ctx: PluginCommandContext): string {
  const raw = ctx.senderId ?? ctx.from ?? ''
  return normalizePhone(raw)
}

function resolveCommandGroup(ctx: PluginCommandContext): string {
  const to = (ctx.to ?? '').trim()
  if (to.endsWith('@g.us')) {
    return to
  }
  const fromSession = groupFromSessionKey(ctx.sessionKey)
  if (fromSession.endsWith('@g.us')) {
    return fromSession
  }
  return resolveGroupJid({
    channelId: ctx.channelId ?? ctx.channel,
    groupJid: to,
    sessionKey: ctx.sessionKey,
  })
}

function resolveReplyTo(
  ctx: PluginCommandContext,
  groupJid: string,
  sender: string,
): string | null {
  const commandBody = (ctx.commandBody ?? '').trim()
  return lookupMessageId(
    messageCacheKey({
      sessionKey: ctx.sessionKey,
      body: commandBody,
    }),
    messageCacheKey({
      channelId: ctx.channelId ?? ctx.channel,
      to: groupJid,
      sender,
      body: commandBody,
    }),
    ctx.messageId?.trim() ?? '',
  )
}

export default definePluginEntry({
  id: 'mt5-whatsapp-commands',
  name: 'MT5 WhatsApp Commands',
  register(api: OpenClawApi) {
    const log = (line: string) =>
      api.logger.info(`[mt5-whatsapp-commands] ${line}`)
    const baseConfig = () =>
      resolveConfig(pluginConfigFromContext({ config: api.config }))

    api.on?.('message_received', (event, ctx) => {
      const channelId = ctx.channelId ?? event.channelId
      if (!isWhatsAppChannel(channelId)) {
        return
      }

      const messageId = ctx.messageId ?? event.messageId
      const content = (event.content ?? ctx.content ?? '').trim()
      if (!messageId || !content.startsWith('/')) {
        return
      }

      const sender = normalizePhone(ctx.senderId ?? event.senderId ?? ctx.from ?? '')
      const to = (ctx.to ?? event.to ?? groupFromSessionKey(ctx.sessionKey)).trim()
      rememberMessageId(
        messageCacheKey({ sessionKey: ctx.sessionKey, body: content }),
        String(messageId),
      )
      rememberMessageId(
        messageCacheKey({
          channelId,
          to,
          sender,
          body: content,
        }),
        String(messageId),
      )
    })

    const runRegisteredCommand = async (
      command: string,
      ctx: PluginCommandContext,
    ): Promise<{ text?: string; suppressReply?: boolean }> => {
      const config = resolveConfig(pluginConfigFromContext(ctx)) ?? baseConfig()
      if (!config) {
        return {
          text: 'MT5 plugin not configured. Run: make install-openclaw-hook',
        }
      }

      const sender = resolveCommandSender(ctx)
      if (!isAllowedAdmin(sender, config.admins)) {
        log(`denied /${command} sender=${sender || '(unknown)'}`)
        return { text: 'You are not authorized to run MT5 commands.' }
      }

      const groupJid = resolveCommandGroup(ctx)
      if (!isAllowedGroup(groupJid, config.groupJids)) {
        return {
          text: `Commands are not enabled for this group (${groupJid || 'unknown'}).`,
        }
      }

      const account = accountForGroup(groupJid, config)
      if (!account) {
        return { text: `No MT5 account mapped to group ${groupJid}.` }
      }

      try {
        const replyTo = resolveReplyTo(ctx, groupJid, sender)
        log(
          `command /${command} sender=${sender} group=${groupJid} account=${account} replyTo=${replyTo || '(none)'}`,
        )
        if (ADMIN_COMMANDS.has(command)) {
          const commandText = (ctx.commandBody ?? `/${command}`).trim()
          const result = await fetchMt5Command(config, command, account, {
            send: true,
            replyTo,
            target: groupJid,
            commandText,
          })
          if (!result.sent) {
            return { text: result.message || 'Admin command failed.' }
          }
          log(`command /${command} delivered (${result.message.length} chars)`)
          return { suppressReply: true }
        }
        const result = await fetchMt5Command(config, command, account, {
          send: true,
          replyTo,
          target: groupJid,
        })
        if (!result.sent) {
          api.logger.error(
            `[mt5-whatsapp-commands] /${command} WhatsApp delivery failed ` +
              `(account=${account} group=${groupJid} replyTo=${replyTo || 'none'})`,
          )
          return { suppressReply: true }
        }
        log(`command /${command} delivered (${result.message.length} chars)`)
        return { suppressReply: true }
      } catch (error) {
        const msg = error instanceof Error ? error.message : String(error)
        api.logger.error(
          `[mt5-whatsapp-commands] /${command} failed before delivery: ${msg}`,
        )
        return { text: `MT5 error: ${msg}` }
      }
    }

    for (const command of MT5_COMMANDS) {
      api.registerCommand({
        name: command.name,
        description: command.description,
        requireAuth: false,
        handler: async (ctx: PluginCommandContext) =>
          runRegisteredCommand(command.name, ctx),
      })
    }
  },
})
