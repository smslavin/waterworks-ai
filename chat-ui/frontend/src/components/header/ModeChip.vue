<script setup lang="ts">
import { computed } from 'vue'
import { useUIStore } from '@/stores/ui'

const ui = useUIStore()
const label = computed(() => ui.multiAgent ? 'Multi Agent' : 'Single Agent')
</script>

<template>
  <button
    class="mode-chip"
    :class="{ active: ui.multiAgent }"
    :title="ui.multiAgent ? 'Switch to single agent' : 'Switch to multi agent'"
    @click.stop="ui.toggleMultiAgent()"
  >
    <span class="chip-dot" />
    {{ label }}
  </button>
</template>

<style scoped>
.mode-chip {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text2);
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
  white-space: nowrap;
}

.mode-chip.active {
  border-color: var(--color-accent);
  color: var(--color-accent);
  background: rgba(59, 130, 246, 0.08);
}

.chip-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}
</style>
