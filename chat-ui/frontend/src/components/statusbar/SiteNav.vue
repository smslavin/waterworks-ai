<script setup lang="ts">
import { useUIStore } from '@/stores/ui'

const ui = useUIStore()

interface SiteArea { label: string; status: 'ok' | 'warn' | 'crit' }
interface Site { name: string; isCurrent: boolean; areas: SiteArea[] }

const SITES: Site[] = [
  {
    name: 'Waterworks',
    isCurrent: true,
    areas: [
      { label: 'Intake', status: 'crit' },
      { label: 'Treatment', status: 'warn' },
      { label: 'Distribution', status: 'crit' },
    ],
  },
  {
    name: 'Eastside',
    isCurrent: false,
    areas: [
      { label: 'Intake', status: 'ok' },
      { label: 'Treatment', status: 'ok' },
      { label: 'Distribution', status: 'ok' },
    ],
  },
  {
    name: 'Northgate',
    isCurrent: false,
    areas: [
      { label: 'Intake', status: 'ok' },
      { label: 'Treatment', status: 'warn' },
      { label: 'Distribution', status: 'ok' },
    ],
  },
  {
    name: 'Riverfront',
    isCurrent: false,
    areas: [
      { label: 'Intake', status: 'ok' },
      { label: 'Treatment', status: 'ok' },
      { label: 'Distribution', status: 'ok' },
    ],
  },
]
</script>

<template>
  <Transition name="sitenav">
    <div
      v-if="ui.siteNavOpen"
      class="site-nav"
      @click.stop
    >
      <div class="site-nav-header">
        <span class="site-nav-title">Sites</span>
        <button class="site-nav-close" @click="ui.siteNavOpen = false">✕</button>
      </div>

      <div class="site-nav-body">
        <button
          v-for="site in SITES"
          :key="site.name"
          class="site-row"
          :class="{ current: site.isCurrent }"
        >
          <span class="site-indicator" :class="{ current: site.isCurrent }" />
          <span class="site-name">{{ site.name }}</span>
          <div class="site-area-dots">
            <span
              v-for="area in site.areas"
              :key="area.label"
              class="site-area-dot"
              :class="area.status"
              :title="area.label"
            />
          </div>
        </button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.site-nav {
  position: absolute;
  bottom: calc(100% + 6px);
  right: 0;
  width: 240px;
  background: var(--color-bg2);
  border: 1px solid var(--color-border);
  border-radius: 10px;
  z-index: 70;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
}

.site-nav-header {
  display: flex;
  align-items: center;
  padding: 10px 12px;
  border-bottom: 1px solid var(--color-border);
  gap: 8px;
}

.site-nav-title {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--color-text1);
  flex: 1;
}


.site-nav-close {
  background: transparent;
  border: none;
  color: var(--color-text2);
  font-size: 11px;
  cursor: pointer;
  padding: 2px 4px;
  transition: color 0.12s;
}

.site-nav-close:hover {
  color: var(--color-text1);
}

.site-nav-body {
  display: flex;
  flex-direction: column;
  padding: 6px 0;
}

.site-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  background: transparent;
  border: none;
  cursor: pointer;
  transition: background 0.1s;
  text-align: left;
}

.site-row:hover {
  background: var(--color-bg3);
}

.site-row.current {
  background: rgba(45, 212, 191, 0.06);
}

.site-indicator {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-border);
  flex-shrink: 0;
}

.site-indicator.current {
  background: var(--color-verified);
}

.site-name {
  font-size: 12px;
  color: var(--color-text1);
  flex: 1;
}

.site-area-dots {
  display: flex;
  gap: 8px;
}

.site-area-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.site-area-dot.ok   { background: var(--color-ok); }
.site-area-dot.warn { background: var(--color-warn); }
.site-area-dot.crit { background: var(--color-error); }

.sitenav-enter-active,
.sitenav-leave-active {
  transition: opacity 0.15s, transform 0.15s;
}

.sitenav-enter-from,
.sitenav-leave-to {
  opacity: 0;
  transform: translateY(8px) scale(0.97);
}
</style>
