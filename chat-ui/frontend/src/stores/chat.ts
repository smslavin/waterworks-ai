import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface SpecialistInfo {
  status: string   // 'running' | 'Normal' | 'Anomaly Detected' | 'Fault Detected' | 'Unknown'
  confidence: number | null
  done: boolean
}

/** A FINDINGS or SUMMARY block, parsed once by the backend (chat-ui/verdict.py)
 *  and sent as a "verdict" SSE event. `block` is the exact text it came from. */
export interface Verdict {
  kind: 'summary' | 'findings'
  status: string
  confidence: number | null
  overview: string | null
  points: string[]
  block: string
}

export const useChatStore = defineStore('chat', () => {
  const content    = ref<Record<string, string>>({})
  const streaming  = ref<Record<string, boolean>>({})
  const streamDone = ref<Record<string, boolean>>({})
  const specialists = ref<Record<string, Record<string, SpecialistInfo>>>({})
  const inputTokens = ref<Record<string, number>>({})
  const verdict = ref<Record<string, Verdict | null>>({})

  function appendToken(key: string, token: string) {
    content.value[key] = (content.value[key] ?? '') + token
  }

  function startStream(key: string) {
    content.value[key] = ''
    streaming.value[key] = true
    streamDone.value[key] = false
    specialists.value[key] = {}
    inputTokens.value[key] = 0
    verdict.value[key] = null
  }

  function finishStream(key: string) {
    streaming.value[key] = false
    streamDone.value[key] = true
  }

  function clearContent(key: string) {
    content.value[key] = ''
    streaming.value[key] = false
    streamDone.value[key] = false
    specialists.value[key] = {}
    inputTokens.value[key] = 0
    verdict.value[key] = null
  }

  function setVerdict(key: string, v: Verdict) {
    verdict.value[key] = v
  }

  function updateSpecialist(key: string, name: string, info: SpecialistInfo) {
    if (!specialists.value[key]) specialists.value[key] = {}
    specialists.value[key]![name] = info
  }

  function setInputTokens(key: string, tokens: number) {
    inputTokens.value[key] = tokens
  }

  return {
    content, streaming, streamDone, specialists, inputTokens, verdict,
    appendToken, startStream, finishStream, clearContent,
    updateSpecialist, setInputTokens, setVerdict,
  }
})
