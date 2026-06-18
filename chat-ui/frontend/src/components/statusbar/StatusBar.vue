<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useUIStore } from '@/stores/ui'
import { useTopologyStore } from '@/stores/topology'
import { AREA_ORDER } from '@/stores/topology'
import type { AlarmState } from '@/stores/topology'
import type { CrumbLevel } from '@/stores/ui'
import { useReactive } from '@/composables/useReactive'
import SiteNav from './SiteNav.vue'

const ui = useUIStore()
const topo = useTopologyStore()
const { activeSite, activeRegion } = storeToRefs(ui)
const { toggle: toggleReactive } = useReactive()

interface AreaDot {
  area: string
  status: AlarmState
}

function worstAlarmState(states: AlarmState[]): AlarmState {
  if (states.includes('critical')) return 'critical'
  if (states.includes('pending-approval')) return 'pending-approval'
  if (states.includes('warning')) return 'warning'
  return 'normal'
}

const areaDots = computed<AreaDot[]>(() =>
  AREA_ORDER.map(area => ({
    area,
    status: worstAlarmState((topo.nodesByArea[area] ?? []).map(n => n.alarmState)),
  }))
)

interface CrumbItem {
  label: string
  key?: CrumbLevel
  action: () => void
}

const crumbItems = computed<CrumbItem[]>(() => {
  const items: CrumbItem[] = [
    { label: 'Enterprise',        key: 'enterprise', action: () => ui.openCrumbPanel('enterprise') },
    { label: activeRegion.value,  key: 'region',     action: () => ui.openCrumbPanel('region') },
    { label: activeSite.value,    key: 'plant',      action: () => ui.openCrumbPanel('plant') },
  ]

  if (ui.activeNodeId) {
    const node = topo.nodeById(ui.activeNodeId)
    if (node) {
      items.push({ label: node.area,       action: () => ui.setActiveArea(node.area) })
      items.push({ label: ui.activeNodeId, action: () => ui.setActiveNode(ui.activeNodeId!) })
    }
  } else if (ui.activeArea) {
    items.push({ label: ui.activeArea, action: () => ui.setActiveArea(ui.activeArea!) })
  }

  return items
})
</script>

<template>
  <div class="status-bar">
    <!-- Left: Area status dots -->
    <div class="area-dots">
      <button
        v-for="dot in areaDots"
        :key="dot.area"
        class="area-dot-btn"
        :title="dot.area"
        @click.stop="ui.setActiveArea(dot.area)"
      >
        <span class="area-dot" :class="dot.status" />
        <span class="area-name">{{ dot.area }}</span>
      </button>
    </div>

    <!-- Left: Reactive toggle (requires Multi-Agent mode) -->
    <button
      class="reactive-toggle"
      :class="{ active: ui.reactiveOn, locked: !ui.multiAgent }"
      :disabled="!ui.multiAgent"
      :title="!ui.multiAgent ? 'Requires Multi-Agent mode' : ui.reactiveOn ? 'Reactive monitoring on' : 'Reactive monitoring off'"
      @click.stop="toggleReactive()"
    >
      <span class="toggle-track">
        <span class="toggle-thumb" />
      </span>
      <span class="toggle-label">Reactive</span>
    </button>

    <!-- Spacer pushes breadcrumb + globe to the right -->
    <div class="status-spacer" />

    <!-- Right: Breadcrumb trail -->
    <nav class="crumb-trail" aria-label="breadcrumb">
      <template v-for="(item, i) in crumbItems" :key="item.label">
        <span v-if="i > 0" class="crumb-sep" aria-hidden="true">›</span>
        <button class="crumb-item" @click.stop="item.action()">{{ item.label }}</button>
      </template>
    </nav>

    <!-- Right: Globe + SiteNav -->
    <div class="globe-wrap">
      <button
        class="globe-btn"
        :class="{ active: ui.siteNavOpen }"
        title="Site navigator"
        @click.stop="ui.toggleSiteNav()"
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10" />
          <line x1="2" y1="12" x2="22" y2="12" />
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
        </svg>
      </button>
      <SiteNav />
    </div>
  </div>
</template>

<style scoped>
.status-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  height: 36px;
  padding: 0 12px 0 16px;
  background: var(--color-bg2);
  border-top: 1px solid var(--color-border);
  flex-shrink: 0;
  position: relative;
}

.globe-wrap {
  position: relative;
}

/* Area dots */
.area-dots {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
}

.area-dot-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border: none;
  background: transparent;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.12s;
}

.area-dot-btn:hover {
  background: var(--color-bg3);
}

.area-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.area-dot.normal           { background: var(--color-ok); }
.area-dot.warning          { background: var(--color-warn); }
.area-dot.critical         { background: var(--color-error); }
.area-dot.pending-approval { background: #a855f7; }

.area-name {
  font-size: 10px;
  font-weight: 600;
  color: var(--color-text2);
}

.status-spacer {
  flex: 1;
}

/* Crumb trail */
.crumb-trail {
  display: flex;
  align-items: center;
  gap: 4px;
  overflow: hidden;
  max-width: 400px;
  flex-shrink: 1;
}

.crumb-sep {
  color: var(--color-border);
  font-size: 11px;
  flex-shrink: 0;
}

.crumb-item {
  font-size: 11px;
  color: var(--color-text2);
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 3px;
  transition: color 0.12s, background 0.12s;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 120px;
}

.crumb-item:hover {
  color: var(--color-text1);
  background: var(--color-bg3);
}

.crumb-item:last-child {
  color: var(--color-text1);
  font-weight: 500;
}

.reactive-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 6px;
  background: transparent;
  border: none;
  cursor: pointer;
}

.reactive-toggle.locked {
  opacity: 0.35;
  cursor: default;
}

.toggle-track {
  width: 24px;
  height: 13px;
  border-radius: 999px;
  background: var(--color-border);
  position: relative;
  transition: background 0.2s;
  flex-shrink: 0;
}

.reactive-toggle.active .toggle-track {
  background: var(--color-warn);
}

.toggle-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--color-text2);
  transition: transform 0.2s, background 0.2s;
}

.reactive-toggle.active .toggle-thumb {
  transform: translateX(11px);
  background: #fff;
}

.toggle-label {
  font-size: 11px;
  color: var(--color-text2);
  transition: color 0.15s;
}

.reactive-toggle.active .toggle-label {
  color: var(--color-warn);
}

.globe-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--color-text2);
  cursor: pointer;
  transition: color 0.12s, border-color 0.12s, background 0.12s;
}

.globe-btn:hover {
  color: var(--color-text1);
  background: var(--color-bg3);
}

.globe-btn.active {
  color: var(--color-accent);
  border-color: var(--color-accent);
  background: rgba(59, 130, 246, 0.08);
}
</style>
