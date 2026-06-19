<script setup lang="ts">
import { computed, watch, nextTick, ref } from 'vue'
import { useUIStore } from '@/stores/ui'
import { useChatStore } from '@/stores/chat'
import { useSSE } from '@/composables/useSSE'
import { renderText } from '@/utils/renderText'
import SpecialistBadges from './SpecialistBadges.vue'

export type CrumbLevel = 'plant' | 'region' | 'enterprise'

const PROMPTS: Record<string, string> = {
  plant:      'Provide a high-level status summary of the Waterworks treatment plant. Use available tools to check all process areas (Intake, Treatment, Distribution) and report current status, any alarms, and recommended actions.',
  region:     'Provide a status summary for the Metro Region. Focus on the Waterworks plant, which has live telemetry, and summarize its current operational status.',
  enterprise: 'Provide an enterprise-level status overview. Use the Waterworks plant live data to report current operational health.',
}

const ui = useUIStore()
const chat = useChatStore()
const { stream, stopStream } = useSSE()

const KEY = 'plant'
const panelTop = ref(0)
const panelLeft = ref(0)

const visible = computed(() => ui.activePanel === 'plant')
const crumbLevel = computed(() => ui.crumbLevel)

const badgeText = computed(() => {
  const map: Record<string, string> = { plant: 'Plant', region: 'Region', enterprise: 'Enterprise' }
  return map[crumbLevel.value ?? 'plant'] ?? 'Plant'
})

const titleText = computed(() => {
  const map: Record<string, string> = {
    plant: 'Waterworks',
    region: 'Metro Region',
    enterprise: 'Enterprise',
  }
  return map[crumbLevel.value ?? 'plant'] ?? 'Waterworks'
})

const isStreaming = computed(() => chat.streaming[KEY] ?? false)
const streamDone = computed(() => chat.streamDone[KEY] ?? false)
const content = computed(() => chat.content[KEY] ?? '')
const renderedContent = computed(() => renderText(content.value))
const tokenCount = computed(() => chat.inputTokens[KEY] ?? 0)
const statusText = computed(() => {
  if (isStreaming.value) return 'Analyzing…'
  const base = `${titleText.value} · complete`
  return tokenCount.value ? `${base} · ctx ${Math.round(tokenCount.value / 2000)}%` : base
})

const followUpText = ref('')
type Message = { role: 'user' | 'assistant'; content: string }
const conversationLog = ref<Message[]>([])

function positionPanel() {
  const canvas = document.getElementById('topo-canvas')
  if (!canvas) return
  const panelW = 380
  const panelH = 360
  panelLeft.value = canvas.offsetWidth / 2 - panelW / 2
  panelTop.value = canvas.offsetHeight / 2 - panelH / 2
}

watch(() => ui.activePanel, async (panel, prev) => {
  if (panel !== 'plant') return
  if (prev !== 'plant') {
    followUpText.value = ''
    stopStream(KEY)
  }
  await nextTick()
  positionPanel()
  const msgContent = PROMPTS[crumbLevel.value ?? 'plant'] ?? 'Provide a status summary of the Waterworks treatment plant.'
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
    id="plant-panel"
    class="plant-panel"
    :class="{ visible }"
    :style="{ top: `${panelTop}px`, left: `${panelLeft}px` }"
    @click.stop
  >
    <div class="plant-panel-header">
      <span class="plant-panel-badge">{{ badgeText }}</span>
      <span class="plant-panel-title">{{ titleText }}</span>
      <div class="plant-panel-status" :class="{ streaming: isStreaming, done: streamDone }">
        <span class="plant-status-dot" />
        <span>{{ statusText }}</span>
      </div>
    </div>
    <SpecialistBadges :stream-key="KEY" />
    <div class="plant-panel-body" v-html="renderedContent" />
    <div class="plant-panel-footer">
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
.plant-panel {
  position: absolute;
  width: 380px;
  background: var(--color-bg2);
  border: 1px solid var(--color-border);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  z-index: 50;
  overflow: hidden;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.18s;
  box-shadow: 0 12px 48px rgba(0, 0, 0, 0.6);
}

.plant-panel.visible {
  opacity: 1;
  pointer-events: all;
}

.plant-panel-header {
  padding: 14px 18px 12px;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.plant-panel-badge {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--color-verified);
}

.plant-panel-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text1);
}

.plant-panel-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--color-text2);
}

.plant-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-border);
}

.plant-panel-status.streaming .plant-status-dot {
  background: var(--color-accent);
  animation: blink 1s step-end infinite;
}

.plant-panel-status.done .plant-status-dot {
  background: var(--color-ok);
}

.plant-panel-body {
  padding: 16px 18px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--color-text1);
  max-height: 280px;
  overflow-y: auto;
}

.plant-panel-body :deep(strong) {
  font-weight: 600;
}

.plant-panel-footer {
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
