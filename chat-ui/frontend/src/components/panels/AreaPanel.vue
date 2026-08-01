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
const panelMaxHeight = ref(600)

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
const analysisExpanded = ref(false)
type Message = { role: 'user' | 'assistant'; content: string }
const conversationLog = ref<Message[]>([])

interface AreaSummary {
  status: string
  overview: string
  points: string[]
}

// SUMMARY is meant to lead the response (the model is instructed to state the
// conclusion before the detailed breakdown), but this isn't anchored to the
// start — if the model ever reverts to placing it at the end instead, "full
// analysis" still needs to show everything else, not go blank. Excising just
// the matched span (wherever it lands) rather than assuming a fixed position
// keeps that working either way.
const SUMMARY_RE = /SUMMARY:\s*\nStatus:\s*([^\n]+)\nOverview:\s*([^\n]+)\n(?:Key points:\n([\s\S]+?))?(?:\n\n|$)/i

const summaryMatch = computed(() => {
  if (!streamDone.value) return null
  return content.value.match(SUMMARY_RE)
})

const summary = computed((): AreaSummary | null => {
  const m = summaryMatch.value
  if (!m) return null
  const [, rawStatus, rawOverview, rawPoints] = m
  if (!rawStatus || !rawOverview) return null
  const points = (rawPoints ?? '')
    .split('\n')
    .filter(l => l.trimStart().startsWith('-'))
    .map(l => l.replace(/^\s*-\s*/, '').trim())
    .filter(Boolean)
  return { status: rawStatus.trim(), overview: rawOverview.trim(), points }
})

const analysisText = computed(() => {
  const m = summaryMatch.value
  if (!m || m.index === undefined) return content.value
  const before = content.value.slice(0, m.index)
  const after = content.value.slice(m.index + m[0].length)
  return (before + after).trim()
})

const summaryClass = computed(() => {
  switch (summary.value?.status) {
    case 'Normal':           return 'summary-normal'
    case 'Anomaly Detected': return 'summary-anomaly'
    case 'Fault Detected':   return 'summary-fault'
    default:                 return 'summary-unknown'
  }
})

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
  // maxHeight is canvas-relative: panel must not extend past canvas bottom
  panelMaxHeight.value = cr.height - panelTop.value - 20
}

watch(() => ui.activeArea, async (area, oldArea) => {
  if (!area) return
  if (oldArea !== area) {
    followUpText.value = ''
    analysisExpanded.value = false
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
  analysisExpanded.value = false
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
    :style="{ top: `${panelTop}px`, left: `${panelLeft}px`, maxHeight: `${panelMaxHeight}px` }"
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
    <div class="panel-scroll">
      <!-- Analyzing skeleton while streaming -->
      <div v-if="isStreaming" class="panel-analyzing">
        <div class="skeleton-line" style="width: 82%" />
        <div class="skeleton-line" style="width: 67%" />
        <div class="skeleton-line" style="width: 91%" />
        <div class="skeleton-line" style="width: 55%" />
      </div>

      <!-- Summary card: shown when stream done and SUMMARY parsed -->
      <template v-else-if="summary">
        <div class="summary-card" :class="summaryClass">
          <div class="summary-header">
            <span class="summary-status">{{ summary.status }}</span>
          </div>
          <p class="summary-overview">{{ summary.overview }}</p>
          <ul v-if="summary.points.length" class="summary-points">
            <li v-for="point in summary.points" :key="point">{{ point }}</li>
          </ul>
          <button class="expand-btn" @click.stop="analysisExpanded = !analysisExpanded">
            {{ analysisExpanded ? 'Hide analysis ↑' : 'Full analysis ↓' }}
          </button>
        </div>
        <div v-if="analysisExpanded" class="area-panel-body" v-html="renderText(analysisText)" />
      </template>

      <!-- Full text for general conversation / no SUMMARY -->
      <template v-else>
        <div
          class="area-panel-body"
          :class="{ 'body-preview': streamDone && !analysisExpanded }"
          v-html="renderedContent"
        />
        <button v-if="streamDone" class="expand-btn" @click.stop="analysisExpanded = !analysisExpanded">
          {{ analysisExpanded ? 'Hide analysis ↑' : 'Full analysis ↓' }}
        </button>
      </template>
    </div>
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
  max-height: calc(100vh - 80px);
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

.panel-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
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
}

.panel-analyzing {
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.skeleton-line {
  height: 10px;
  border-radius: 4px;
  background: var(--color-bg3);
  animation: skeleton-pulse 1.4s ease-in-out infinite;
}

.skeleton-line:nth-child(2) { animation-delay: 0.15s; }
.skeleton-line:nth-child(3) { animation-delay: 0.3s; }
.skeleton-line:nth-child(4) { animation-delay: 0.45s; }

@keyframes skeleton-pulse {
  0%, 100% { opacity: 0.35; }
  50%       { opacity: 0.7; }
}

.summary-card {
  padding: 12px 14px;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-left: 3px solid transparent;
}

.summary-normal  { border-left-color: var(--color-ok); }
.summary-anomaly { border-left-color: var(--color-warn); }
.summary-fault   { border-left-color: var(--color-error); }
.summary-unknown { border-left-color: var(--color-border); }

.summary-header {
  display: flex;
  align-items: baseline;
}

.summary-status {
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.summary-normal  .summary-status { color: var(--color-ok); }
.summary-anomaly .summary-status { color: var(--color-warn); }
.summary-fault   .summary-status { color: var(--color-error); }
.summary-unknown .summary-status { color: var(--color-text2); }

.summary-overview {
  font-size: 13px;
  line-height: 1.5;
  color: var(--color-text1);
  margin: 0;
}

.summary-points {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.summary-points li {
  font-size: 12px;
  line-height: 1.5;
  color: var(--color-text1);
  padding-left: 12px;
  position: relative;
}

.summary-points li::before {
  content: '·';
  position: absolute;
  left: 0;
  color: var(--color-text2);
}

.body-preview {
  max-height: 180px;
  overflow: hidden;
  mask-image: linear-gradient(to bottom, black 50%, transparent 100%);
  -webkit-mask-image: linear-gradient(to bottom, black 50%, transparent 100%);
}

.expand-btn {
  background: transparent;
  border: none;
  padding: 0 14px 10px;
  font-size: 11px;
  font-weight: 600;
  color: var(--color-accent);
  cursor: pointer;
  text-align: left;
  transition: opacity 0.12s;
}

.expand-btn:hover {
  opacity: 0.75;
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
