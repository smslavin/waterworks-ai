<script setup lang="ts">
import ReactivePill from './ReactivePill.vue'
import ApprovalPill from './ApprovalPill.vue'
import ModeChip from './ModeChip.vue'
import ReasoningChip from './ReasoningChip.vue'
import ConfigButton from './ConfigButton.vue'
</script>

<template>
  <header class="app-header">
    <div class="header-left">
      <span class="site-name">Waterworks</span>
    </div>
    <div class="header-right">
      <ReactivePill />
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
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-verified);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-divider {
  width: 1px;
  height: 18px;
  background: var(--color-border);
  margin: 0 4px;
}
</style>
