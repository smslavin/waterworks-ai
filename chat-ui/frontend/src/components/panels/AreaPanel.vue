<script setup lang="ts">
import { computed, watch, nextTick, ref } from 'vue'
import { useUIStore } from '@/stores/ui'
import { useChatStore } from '@/stores/chat'
import { useStreaming } from '@/composables/useStreaming'
import { AREA_RESPONSES } from '@/data/responses'
import { renderText } from '@/utils/renderText'

const ui = useUIStore()
const chat = useChatStore()
const { stream, stopStream } = useStreaming()

const KEY = 'area'
const panelTop = ref(0)
const panelLeft = ref(0)

const visible = computed(() => ui.activePanel === 'area')
const isStreaming = computed(() => chat.streaming[KEY] ?? false)
const streamDone = computed(() => chat.streamDone[KEY] ?? false)
const content = computed(() => chat.content[KEY] ?? '')
const renderedContent = computed(() => renderText(content.value))
const statusText = computed(() => isStreaming.value ? 'Analyzing…' : `${ui.activeArea} area · complete`)

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
  if (oldArea !== area) stopStream(KEY)

  await nextTick()
  positionPanel(area)
  stream(KEY, AREA_RESPONSES[area] ?? 'No data available.')
})
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
    <div class="area-panel-body" v-html="renderedContent" />
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
</style>
