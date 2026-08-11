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
  region:     'Provide a status summary for every plant in the Metro Region. Check each site individually and report current operational status, any alarms, and recommended actions per site.',
  enterprise: 'Provide an enterprise-wide status overview across every registered plant. Check each site individually and report current operational status, any alarms, and recommended actions per site.',
}

const ui = useUIStore()
const chat = useChatStore()
const { stream, stopStream } = useSSE()

const KEY = 'plant'
const panelTop = ref(0)
const panelLeft = ref(0)
const panelMaxHeight = ref(600)

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

// Region/Enterprise breadcrumb levels are cross-plant questions — answered by
// the enterprise orchestrator (diagnose_plant fan-out), never this plant's
// own single/multi-agent loop, regardless of the Multi-Agent toggle.
const chatMode = computed<'single' | 'multi' | 'enterprise'>(() => {
  if (crumbLevel.value === 'region' || crumbLevel.value === 'enterprise') return 'enterprise'
  return ui.multiAgent ? 'multi' : 'single'
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
const analysisExpanded = ref(false)
type Message = { role: 'user' | 'assistant'; content: string }
const conversationLog = ref<Message[]>([])

interface PlantSummary {
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
//
// \*{0,2} around each label tolerates the model bolding "Status:"/"Overview:"/
// "Key points:" (observed in practice — it isn't consistent about this), and
// the lazy value capture + trailing \*{0,2} strips a bolded value's closing
// ** without swallowing it into the next line. The optional \n? before "Key
// points:" tolerates an extra blank line before it, also observed in
// practice. Without these, a match failure silently falls through to the
// raw full-text branch instead of the summary card — worse than a stray
// residual ** would be.
const SUMMARY_RE = /SUMMARY:\s*\n\*{0,2}Status:\*{0,2}\s*([^\n]+?)\*{0,2}\n\*{0,2}Overview:\*{0,2}\s*([^\n]+?)\*{0,2}\n(?:\n?\*{0,2}Key points:\*{0,2}\s*\n([\s\S]+?))?(?:\n\n|$)/i

// Deliberately not gated on streamDone — the model is instructed to lead
// with SUMMARY before the detailed breakdown, so this pattern is usually
// fully matchable within seconds of the model starting to write (right
// after any tool calls resolve), well before the whole response finishes.
// Matching as soon as it's parseable means the panel goes straight from
// skeleton to summary card like every other panel, instead of showing the
// raw response mid-stream and then visibly collapsing into the card once
// done.
const summaryMatch = computed(() => {
  return content.value.match(SUMMARY_RE)
})

const summary = computed((): PlantSummary | null => {
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

function positionPanel() {
  const canvas = document.getElementById('topo-canvas')
  if (!canvas) return
  const panelW = 380
  const panelH = 360
  panelLeft.value = canvas.offsetWidth / 2 - panelW / 2
  panelTop.value = canvas.offsetHeight / 2 - panelH / 2
  // maxHeight is canvas-relative: panel must not extend past canvas bottom
  panelMaxHeight.value = canvas.offsetHeight - panelTop.value - 20
}

watch(() => ui.activePanel, async (panel, prev) => {
  if (panel !== 'plant') return
  if (prev !== 'plant') {
    followUpText.value = ''
    analysisExpanded.value = false
    stopStream(KEY)
  }
  await nextTick()
  positionPanel()
  const msgContent = PROMPTS[crumbLevel.value ?? 'plant'] ?? 'Provide a status summary of the Waterworks treatment plant.'
  const initial: Message = { role: 'user', content: msgContent }
  conversationLog.value = [initial]
  stream(KEY, [initial], { mode: chatMode.value })
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
  stream(KEY, messages, { mode: chatMode.value })
}
</script>

<template>
  <div
    id="plant-panel"
    class="plant-panel"
    :class="{ visible }"
    :style="{ top: `${panelTop}px`, left: `${panelLeft}px`, maxHeight: `${panelMaxHeight}px` }"
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
    <div class="panel-scroll">
      <!-- Analyzing skeleton — shown until a SUMMARY block is parseable, not
           until the whole response finishes. Region/Enterprise turns fan
           out across multiple plants and can take minutes, but the model
           leads with SUMMARY before the detailed breakdown, so this
           usually resolves within seconds of the model starting to write
           (right after any tool calls resolve) — the panel goes straight
           to the card, same as every other panel, never showing the raw
           in-progress response. -->
      <div v-if="isStreaming && !summary" class="panel-analyzing">
        <div class="skeleton-line" style="width: 82%" />
        <div class="skeleton-line" style="width: 67%" />
        <div class="skeleton-line" style="width: 91%" />
        <div class="skeleton-line" style="width: 55%" />
      </div>

      <!-- Summary card: shown as soon as SUMMARY is parseable, streaming or not -->
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
        <div v-if="analysisExpanded" class="plant-panel-body" v-html="renderText(analysisText)" />
      </template>

      <!-- Full text for general conversation / no SUMMARY -->
      <template v-else>
        <div
          class="plant-panel-body"
          :class="{ 'body-preview': streamDone && !analysisExpanded }"
          v-html="renderedContent"
        />
        <button v-if="streamDone" class="expand-btn" @click.stop="analysisExpanded = !analysisExpanded">
          {{ analysisExpanded ? 'Hide analysis ↑' : 'Full analysis ↓' }}
        </button>
      </template>
    </div>
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

.panel-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
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
}

.panel-analyzing {
  padding: 16px 18px;
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
  padding: 14px 18px;
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
  line-height: 1.6;
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
  max-height: 200px;
  overflow: hidden;
  mask-image: linear-gradient(to bottom, black 50%, transparent 100%);
  -webkit-mask-image: linear-gradient(to bottom, black 50%, transparent 100%);
}

.expand-btn {
  background: transparent;
  border: none;
  padding: 0 18px 12px;
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
