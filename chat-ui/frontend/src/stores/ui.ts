import { defineStore } from 'pinia'
import { ref } from 'vue'

export type FlyoutKey = 'notif' | 'health' | 'faults' | 'settings' | null
export type PanelKey = 'node' | 'area' | 'plant' | null
export type CrumbLevel = 'plant' | 'region' | 'enterprise'

export const useUIStore = defineStore('ui', () => {
  // Config mode: operational view ↔ topology builder
  const configMode = ref(false)

  // Active selections driving panel display
  const activeNodeId = ref<string | null>(null)
  const activeArea = ref<string | null>(null)
  const activePanel = ref<PanelKey>(null)

  // Icon strip flyout
  const activeFlyout = ref<FlyoutKey>(null)

  // Active site / region (nav hierarchy: enterprise > region > site)
  const activeSite = ref('Waterworks')
  const activeRegion = ref('Metro Region')
  // GRAFANA_PORT varies per plant (docker-compose host port) — seeded from
  // GET /api/site alongside activeSite/activeRegion. See IconStrip.vue's
  // openGrafana() for why the host portion is never read from here.
  const grafanaPort = ref(3000)

  // Overlays
  const siteNavOpen = ref(false)
  const approvalOpen = ref(false)

  // Agent / model settings
  const multiAgent = ref(false)
  const deepReasoning = ref(false)
  const reactiveOn = ref(false)
  const selectedModel = ref('')

  // Crumb trail level for PlantPanel
  const crumbLevel = ref<CrumbLevel>('plant')

  function enterConfigMode() {
    configMode.value = true
  }

  function exitConfigMode() {
    configMode.value = false
  }

  function setActiveNode(id: string | null) {
    activeNodeId.value = id
    activeArea.value = null
    activePanel.value = id ? 'node' : null
  }

  function setActiveArea(area: string | null) {
    activeArea.value = area
    activeNodeId.value = null
    activePanel.value = area ? 'area' : null
  }

  function openPlantPanel() {
    activeNodeId.value = null
    activeArea.value = null
    crumbLevel.value = 'plant'
    activePanel.value = 'plant'
  }

  function openCrumbPanel(level: CrumbLevel) {
    activeNodeId.value = null
    activeArea.value = null
    crumbLevel.value = level
    activePanel.value = 'plant'
  }

  function dismissPanels() {
    activeNodeId.value = null
    activeArea.value = null
    activePanel.value = null
    activeFlyout.value = null
    siteNavOpen.value = false
  }

  function setActiveSite(site: string, region: string) {
    activeSite.value = site
    activeRegion.value = region
    activeNodeId.value = null
    activeArea.value = null
    activePanel.value = null
    siteNavOpen.value = false
  }

  function toggleSiteNav() {
    siteNavOpen.value = !siteNavOpen.value
  }

  function toggleFlyout(key: FlyoutKey) {
    activeFlyout.value = activeFlyout.value === key ? null : key
  }

  function closeFlyout() {
    activeFlyout.value = null
  }

  function toggleMultiAgent() {
    multiAgent.value = !multiAgent.value
    if (!multiAgent.value) reactiveOn.value = false
  }

  function toggleDeepReasoning() {
    deepReasoning.value = !deepReasoning.value
  }

  function toggleReactive() {
    reactiveOn.value = !reactiveOn.value
  }

  return {
    configMode,
    activeSite,
    activeRegion,
    grafanaPort,
    activeNodeId,
    activeArea,
    activePanel,
    activeFlyout,
    siteNavOpen,
    approvalOpen,
    multiAgent,
    deepReasoning,
    reactiveOn,
    selectedModel,
    crumbLevel,
    enterConfigMode,
    exitConfigMode,
    setActiveSite,
    setActiveNode,
    setActiveArea,
    openPlantPanel,
    openCrumbPanel,
    dismissPanels,
    toggleSiteNav,
    toggleFlyout,
    closeFlyout,
    toggleMultiAgent,
    toggleDeepReasoning,
    toggleReactive,
  }
})
