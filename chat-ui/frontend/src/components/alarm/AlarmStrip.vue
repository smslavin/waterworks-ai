<script setup lang="ts">
import { computed } from 'vue'
import { useAlarmStore } from '@/stores/alarm'
import AlarmRow from './AlarmRow.vue'

const alarm = useAlarmStore()
const hasAlarms = computed(() => alarm.alarms.length > 0)
</script>

<template>
  <div v-if="hasAlarms" class="alarm-strip">
    <TransitionGroup name="alarm" tag="div" class="alarm-list">
      <AlarmRow
        v-for="a in alarm.alarms"
        :key="a.id"
        :alarm="a"
        @ack="alarm.acknowledge(a.id)"
      />
    </TransitionGroup>
  </div>
</template>

<style scoped>
.alarm-strip {
  background: var(--color-bg);
  border-bottom: 1px solid var(--color-border);
  overflow-x: auto;
  flex-shrink: 0;
}

.alarm-list {
  display: flex;
  flex-direction: row;
}

.alarm-enter-active,
.alarm-leave-active {
  transition: opacity 0.2s, max-width 0.25s;
  overflow: hidden;
}

.alarm-enter-from,
.alarm-leave-to {
  opacity: 0;
  max-width: 0;
}

.alarm-enter-to,
.alarm-leave-from {
  max-width: 400px;
}
</style>
