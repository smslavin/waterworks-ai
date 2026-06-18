<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'
import { useUIStore } from '@/stores/ui'
import { useTopologyStore } from '@/stores/topology'
import { useChatStore } from '@/stores/chat'
import { useNodePanel } from '@/composables/useNodePanel'
import { useSSE } from '@/composables/useSSE'
import { renderText } from '@/utils/renderText'
import SaveInsight from './SaveInsight.vue'

const ui = useUIStore()
const topo = useTopologyStore()
const chat = useChatStore()
const { panelTop, panelLeft, arrowSide, positionPanel } = useNodePanel()
const { stream, stopStream } = useSSE()

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
const hasSaved = computed(() => (activeNode.value?.saveCount ?? 0) > 0)

const classifyOpen = ref(false)
const followUpText = ref('')

type Message = { role: 'user' | 'assistant'; content: string }
const conversationLog = ref<Message[]>([])

const statusText = computed(() =>
  isStreaming.value
    ? 'Analyzing…'
    : `${activeNode.value?.specialist ?? ''} · complete`
)

watch(() => ui.activeNodeId, async (newId) => {
  if (!newId) return

  classifyOpen.value = false
  followUpText.value = ''
  stopStream(KEY)

  await nextTick()
  const nodeEl = document.querySelector<HTMLElement>(`[data-id="${newId}"]`)
  if (nodeEl) positionPanel(nodeEl)

  const node = topo.nodeById(newId)
  if (!node) return

  let msgContent = `Please diagnose ${node.id} (${node.equipmentType}) in the ${node.area} area. Use available tools to check current readings and identify any issues.`

  if (ui.postApprovalDecision) {
    const decision = ui.postApprovalDecision
    ui.postApprovalDecision = null
    msgContent = `The operator ${decision}d the proposed action for ${node.id}. Please continue your assessment.`
  }

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

    <SaveInsight
      v-if="activeNode"
      :node-id="activeNode.id"
      :stream-done="streamDone"
      v-model:open="classifyOpen"
    />

    <div class="panel-footer">
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
      <button
        v-if="activeNode"
        class="save-bookmark-btn"
        :class="{
          active: streamDone && !hasSaved,
          classifying: classifyOpen,
          saved: hasSaved,
        }"
        :disabled="!streamDone && !hasSaved"
        :title="hasSaved
          ? `${activeNode?.saveCount ?? 0} saved insight${(activeNode?.saveCount ?? 0) > 1 ? 's' : ''}`
          : 'Save insight'"
        @click.stop="classifyOpen = !classifyOpen"
      >
        <span>🔖</span>
        <span v-if="hasSaved" class="save-badge">{{ activeNode?.saveCount }}</span>
      </button>
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

.panel-body :deep(p) {
  margin-bottom: 0.55em;
}
.panel-body :deep(p:last-child) {
  margin-bottom: 0;
}
.panel-body :deep(strong) {
  color: var(--color-text1);
  font-weight: 600;
}
.panel-body :deep(em) {
  font-style: italic;
}
.panel-body :deep(h1),
.panel-body :deep(h2),
.panel-body :deep(h3),
.panel-body :deep(h4) {
  font-weight: 600;
  color: var(--color-text1);
  line-height: 1.3;
  margin: 0.6em 0 0.25em;
}
.panel-body :deep(h1) { font-size: 1.05em; }
.panel-body :deep(h2) { font-size: 0.97em; }
.panel-body :deep(h3) { font-size: 0.9em; letter-spacing: 0.01em; }
.panel-body :deep(h4) { font-size: 0.87em; color: var(--color-text2); }
.panel-body :deep(code) {
  font-family: var(--font-mono);
  font-size: 11px;
  background: var(--color-bg3);
  padding: 1px 5px;
  border-radius: 4px;
}
.panel-body :deep(pre) {
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 10px 12px;
  overflow-x: auto;
  margin: 6px 0;
}
.panel-body :deep(pre code) {
  background: none;
  padding: 0;
  font-size: 11px;
}
.panel-body :deep(ul),
.panel-body :deep(ol) {
  padding-left: 1.3em;
  margin: 0.3em 0;
}
.panel-body :deep(li) {
  margin-bottom: 0.2em;
}
.panel-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 6px 0;
  font-size: 12px;
}
.panel-body :deep(th),
.panel-body :deep(td) {
  border: 1px solid var(--color-border);
  padding: 4px 8px;
  text-align: left;
}
.panel-body :deep(th) {
  background: var(--color-bg3);
  font-weight: 600;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text2);
}
.panel-body :deep(blockquote) {
  border-left: 3px solid var(--color-border);
  margin: 6px 0;
  padding: 4px 10px;
  color: var(--color-text2);
  font-size: 12px;
}
.panel-body :deep(hr) {
  border: none;
  border-top: 1px solid var(--color-border);
  margin: 8px 0;
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

.panel-send:hover:not(:disabled) {
  opacity: 0.85;
}

.panel-send:disabled {
  opacity: 0.35;
  cursor: default;
}

.save-bookmark-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  background: transparent;
  border: none;
  font-size: 14px;
  cursor: pointer;
  opacity: 0.35;
  transition: opacity 0.15s;
  flex-shrink: 0;
}

.save-bookmark-btn.active,
.save-bookmark-btn.saved {
  opacity: 1;
}

.save-bookmark-btn.classifying {
  opacity: 1;
}

.save-bookmark-btn:disabled {
  cursor: default;
}

.save-badge {
  font-size: 10px;
  font-weight: 700;
  background: var(--color-verified);
  color: #000;
  border-radius: 999px;
  padding: 1px 5px;
  line-height: 1.4;
}
</style>
