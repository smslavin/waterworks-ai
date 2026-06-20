<script setup lang="ts">
import { useUIStore } from '@/stores/ui'
import type { Alarm } from '@/stores/alarm'

const props = defineProps<{ alarm: Alarm }>()
const emit = defineEmits<{ ack: [] }>()
const ui = useUIStore()
</script>

<template>
  <div class="alarm-row" :class="alarm.severity" @click.stop="ui.setActiveNode(props.alarm.nodeId)">
    <span class="alarm-badge" :class="alarm.severity">{{ alarm.severity }}</span>
    <span class="alarm-node">{{ alarm.nodeId }}</span>
    <span class="alarm-message">{{ alarm.message }}</span>
    <span class="alarm-timestamp">{{ alarm.timestamp }}</span>
    <button class="alarm-ack" @click.stop="emit('ack')">ACK</button>
  </div>
</template>

<style scoped>
.alarm-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 16px;
  height: 32px;
  border-bottom: 1px solid var(--color-border);
  width: 100%;
  box-sizing: border-box;
  cursor: pointer;
  transition: background 0.1s;
}

.alarm-row:hover {
  filter: brightness(1.25);
}

.alarm-row:last-child {
  border-bottom: none;
}

.alarm-row.critical {
  border-left: 3px solid var(--color-error);
  background: rgba(248, 113, 113, 0.08);
}
.alarm-row.warning {
  border-left: 3px solid var(--color-warn);
  background: rgba(251, 191, 36, 0.05);
}

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
  min-width: 100px;
}

.alarm-message {
  font-size: 11px;
  color: var(--color-text2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}

.alarm-timestamp {
  font-size: 10px;
  color: var(--color-text2);
  opacity: 0.6;
  flex-shrink: 0;
  white-space: nowrap;
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
