<script setup lang="ts">
import { computed, watch, nextTick, ref } from 'vue'
import { useUIStore } from '@/stores/ui'
import { useChatStore } from '@/stores/chat'
import { useSSE } from '@/composables/useSSE'
import { renderText } from '@/utils/renderText'
import SpecialistBadges from './SpecialistBadges.vue'

const ui = useUIStore()
const chat = useChatStore()
const { stream, stopStream } = useSSE()

const KEY = 'area'
const panelTop = ref(0)
const panelLeft = ref(0)

const visible = computed(() => ui.activePanel === 'area')
const isStreaming = computed(() => chat.streaming[KEY] ?? false)
const streamDone = computed(() => chat.streamDone[KEY] ?? false)
const content = computed(() => chat.content[KEY] ?? '')
const renderedContent = computed(() => renderText(content.value))
const tokenCount = computed(() => chat.inputTokens[KEY] ?? 0)
const statusText = computed(() => {
  if (isStreaming.value) return 'Analyzing…'
  const base = `${ui.activeArea} area · complete`
  return tokenCount.value ? `${base} · ctx ${Math.round(tokenCount.value / 2000)}%` : base
})

const followUpText = ref('')
type Message = { role: 'user' | 'assistant'; content: string }
const conversationLog = ref<Message[]>([])

function positionPanel(area: string) {
  const canvas = document.getElementById('topo-canvas')
  const labelEl = document.querySelector<HTMLElement>(`.topo-column[data-area="${area}"] .topo-column-label`)
  if (!canvas || !labelEl) return

  const cr = canvas.getBoundingClientRect()
  const lr = labelEl.getBoundingClientRect()

  const panelW = 300
  let left = lr.left - cr.left + lr.width / 2 - panelW / 2
  left = Math.max(8, Math.min(left, cr.width - panelW - 8))
  panelTop.value = lr.bottom - cr.top + 12
  panelLeft.value = left
}

watch(() => ui.activeArea, async (area, oldArea) => {
  if (!area) return
  if (oldArea !== area) {
    followUpText.value = ''
    stopStream(KEY)
  }

  await nextTick()
  positionPanel(area)
  const msgContent = `Analyze the ${area} process area of the Waterworks plant. Use available tools to check all equipment in this area and provide a status summary including any alarms or anomalies.`
  const initial: Message = { role: 'user', content: msgContent }
  conversationLog.value = [initial]
  stream(KEY, [initial], { mode: ui.multiAgent ? 'multi' : 'single' })
})

function sendFollowUp() {
  const text = followUpText.value.trim()
  if (!text || isStreaming.value) return
  followUpText.value = ''
  const messages: Message[] = [
    ...conversationLog.value,
    { role: 'assistant', content: content.value },
    { role: 'user', content: text },
  ]
  conversationLog.value = messages
  stream(KEY, messages, { mode: ui.multiAgent ? 'multi' : 'single' })
}
</script>

<template>
  <div
    id="area-panel"
    class="area-panel"
    :class="{ visible }"
    :style="{ top: `${panelTop}px`, left: `${panelLeft}px` }"
    @click.stop
  >
    <div class="area-panel-header">
      <span class="area-panel-badge">Process Area</span>
      <span class="area-panel-title">{{ ui.activeArea }}</span>
      <div class="area-panel-status" :class="{ streaming: isStreaming, done: streamDone }">
        <span class="area-status-dot" />
        <span>{{ statusText }}</span>
      </div>
    </div>
    <SpecialistBadges :stream-key="KEY" />
    <div class="area-panel-body" v-html="renderedContent" />
    <div class="area-panel-footer">
      <input
        v-model="followUpText"
        class="panel-input"
        placeholder="Ask a follow-up…"
        :disabled="isStreaming"
        @click.stop
        @keydown.enter.prevent="sendFollowUp"
      />
      <button
        class="panel-send"
        :disabled="isStreaming || !followUpText.trim()"
        @click.stop="sendFollowUp"
      >Ask</button>
    </div>
  </div>
</template>

<style scoped>
.area-panel {
  position: absolute;
  width: 300px;
  background: var(--color-bg2);
  border: 1px solid var(--color-border);
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  z-index: 50;
  overflow: hidden;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.18s;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
}

.area-panel.visible {
  opacity: 1;
  pointer-events: all;
}

.area-panel-header {
  padding: 12px 14px 10px;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.area-panel-badge {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--color-text2);
}

.area-panel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text1);
}

.area-panel-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--color-text2);
}

.area-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-border);
}

.area-panel-status.streaming .area-status-dot {
  background: var(--color-accent);
  animation: blink 1s step-end infinite;
}

.area-panel-status.done .area-status-dot {
  background: var(--color-ok);
}

.area-panel-body {
  padding: 12px 14px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--color-text1);
  max-height: 220px;
  overflow-y: auto;
}

.area-panel-body :deep(strong) {
  font-weight: 600;
}

.area-panel-footer {
  padding: 10px 12px;
  border-top: 1px solid var(--color-border);
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.panel-input {
  flex: 1;
  background: var(--color-bg3);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 12px;
  color: var(--color-text1);
  outline: none;
}

.panel-input:focus {
  border-color: var(--color-accent);
}

.panel-send {
  padding: 6px 12px;
  background: var(--color-accent);
  border: none;
  border-radius: 6px;
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s;
}

.panel-send:hover:not(:disabled) {
  opacity: 0.85;
}

.panel-send:disabled {
  opacity: 0.35;
  cursor: default;
}
</style>
