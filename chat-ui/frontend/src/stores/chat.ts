import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useChatStore = defineStore('chat', () => {
  const content = ref<Record<string, string>>({})
  const streaming = ref<Record<string, boolean>>({})
  const streamDone = ref<Record<string, boolean>>({})

  function appendToken(key: string, token: string) {
    content.value[key] = (content.value[key] ?? '') + token
  }

  function startStream(key: string) {
    content.value[key] = ''
    streaming.value[key] = true
    streamDone.value[key] = false
  }

  function finishStream(key: string) {
    streaming.value[key] = false
    streamDone.value[key] = true
  }

  function clearContent(key: string) {
    content.value[key] = ''
    streaming.value[key] = false
    streamDone.value[key] = false
  }

  return { content, streaming, streamDone, appendToken, startStream, finishStream, clearContent }
})
