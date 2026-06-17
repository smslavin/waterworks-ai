<script setup lang="ts">
import { computed, watch, nextTick } from 'vue'
import { useUIStore } from '@/stores/ui'
import { useTopologyStore } from '@/stores/topology'
import { useChatStore } from '@/stores/chat'
import { useNodePanel } from '@/composables/useNodePanel'
import { useStreaming } from '@/composables/useStreaming'
import { NODE_RESPONSES } from '@/data/responses'
import { renderText } from '@/utils/renderText'
import SaveInsight from './SaveInsight.vue'

const ui = useUIStore()
const topo = useTopologyStore()
const chat = useChatStore()
const { panelTop, panelLeft, arrowSide, positionPanel } = useNodePanel()
const { stream, stopStream } = useStreaming()

const KEY = 'node'

const activeNode = computed(() => ui.activeNodeId ? topo.nodeById(ui.activeNodeId) : null)
const visible = computed(() => ui.activePanel === 'node')
const isCritical = computed(() => activeNode.value?.alarmState === 'critical')
const isWarning = computed(() => activeNode.value?.alarmState === 'warning')
const isPendingApproval = computed(() => activeNode.value?.alarmState === 'pending-approval')

const badgeText = computed(() => {
  if (isPendingApproval.value) return 'Pending Approval'
  if (isCritical.value) return 'Critical'
  if (isWarning.value) return 'Warning'
  return activeNode.value?.specialist ?? ''
})

const isStreaming = computed(() => chat.streaming[KEY] ?? false)
const streamDone = computed(() => chat.streamDone[KEY] ?? false)
const content = computed(() => chat.content[KEY] ?? '')
const renderedContent = computed(() => renderText(content.value))
const statusText = computed(() =>
  isStreaming.value
    ? 'Analyzing…'
    : `${activeNode.value?.specialist ?? ''} · complete`
)

watch(() => ui.activeNodeId, async (newId, oldId) => {
  if (!newId) return

  if (oldId !== newId) stopStream(KEY)

  await nextTick()
  const nodeEl = document.querySelector<HTMLElement>(`[data-id="${newId}"]`)
  if (nodeEl) positionPanel(nodeEl)

  let responseKey = newId
  if (ui.postApprovalDecision) {
    responseKey = `${newId}_${ui.postApprovalDecision}`
    ui.postApprovalDecision = null
  }

  stream(KEY, NODE_RESPONSES[responseKey] ?? NODE_RESPONSES[newId] ?? 'No data available.')
})
</script>

<template>
  <div
    id="node-panel"
    class="float-panel"
    :class="{
      visible,
      'is-critical': isCritical,
      'is-warning': isWarning,
      'is-pending': isPendingApproval,
    }"
    :style="{ top: `${panelTop}px`, left: `${panelLeft}px` }"
    @click.stop
  >
    <div class="panel-arrow" :class="{ right: arrowSide === 'right' }" />

    <div class="panel-header">
      <span
        class="panel-badge"
        :class="{
          critical: isCritical,
          warning: isWarning,
          approval: isPendingApproval,
        }"
      >{{ badgeText }}</span>
      <span class="panel-title">{{ activeNode?.id }}</span>
      <div class="panel-status" :class="{ streaming: isStreaming, done: streamDone }">
        <span class="panel-status-dot" />
        <span class="panel-status-text">{{ statusText }}</span>
      </div>
    </div>

    <div class="panel-body" v-html="renderedContent" />

    <div class="panel-footer">
      <input class="panel-input" placeholder="Ask a follow-up…" @click.stop />
      <button class="panel-send">Ask</button>
      <SaveInsight
        v-if="activeNode"
        :node-id="activeNode.id"
        :stream-done="streamDone"
      />
    </div>
  </div>
</template>

<style scoped>
.float-panel {
  position: absolute;
  width: 340px;
  background: var(--color-bg2);
  border: 1px solid var(--color-border);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  z-index: 50;
  overflow: hidden;
  opacity: 0;
  pointer-events: none;
  visibility: hidden;
  transition: opacity 0.18s, visibility 0s 0.18s;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
}

.float-panel.visible {
  opacity: 1;
  pointer-events: all;
  visibility: visible;
  transition: opacity 0.18s, visibility 0s;
}

.float-panel.is-critical { border-color: var(--color-error); }
.float-panel.is-warning  { border-color: var(--color-warn); }
.float-panel.is-pending  { border-color: #a855f7; }

.panel-arrow {
  position: absolute;
  top: 50%;
  left: -7px;
  transform: translateY(-50%);
  width: 0;
  height: 0;
  border-top: 7px solid transparent;
  border-bottom: 7px solid transparent;
  border-right: 7px solid var(--color-border);
  pointer-events: none;
}

.panel-arrow.right {
  left: auto;
  right: -7px;
  border-right: none;
  border-left: 7px solid var(--color-border);
}

.panel-header {
  padding: 12px 16px 10px;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.panel-badge {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--color-text2);
}

.panel-badge.critical { color: var(--color-error); }
.panel-badge.warning  { color: var(--color-warn); }
.panel-badge.approval { color: #a855f7; }

.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text1);
  font-family: var(--font-mono);
}

.panel-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--color-text2);
}

.panel-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-border);
}

.panel-status.streaming .panel-status-dot {
  background: var(--color-accent);
  animation: blink 1s step-end infinite;
}

.panel-status.done .panel-status-dot {
  background: var(--color-ok);
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--color-text1);
  min-height: 100px;
  max-height: 240px;
}

.panel-body :deep(strong) {
  color: var(--color-text1);
  font-weight: 600;
}

.panel-footer {
  padding: 10px 12px;
  border-top: 1px solid var(--color-border);
  display: flex;
  align-items: flex-end;
  gap: 8px;
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

.panel-send:hover {
  opacity: 0.85;
}
</style>
