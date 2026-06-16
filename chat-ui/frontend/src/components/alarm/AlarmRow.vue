<script setup lang="ts">
import type { Alarm } from '@/stores/alarm'

defineProps<{ alarm: Alarm }>()
const emit = defineEmits<{ ack: [] }>()
</script>

<template>
  <div class="alarm-row" :class="alarm.severity">
    <span class="alarm-badge" :class="alarm.severity">{{ alarm.severity }}</span>
    <span class="alarm-node">{{ alarm.nodeId }}</span>
    <span class="alarm-message">{{ alarm.message }}</span>
    <button class="alarm-ack" @click.stop="emit('ack')">ACK</button>
  </div>
</template>

<style scoped>
.alarm-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
  height: 32px;
  border-right: 1px solid var(--color-border);
  flex-shrink: 0;
}

.alarm-row.critical { border-left: 2px solid var(--color-error); }
.alarm-row.warning  { border-left: 2px solid var(--color-warn); }

.alarm-badge {
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 1px 6px;
  border-radius: 3px;
  flex-shrink: 0;
}

.alarm-badge.critical {
  background: rgba(248, 113, 113, 0.2);
  color: var(--color-error);
  animation: alarm-blink 1.2s step-end infinite;
}

.alarm-badge.warning {
  background: rgba(251, 191, 36, 0.15);
  color: var(--color-warn);
}

.alarm-node {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-text1);
  flex-shrink: 0;
}

.alarm-message {
  font-size: 11px;
  color: var(--color-text2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}

.alarm-ack {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.08em;
  padding: 2px 7px;
  border-radius: 3px;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text2);
  cursor: pointer;
  flex-shrink: 0;
  transition: border-color 0.12s, color 0.12s;
}

.alarm-ack:hover {
  border-color: var(--color-ok);
  color: var(--color-ok);
}
</style>
