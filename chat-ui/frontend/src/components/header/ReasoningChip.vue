<script setup lang="ts">
import { computed } from 'vue'
import { useUIStore } from '@/stores/ui'

const ui = useUIStore()
const disabled = computed(() => ui.multiAgent || ui.reactiveOn)
</script>

<template>
  <button
    class="reasoning-chip"
    :class="{ active: ui.deepReasoning && !disabled, muted: disabled }"
    :title="disabled ? 'Deep Reasoning is only available in single agent mode' : 'Toggle extended reasoning'"
    :disabled="disabled"
    @click.stop="ui.toggleDeepReasoning()"
  >
    Deep Reasoning
  </button>
</template>

<style scoped>
.reasoning-chip {
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text2);
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background 0.15s, opacity 0.15s;
  white-space: nowrap;
}

.reasoning-chip.active {
  border-color: var(--color-verified);
  color: var(--color-verified);
  background: rgba(45, 212, 191, 0.08);
}

.reasoning-chip.muted {
  opacity: 0.35;
  cursor: not-allowed;
}
</style>
