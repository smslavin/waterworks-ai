<script setup lang="ts">
import { useUIStore } from '@/stores/ui'

const ui = useUIStore()

function onClick() {
  ui.approvalOpen = true
}
</script>

<template>
  <button
    class="approval-pill"
    :class="{ active: ui.approvalOpen }"
    title="Pending operator approval"
    @click.stop="onClick"
  >
    <span class="pill-dot" />
    <span>Approval</span>
  </button>
</template>

<style scoped>
.approval-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid #a855f7;
  background: transparent;
  color: #a855f7;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  animation: approval-pill-pulse 2s ease-in-out infinite;
  transition: background 0.15s;
}

.approval-pill.active {
  background: rgba(168, 85, 247, 0.12);
}

.pill-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}
</style>
