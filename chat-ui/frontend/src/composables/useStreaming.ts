import { onUnmounted } from 'vue'
import { useChatStore } from '@/stores/chat'

export function useStreaming() {
  const chat = useChatStore()
  const timers: Record<string, ReturnType<typeof setInterval> | null> = {}

  function stream(key: string, text: string) {
    stopStream(key)
    chat.startStream(key)
    const chars = text.split('')
    let i = 0

    timers[key] = setInterval(() => {
      const n = Math.floor(Math.random() * 4) + 2
      for (let c = 0; c < n && i < chars.length; c++, i++) {
        chat.appendToken(key, chars[i]!)
      }
      if (i >= chars.length) {
        stopStream(key)
        chat.finishStream(key)
      }
    }, 18)
  }

  function stopStream(key: string) {
    const t = timers[key]
    if (t !== null && t !== undefined) {
      clearInterval(t)
      timers[key] = null
    }
  }

  onUnmounted(() => {
    Object.keys(timers).forEach(k => stopStream(k))
  })

  return { stream, stopStream }
}
