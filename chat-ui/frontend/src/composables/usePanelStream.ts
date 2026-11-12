import { computed, ref } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useSSE, type SSEMessage, type SSEOptions } from '@/composables/useSSE'
import { useVerdict } from '@/composables/useVerdict'
import { renderText } from '@/utils/renderText'

/** Matches the backend's CONTEXT_WINDOW_TOKENS default (claude_loop.py). */
const CONTEXT_WINDOW_TOKENS = 200_000

/** The conversation behind one diagnostic panel: its stream, follow-ups and
 *  verdict. NodePanel, AreaPanel and PlantPanel each carried a copy of this
 *  (gh-29); they now differ only in their prompt, layout and card gating.
 *
 *  `options` is read each time a request goes out, so a panel can depend on
 *  live UI state (multi-agent toggle, breadcrumb level). */
export function usePanelStream(key: string, options: () => SSEOptions) {
  const chat = useChatStore()
  const { stream, stopStream } = useSSE()

  const isStreaming = computed(() => chat.streaming[key] ?? false)
  const streamDone = computed(() => chat.streamDone[key] ?? false)
  const content = computed(() => chat.content[key] ?? '')
  const renderedContent = computed(() => renderText(content.value))
  const followUpText = ref('')
  const analysisExpanded = ref(false)
  const conversationLog = ref<SSEMessage[]>([])

  const contextPct = computed(() => {
    const tokens = chat.inputTokens[key] ?? 0
    return tokens ? Math.round((tokens / CONTEXT_WINDOW_TOKENS) * 100) : null
  })

  /** "Analyzing…" while streaming, else `doneLabel` plus context usage. */
  function statusLine(doneLabel: string): string {
    if (isStreaming.value) return 'Analyzing…'
    return contextPct.value === null ? doneLabel : `${doneLabel} · ctx ${contextPct.value}%`
  }

  /** Drop the follow-up draft and any stream in flight. */
  function reset() {
    followUpText.value = ''
    analysisExpanded.value = false
    stopStream(key)
  }

  /** Start a fresh conversation with `prompt`. */
  function begin(prompt: string) {
    const initial: SSEMessage = { role: 'user', content: prompt }
    conversationLog.value = [initial]
    stream(key, [initial], options())
  }

  function sendFollowUp() {
    const text = followUpText.value.trim()
    if (!text || isStreaming.value) return
    followUpText.value = ''
    analysisExpanded.value = false
    const messages: SSEMessage[] = [
      ...conversationLog.value,
      { role: 'assistant', content: content.value },
      { role: 'user', content: text },
    ]
    conversationLog.value = messages
    stream(key, messages, options())
  }

  return {
    isStreaming, streamDone, content, renderedContent,
    followUpText, analysisExpanded, conversationLog, contextPct,
    statusLine, reset, begin, sendFollowUp,
    ...useVerdict(key),
  }
}
