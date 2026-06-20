<script setup lang="ts">
import { computed } from 'vue'
import { useAlarmStore } from '@/stores/alarm'
import { useApprovalStore } from '@/stores/approval'
import { useUIStore } from '@/stores/ui'
import ApprovalPill from './ApprovalPill.vue'
import ModeChip from './ModeChip.vue'
import ReasoningChip from './ReasoningChip.vue'
import ConfigButton from './ConfigButton.vue'

const ui = useUIStore()
const alarm = useAlarmStore()
const approval = useApprovalStore()
const warningAlarms = computed(() => alarm.alarms.filter(a => a.severity === 'warning'))

function shortMsg(msg: string): string {
  const before = msg.split(' — ').at(0) ?? msg
  return before.length > 22 ? before.slice(0, 22) + '…' : before
}
</script>

<template>
  <header class="app-header">
    <div class="header-left">
      <span class="site-name">
        <img src="@/assets/icon-dark.png" class="site-icon" alt="" />
        Waterworks AI
      </span>
    </div>
    <div class="header-right">
      <div
        v-for="a in warningAlarms"
        :key="a.id"
        class="warning-pill"
        :title="a.message"
        role="button"
        @click="ui.setActiveNode(a.nodeId)"
      >
        <span class="warning-dot" />
        <span class="warning-text">{{ a.nodeId }} · {{ shortMsg(a.message) }}</span>
      </div>
      <ApprovalPill v-if="approval.hasPending" />
      <div class="header-divider" />
      <ModeChip />
      <ReasoningChip />
      <ConfigButton />
    </div>
  </header>
</template>

<style scoped>
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 44px;
  padding: 0 16px;
  background: var(--color-bg2);
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
  z-index: 60;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.site-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-verified);
}

.site-icon {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  object-fit: contain;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.warning-pill {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 3px 9px;
  border-radius: 999px;
  border: 1px solid rgba(251, 191, 36, 0.4);
  background: rgba(251, 191, 36, 0.08);
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
}

.warning-pill:hover {
  background: rgba(251, 191, 36, 0.16);
  border-color: rgba(251, 191, 36, 0.7);
}

.warning-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-warn);
  flex-shrink: 0;
  animation: warning-blink 2s step-end infinite;
}

.warning-text {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-warn);
  white-space: nowrap;
}

@keyframes warning-blink {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.4; }
}

.header-divider {
  width: 1px;
  height: 18px;
  background: var(--color-border);
  margin: 0 4px;
}
</style>
