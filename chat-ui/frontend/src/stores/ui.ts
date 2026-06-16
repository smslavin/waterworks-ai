import { defineStore } from 'pinia'
import { ref } from 'vue'

export type FlyoutKey = 'notif' | 'health' | 'faults' | 'audit' | null
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

  // Overlays
  const siteNavOpen = ref(false)
  const approvalOpen = ref(false)

  // Agent / model settings
  const multiAgent = ref(false)
  const deepReasoning = ref(false)
  const reactiveOn = ref(true)

  // Post-approval decision: drives which response key the node panel uses
  const postApprovalDecision = ref<'approve' | 'deny' | null>(null)

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
  }

  function toggleDeepReasoning() {
    deepReasoning.value = !deepReasoning.value
  }

  function toggleReactive() {
    reactiveOn.value = !reactiveOn.value
  }

  return {
    configMode,
    activeNodeId,
    activeArea,
    activePanel,
    activeFlyout,
    siteNavOpen,
    approvalOpen,
    multiAgent,
    deepReasoning,
    reactiveOn,
    postApprovalDecision,
    crumbLevel,
    enterConfigMode,
    exitConfigMode,
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
