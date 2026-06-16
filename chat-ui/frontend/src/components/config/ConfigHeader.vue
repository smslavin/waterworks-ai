<script setup lang="ts">
import { useUIStore } from '@/stores/ui'

const ui = useUIStore()
</script>

<template>
  <header class="config-header">
    <button class="exit-btn" @click="ui.exitConfigMode()">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="15 18 9 12 15 6" />
      </svg>
      Exit
    </button>
    <div class="config-title-group">
      <span class="config-title">Topology Builder</span>
      <span class="config-mode-badge">Configuration Mode</span>
    </div>
    <div class="config-header-right">
      <span class="config-hint">Changes require commit before taking effect</span>
    </div>
  </header>
</template>

<style scoped>
.config-header {
  display: flex;
  align-items: center;
  gap: 24px;
  height: 48px;
  padding: 0 20px;
  background: #0d0d18;
  border-bottom: 2px solid var(--color-config);
  flex-shrink: 0;
}

.exit-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 6px;
  border: 1px solid var(--color-config);
  background: transparent;
  color: var(--color-config);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
  flex-shrink: 0;
}

.exit-btn:hover {
  background: rgba(99, 102, 241, 0.12);
}

.config-title-group {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.config-title {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--color-config);
}

.config-mode-badge {
  font-size: 10px;
  color: var(--color-text2);
  letter-spacing: 0.06em;
}

.config-header-right {
  flex: 1;
  display: flex;
  justify-content: flex-end;
}

.config-hint {
  font-size: 11px;
  color: var(--color-text2);
  font-style: italic;
}
</style>
