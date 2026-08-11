<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useUIStore } from '@/stores/ui'
import { useTopologyStore, AREA_ORDER, type AlarmState } from '@/stores/topology'

const ui = useUIStore()
const topo = useTopologyStore()
const { activeRegion, activeSite } = storeToRefs(ui)

type AreaStatus = 'ok' | 'warn' | 'crit'
interface SiteArea { label: string; status: AreaStatus }
interface Site { name: string; chatUiUrl: string | null; areas: SiteArea[] }
interface Region { name: string; sites: Site[] }

interface DirectorySite {
  name: string
  region: string
  chat_ui_url: string
}

// Populated from GET /api/sites (a proxy of the enterprise orchestrator's
// own /api/sites — see chat-ui/backend.py's sites_endpoint). Empty when the
// enterprise layer isn't running; this plant is always injected below so the
// popover is never empty even then.
const directory = ref<Record<string, DirectorySite>>({})
const loaded = ref(false)

function alarmToStatus(state: AlarmState): AreaStatus {
  if (state === 'critical' || state === 'pending-approval') return 'crit'
  if (state === 'warning') return 'warn'
  return 'ok'
}

// Only this plant's own area status is real (sourced from the already-loaded
// topology/alarm state) — other plants' live health isn't fetched by Phase 4
// (deferred, see plan_m10_enterprise_multiplant.md's Phase 4 follow-up note).
const ownAreas = computed<SiteArea[]>(() =>
  AREA_ORDER.filter(a => topo.nodesByArea[a]?.length).map(area => ({
    label: area,
    status: (topo.nodesByArea[area] ?? []).reduce<AreaStatus>((worst, n) => {
      const s = alarmToStatus(n.alarmState)
      if (worst === 'crit' || s === 'crit') return s === 'crit' ? 'crit' : worst
      return s === 'warn' || worst === 'warn' ? 'warn' : 'ok'
    }, 'ok'),
  }))
)

const regions = computed<Region[]>(() => {
  const byRegion = new Map<string, Site[]>()

  function addSite(regionName: string, site: Site) {
    const list = byRegion.get(regionName) ?? []
    if (!list.some(s => s.name === site.name)) list.push(site)
    byRegion.set(regionName, list)
  }

  // Always include this plant first, with real area status.
  addSite(activeRegion.value, { name: activeSite.value, chatUiUrl: null, areas: ownAreas.value })

  for (const site of Object.values(directory.value)) {
    if (site.name === activeSite.value) continue // already added above, with real status
    addSite(site.region, { name: site.name, chatUiUrl: site.chat_ui_url, areas: [] })
  }

  return Array.from(byRegion.entries()).map(([name, sites]) => ({ name, sites }))
})

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
  regions.value.find(r => r.name === viewingRegion.value)?.sites ?? []
)

async function loadDirectory() {
  try {
    const resp = await fetch('/api/sites')
    if (resp.ok) directory.value = await resp.json()
  } catch { /* enterprise layer unreachable — just show this plant */ }
  loaded.value = true
}

// Reset to the current site's region every time the nav opens, and refresh
// the directory (cheap read, keeps a newly-registered plant from requiring
// a page reload to appear). `immediate: true` because the nav can already be
// open at mount time (e.g. a hot-reload or test render) — a plain watcher
// only fires on change, so it would never fetch in that case.
watch(() => ui.siteNavOpen, (open) => {
  if (open) {
    navLevel.value = 'site'
    viewingRegionOverride.value = null
    loadDirectory()
  }
}, { immediate: true })

function drillToRegion(regionName: string) {
  viewingRegionOverride.value = regionName
  navLevel.value = 'site'
}

function selectSite(site: Site) {
  if (site.name === activeSite.value) {
    ui.siteNavOpen = false
    return
  }
  // Cross-plant switching is a full browser navigation to that plant's own
  // chat-ui origin, not an in-app API repoint — deliberately, to avoid
  // opening CORS between plant origins on a system with an actuation path
  // (control-mcp setpoints). See plan_m10_enterprise_multiplant.md.
  if (!site.chatUiUrl) return
  // enterprise.yaml's chat_ui_url is written as http://localhost:<port> —
  // correct for the backend-to-backend calls that also read it (orchestrator,
  // diagnose_plant_mcp), which run on the same host as every plant. But this
  // is a *browser* navigation: if the browser isn't on that host (e.g. it's
  // on the VMware host machine, reaching the VM at 192.168.x.x), "localhost"
  // resolves to the browser's own machine instead, which has nothing on that
  // port — swap in whatever host got us to *this* page instead of trusting
  // chat_ui_url's host verbatim (its port is still per-plant and correct).
  const url = new URL(site.chatUiUrl)
  url.hostname = window.location.hostname
  // Carry UI-preference toggles across the navigation as query params —
  // App.vue reads them on mount. Deliberately not URL-encoding arbitrary
  // state: just the two flags that don't survive a fresh page load.
  if (ui.multiAgent) url.searchParams.set('multiAgent', '1')
  if (ui.reactiveOn) url.searchParams.set('reactive', '1')
  window.location.href = url.toString()
}
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
          v-for="region in regions"
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
          :class="{ current: site.name === activeSite }"
          @click="selectSite(site)"
        >
          <span class="site-indicator" :class="{ current: site.name === activeSite }" />
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
        <div v-if="loaded && sitesInRegion.length <= 1" class="site-nav-empty">
          No other sites reachable — check the enterprise layer is running.
        </div>
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

.site-nav-empty {
  padding: 8px 12px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--color-text2);
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
