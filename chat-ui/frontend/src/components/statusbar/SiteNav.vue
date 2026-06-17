<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useUIStore } from '@/stores/ui'

const ui = useUIStore()
const { activeRegion, activeSite } = storeToRefs(ui)

type AreaStatus = 'ok' | 'warn' | 'crit'
interface SiteArea { label: string; status: AreaStatus }
interface Site { name: string; areas: SiteArea[] }
interface Region { name: string; sites: Site[] }

const ENTERPRISE: Region[] = [
  {
    name: 'Metro Region',
    sites: [
      { name: 'Waterworks', areas: [{ label: 'Intake', status: 'crit' }, { label: 'Treatment', status: 'warn' }, { label: 'Distribution', status: 'crit' }] },
      { name: 'Eastside',   areas: [{ label: 'Intake', status: 'ok' },  { label: 'Treatment', status: 'ok' },  { label: 'Distribution', status: 'ok' }] },
      { name: 'Northgate',  areas: [{ label: 'Intake', status: 'ok' },  { label: 'Treatment', status: 'warn' }, { label: 'Distribution', status: 'ok' }] },
    ],
  },
  {
    name: 'Valley Region',
    sites: [
      { name: 'Riverfront', areas: [{ label: 'Intake', status: 'ok' }, { label: 'Treatment', status: 'ok' }, { label: 'Distribution', status: 'ok' }] },
      { name: 'Creekside',  areas: [{ label: 'Intake', status: 'ok' }, { label: 'Treatment', status: 'ok' }, { label: 'Distribution', status: 'warn' }] },
    ],
  },
]

function worstStatus(statuses: AreaStatus[]): AreaStatus {
  if (statuses.includes('crit')) return 'crit'
  if (statuses.includes('warn')) return 'warn'
  return 'ok'
}

function regionStatus(region: Region): AreaStatus {
  return worstStatus(region.sites.flatMap(s => s.areas.map(a => a.status)))
}

// 'region' shows the region list; 'site' shows sites within a region
const navLevel = ref<'region' | 'site'>('site')

// null = derive from active region; set when user manually drills into a different region
const viewingRegionOverride = ref<string | null>(null)
const viewingRegion = computed(() => viewingRegionOverride.value ?? activeRegion.value)

const sitesInRegion = computed(() =>
  ENTERPRISE.find(r => r.name === viewingRegion.value)?.sites ?? []
)

// Reset to the current site's region every time the nav opens
watch(() => ui.siteNavOpen, (open) => {
  if (open) {
    navLevel.value = 'site'
    viewingRegionOverride.value = null
  }
})

function drillToRegion(regionName: string) {
  viewingRegionOverride.value = regionName
  navLevel.value = 'site'
}

const LIVE_SITES = new Set(['Waterworks'])
const isLive = (name: string) => LIVE_SITES.has(name)
</script>

<template>
  <Transition name="sitenav">
    <div
      v-if="ui.siteNavOpen"
      class="site-nav"
      @click.stop
    >
      <!-- Header: region list view -->
      <div v-if="navLevel === 'region'" class="site-nav-header">
        <span class="site-nav-title">Enterprise</span>
        <button class="site-nav-close" @click="ui.siteNavOpen = false">✕</button>
      </div>

      <!-- Header: site list view (shows region name + back button) -->
      <div v-else class="site-nav-header">
        <button class="site-nav-back" title="All regions" @click="navLevel = 'region'">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>
        <span class="site-nav-title">{{ viewingRegion }}</span>
        <button class="site-nav-close" @click="ui.siteNavOpen = false">✕</button>
      </div>

      <!-- Body: region list -->
      <div v-if="navLevel === 'region'" class="site-nav-body">
        <button
          v-for="region in ENTERPRISE"
          :key="region.name"
          class="site-row"
          :class="{ current: region.name === activeRegion }"
          @click="drillToRegion(region.name)"
        >
          <span class="site-indicator" :class="{ current: region.name === activeRegion }" />
          <span class="site-name">{{ region.name }}</span>
          <div class="site-area-dots">
            <span class="site-area-dot" :class="regionStatus(region)" />
          </div>
          <svg class="row-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </button>
      </div>

      <!-- Body: site list within a region -->
      <div v-else class="site-nav-body">
        <button
          v-for="site in sitesInRegion"
          :key="site.name"
          class="site-row"
          :class="{ current: site.name === activeSite, offline: !isLive(site.name) }"
          :disabled="!isLive(site.name)"
          @click="ui.setActiveSite(site.name, viewingRegion)"
        >
          <span class="site-indicator" :class="{ current: site.name === activeSite }" />
          <span class="site-name">{{ site.name }}</span>
          <span v-if="!isLive(site.name)" class="site-offline-badge">offline</span>
          <div v-else class="site-area-dots">
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
  gap: 6px;
}

.site-nav-back {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 4px;
  border: none;
  background: transparent;
  color: var(--color-text2);
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.12s, color 0.12s;
}

.site-nav-back:hover {
  background: var(--color-bg3);
  color: var(--color-text1);
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

.site-row:hover:not(:disabled) {
  background: var(--color-bg3);
}

.site-row.offline {
  opacity: 0.4;
  cursor: default;
}

.site-offline-badge {
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text2);
  border: 1px solid var(--color-border);
  border-radius: 3px;
  padding: 1px 5px;
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

.row-chevron {
  color: var(--color-text2);
  opacity: 0.5;
  flex-shrink: 0;
}

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
