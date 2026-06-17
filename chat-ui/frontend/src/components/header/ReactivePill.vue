<script setup lang="ts">
import { useUIStore } from '@/stores/ui'

const ui = useUIStore()
</script>

<template>
  <div
    v-if="ui.reactiveOn"
    class="reactive-indicator"
    title="Reactive monitoring active"
  >
    <span class="indicator-dot" />
    <span class="indicator-label">Reactive</span>
  </div>
</template>

<style scoped>
.reactive-indicator {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border-radius: 4px;
  background: rgba(251, 191, 36, 0.1);
  border: 1px solid rgba(251, 191, 36, 0.3);
}

.indicator-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-warn);
  flex-shrink: 0;
  animation: reactive-blink 1.6s step-end infinite;
}

.indicator-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--color-warn);
  white-space: nowrap;
}

@keyframes reactive-blink {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.3; }
}
</style>
