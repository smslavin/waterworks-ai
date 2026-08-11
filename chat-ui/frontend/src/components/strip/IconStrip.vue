<script setup lang="ts">
import { ref } from 'vue'
import { useUIStore } from '@/stores/ui'
import type { FlyoutKey } from '@/stores/ui'

const ui = useUIStore()

const FLYOUT_ICONS: { key: NonNullable<FlyoutKey>; label: string; path: string }[] = [
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
    key: 'settings',
    label: 'Settings',
    path: 'M3 9h12M19 9h2M15 7v4M3 15h2M9 15h12M5 13v4',
  },
]

function openAuditLog() {
  window.open('/audit', '_blank', 'noopener')
}

function openMetrics() {
  window.open('/metrics', '_blank', 'noopener')
}

function openGrafana() {
  // Same fix as SiteNav.vue's selectSite(): localhost is only correct if
  // the browser is on the same host as this plant's own services — reach
  // Grafana the same way the browser reached this page instead. Port is
  // per-plant (docker-compose host port), seeded from GET /api/site.
  window.open(
    `http://${window.location.hostname}:${ui.grafanaPort}`,
    '_blank',
    'noopener'
  )
}

const confirmingClear = ref(false)

function requestClear() {
  confirmingClear.value = true
}

function cancelClear() {
  confirmingClear.value = false
}

async function confirmClear() {
  confirmingClear.value = false
  await fetch('/api/audit/clear', { method: 'POST' })
}
</script>

<template>
  <div class="icon-strip">
    <!-- Flyout toggles -->
    <button
      v-for="item in FLYOUT_ICONS"
      :key="item.key"
      class="strip-btn"
      :class="{ active: ui.activeFlyout === item.key }"
      :title="item.label"
      @click.stop="ui.toggleFlyout(item.key)"
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
        <path :d="item.path" />
      </svg>
    </button>

    <div class="strip-divider" />

    <!-- Audit log — new window -->
    <button class="strip-btn" title="Audit log" @click.stop="openAuditLog">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M16 13H8M16 17H8M10 9H8" />
      </svg>
    </button>

    <!-- Metrics — new window -->
    <button class="strip-btn" title="Metrics" @click.stop="openMetrics">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
        <path d="M18 20V10M12 20V4M6 20v-6" />
      </svg>
    </button>

    <!-- Grafana dashboards — new window -->
    <button class="strip-btn" title="Grafana dashboards" @click.stop="openGrafana">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
      </svg>
    </button>

    <div class="strip-divider" />

    <!-- Clear audit log — two-click inline confirmation -->
    <div class="clear-wrap">
      <button
        class="strip-btn strip-btn-danger"
        :class="{ active: confirmingClear }"
        title="Clear audit log"
        @click.stop="requestClear"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="3 6 5 6 21 6" />
          <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
        </svg>
      </button>
      <Transition name="confirm-pop">
        <div v-if="confirmingClear" class="clear-confirm" @click.stop>
          <span class="clear-confirm-label">Clear audit log?</span>
          <span class="clear-confirm-sub">Cannot be undone</span>
          <div class="clear-confirm-btns">
            <button class="clear-cancel-btn" @click.stop="cancelClear">Cancel</button>
            <button class="clear-ok-btn" @click.stop="confirmClear">Clear</button>
          </div>
        </div>
      </Transition>
    </div>
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

.strip-divider {
  width: 24px;
  height: 1px;
  background: var(--color-border);
  margin: 4px 0;
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

.strip-btn-danger {
  color: var(--color-error);
  opacity: 0.6;
}

.strip-btn-danger:hover {
  color: var(--color-error);
  opacity: 1;
  background: rgba(248, 113, 113, 0.08);
}

.strip-btn-danger.active {
  color: var(--color-error);
  border-color: rgba(248, 113, 113, 0.4);
  background: rgba(248, 113, 113, 0.08);
}

.clear-wrap {
  position: relative;
}

.clear-confirm {
  position: absolute;
  left: calc(100% + 10px);
  bottom: 0;
  width: 164px;
  background: var(--color-bg2);
  border: 1px solid rgba(248, 113, 113, 0.4);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
  z-index: 200;
}

.clear-confirm-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-error);
}

.clear-confirm-sub {
  font-size: 11px;
  color: var(--color-text2);
  margin-top: -4px;
}

.clear-confirm-btns {
  display: flex;
  gap: 6px;
}

.clear-cancel-btn {
  flex: 1;
  padding: 5px 0;
  border-radius: 5px;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text2);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.12s, color 0.12s;
}

.clear-cancel-btn:hover {
  border-color: var(--color-text2);
  color: var(--color-text1);
}

.clear-ok-btn {
  flex: 1;
  padding: 5px 0;
  border-radius: 5px;
  border: 1px solid rgba(248, 113, 113, 0.5);
  background: rgba(248, 113, 113, 0.1);
  color: var(--color-error);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.12s;
}

.clear-ok-btn:hover {
  background: rgba(248, 113, 113, 0.2);
}

.confirm-pop-enter-active,
.confirm-pop-leave-active {
  transition: opacity 0.15s, transform 0.15s;
}

.confirm-pop-enter-from,
.confirm-pop-leave-to {
  opacity: 0;
  transform: translateX(-6px);
}
</style>
