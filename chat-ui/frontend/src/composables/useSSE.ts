import { onUnmounted } from 'vue'
import { useChatStore } from '@/stores/chat'

export interface SSEMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface SSEOptions {
  mode?: 'single' | 'multi'
}

export function useSSE() {
  const chat = useChatStore()
  const controllers: Record<string, AbortController> = {}

  async function stream(key: string, messages: SSEMessage[], opts: SSEOptions = {}) {
    stopStream(key)
    chat.startStream(key)

    const controller = new AbortController()
    controllers[key] = controller

    try {
      const resp = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages, mode: opts.mode ?? 'single' }),
        signal: controller.signal,
      })

      if (!resp.ok || !resp.body) {
        chat.appendToken(key, `*Error ${resp.status}: could not connect to backend.*`)
        chat.finishStream(key)
        return
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      let finished = false

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw) continue
          try {
            const evt = JSON.parse(raw) as { type: string; [k: string]: unknown }
            if (evt.type === 'text') {
              chat.appendToken(key, evt.text as string)
            } else if (evt.type === 'done') {
              chat.finishStream(key)
              finished = true
            } else if (evt.type === 'error') {
              chat.appendToken(key, `\n\n*Error: ${evt.error as string}*`)
              chat.finishStream(key)
              finished = true
            }
          } catch { /* ignore malformed lines */ }
        }
      }

      if (!finished) chat.finishStream(key)
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        chat.appendToken(key, '\n\n*Connection error — is the backend running?*')
        chat.finishStream(key)
      }
    } finally {
      delete controllers[key]
    }
  }

  function stopStream(key: string) {
    controllers[key]?.abort()
    delete controllers[key]
  }

  onUnmounted(() => {
    Object.values(controllers).forEach(c => c.abort())
  })

  return { stream, stopStream }
}
