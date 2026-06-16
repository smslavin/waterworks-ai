<script setup lang="ts">
import { useUIStore } from '@/stores/ui'

const ui = useUIStore()

function onClick() {
  ui.toggleFlyout('notif')
}
</script>

<template>
  <button
    class="reactive-pill"
    :class="{ active: ui.reactiveOn, flyout: ui.activeFlyout === 'notif' }"
    :title="ui.reactiveOn ? 'Reactive monitoring on — click for alerts' : 'Reactive monitoring off'"
    @click.stop="onClick"
  >
    <span class="pill-dot" />
    <span class="pill-label">⚡ Reactive</span>
  </button>
</template>

<style scoped>
.reactive-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text2);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
}

.reactive-pill.active {
  border-color: var(--color-warn);
  color: var(--color-warn);
  animation: pill-pulse 2s ease-in-out infinite;
}

.reactive-pill.flyout {
  background: rgba(251, 191, 36, 0.1);
}

.pill-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}

.pill-label {
  white-space: nowrap;
}
</style>
