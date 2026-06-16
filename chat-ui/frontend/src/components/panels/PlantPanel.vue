<script setup lang="ts">
import { computed, watch, nextTick, ref } from 'vue'
import { useUIStore } from '@/stores/ui'
import { useChatStore } from '@/stores/chat'
import { useStreaming } from '@/composables/useStreaming'
import { CRUMB_RESPONSES } from '@/data/responses'
import { renderText } from '@/utils/renderText'

export type CrumbLevel = 'plant' | 'region' | 'enterprise'

const ui = useUIStore()
const chat = useChatStore()
const { stream, stopStream } = useStreaming()

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
const statusText = computed(() => isStreaming.value ? 'Analyzing…' : `${titleText.value} · complete`)

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
  if (prev !== 'plant') stopStream(KEY)
  await nextTick()
  positionPanel()
  stream(KEY, CRUMB_RESPONSES[crumbLevel.value ?? 'plant'] ?? 'No data available.')
})
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
    <div class="plant-panel-body" v-html="renderedContent" />
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
</style>
