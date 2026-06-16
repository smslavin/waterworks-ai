<script setup lang="ts">
import { useUIStore } from '@/stores/ui'
import type { FlyoutKey } from '@/stores/ui'

const ui = useUIStore()

const ICONS: { key: FlyoutKey; label: string; path: string }[] = [
  {
    key: 'notif',
    label: 'Notifications',
    path: 'M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 0 1-3.46 0',
  },
  {
    key: 'health',
    label: 'Service health',
    path: 'M22 12h-4l-3 9L9 3l-3 9H2',
  },
  {
    key: 'faults',
    label: 'Fault injection',
    path: 'M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01',
  },
  {
    key: 'audit',
    label: 'Audit log',
    path: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M16 13H8M16 17H8M10 9H8',
  },
]
</script>

<template>
  <div class="icon-strip">
    <button
      v-for="item in ICONS"
      :key="item.key"
      class="strip-btn"
      :class="{ active: ui.activeFlyout === item.key }"
      :title="item.label"
      @click.stop="ui.toggleFlyout(item.key)"
    >
      <svg
        width="18"
        height="18"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.75"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path :d="item.path" />
      </svg>
    </button>
  </div>
</template>

<style scoped>
.icon-strip {
  width: 48px;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 0;
  gap: 2px;
  background: var(--color-bg2);
  border-right: 1px solid var(--color-border);
  flex-shrink: 0;
}

.strip-btn {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--color-text2);
  cursor: pointer;
  transition: color 0.12s, border-color 0.12s, background 0.12s;
}

.strip-btn:hover {
  color: var(--color-text1);
  background: var(--color-bg3);
}

.strip-btn.active {
  color: var(--color-accent);
  border-color: var(--color-accent);
  background: rgba(59, 130, 246, 0.08);
}
</style>
