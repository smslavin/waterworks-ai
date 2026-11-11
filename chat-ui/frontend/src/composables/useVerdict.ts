import { computed } from 'vue'
import { useChatStore } from '@/stores/chat'

const STATUS_KEYS: Record<string, string> = {
  'Normal': 'normal',
  'Anomaly Detected': 'anomaly',
  'Fault Detected': 'fault',
}

/** The verdict for a panel's stream, and its text with the block taken out.
 *
 *  The backend parses the FINDINGS/SUMMARY block once and sends it as a
 *  "verdict" event (chat-ui/verdict.py). Each panel used to run its own regex
 *  over the text, and they had drifted apart (gh-25). */
export function useVerdict(key: string) {
  const chat = useChatStore()

  const verdict = computed(() => chat.verdict[key] ?? null)

  /** Everything but the block, wherever in the response it landed. */
  const analysisText = computed(() => {
    const content = chat.content[key] ?? ''
    const block = verdict.value?.block
    if (!block) return content
    const i = content.lastIndexOf(block)
    if (i < 0) return content
    return (content.slice(0, i) + content.slice(i + block.length)).trim()
  })

  /** 'normal' | 'anomaly' | 'fault' | 'unknown', for CSS class suffixes. */
  const statusKey = computed(() => STATUS_KEYS[verdict.value?.status ?? ''] ?? 'unknown')

  return { verdict, analysisText, statusKey }
}
