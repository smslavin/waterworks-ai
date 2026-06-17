<script setup lang="ts">
import { computed } from 'vue'
import { useAlarmStore } from '@/stores/alarm'
import ApprovalPill from './ApprovalPill.vue'
import ModeChip from './ModeChip.vue'
import ReasoningChip from './ReasoningChip.vue'
import ConfigButton from './ConfigButton.vue'

const alarm = useAlarmStore()
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
        <svg class="site-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z" />
          <path d="M12 6v6l4 2" />
        </svg>
        Waterworks AI
      </span>
    </div>
    <div class="header-right">
      <div
        v-for="a in warningAlarms"
        :key="a.id"
        class="warning-pill"
        :title="a.message"
      >
        <span class="warning-dot" />
        <span class="warning-text">{{ a.nodeId }} · {{ shortMsg(a.message) }}</span>
      </div>
      <ApprovalPill />
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
  flex-shrink: 0;
  color: var(--color-verified);
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
