import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface SpecialistInfo {
  status: string   // 'running' | 'Normal' | 'Anomaly Detected' | 'Fault Detected' | 'Unknown'
  confidence: number | null
  done: boolean
}

export const useChatStore = defineStore('chat', () => {
  const content    = ref<Record<string, string>>({})
  const streaming  = ref<Record<string, boolean>>({})
  const streamDone = ref<Record<string, boolean>>({})
  const specialists = ref<Record<string, Record<string, SpecialistInfo>>>({})
  const inputTokens = ref<Record<string, number>>({})

  function appendToken(key: string, token: string) {
    content.value[key] = (content.value[key] ?? '') + token
  }

  function startStream(key: string) {
    content.value[key] = ''
    streaming.value[key] = true
    streamDone.value[key] = false
    specialists.value[key] = {}
    inputTokens.value[key] = 0
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
  }

  function updateSpecialist(key: string, name: string, info: SpecialistInfo) {
    if (!specialists.value[key]) specialists.value[key] = {}
    specialists.value[key]![name] = info
  }

  function setInputTokens(key: string, tokens: number) {
    inputTokens.value[key] = tokens
  }

  return {
    content, streaming, streamDone, specialists, inputTokens,
    appendToken, startStream, finishStream, clearContent,
    updateSpecialist, setInputTokens,
  }
})
