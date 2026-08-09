<script setup lang="ts">
import { onMounted } from 'vue'
import { useUIStore } from '@/stores/ui'
import { useTopologyStore } from '@/stores/topology'
import { useAlarmStore } from '@/stores/alarm'
import { usePanelDismiss } from '@/composables/usePanelDismiss'
import AppHeader from '@/components/header/AppHeader.vue'
import AlarmStrip from '@/components/alarm/AlarmStrip.vue'
import IconStrip from '@/components/strip/IconStrip.vue'
import StripFlyout from '@/components/strip/StripFlyout.vue'
import TopoColumns from '@/components/topo/TopoColumns.vue'
import TopoEdges from '@/components/topo/TopoEdges.vue'
import NodePanel from '@/components/panels/NodePanel.vue'
import AreaPanel from '@/components/panels/AreaPanel.vue'
import PlantPanel from '@/components/panels/PlantPanel.vue'
import StatusBar from '@/components/statusbar/StatusBar.vue'
import ApprovalPanel from '@/components/approval/ApprovalPanel.vue'
import ConfigShell from '@/components/config/ConfigShell.vue'

const ui = useUIStore()
const topo = useTopologyStore()
const alarm = useAlarmStore()
usePanelDismiss()

// Carry UI-preference toggles across a cross-plant SiteNav navigation (see
// SiteNav.vue's selectSite) — read synchronously, during setup rather than
// onMounted, so child components (StatusBar -> useReactive) see the correct
// ui.multiAgent from their own mount, not one tick later.
const _carryParams = new URLSearchParams(window.location.search)
if (_carryParams.get('multiAgent') === '1' || _carryParams.get('reactive') === '1') {
  ui.multiAgent = true // reactive requires multi-agent
}

onMounted(async () => {
  try {
    const resp = await fetch('/api/site')
    if (resp.ok) {
      const site = await resp.json() as { site_id: string; site_name: string; region_name: string }
      ui.setActiveSite(site.site_name, site.region_name)
    }
  } catch { /* backend not running — keep ui.ts defaults */ }

  if (_carryParams.get('reactive') === '1') {
    try {
      const resp = await fetch('/api/reactive/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enable: true }),
      })
      const data = await resp.json() as { enabled: boolean }
      ui.reactiveOn = data.enabled
    } catch { /* backend unreachable — leave default */ }
  }

  if (_carryParams.has('multiAgent') || _carryParams.has('reactive')) {
    // Drop the carry-over params so a manual refresh doesn't re-force these
    // toggles after the operator has since changed them.
    window.history.replaceState({}, '', window.location.pathname)
  }

  try {
    const resp = await fetch('/api/fault/status')
    if (resp.ok) {
      const status = await resp.json() as Record<string, string>
      Object.entries(status).forEach(([nodeId, mode]) => {
        topo.setAlarmState(nodeId, mode === 'normal' ? 'normal' : 'critical')
        if (mode !== 'normal') {
          alarm.addAlarm({
            id: nodeId,
            nodeId,
            severity: 'critical',
            message: mode.replace(/_/g, ' '),
            timestamp: new Date().toISOString(),
          })
        }
      })
    }
  } catch { /* backend not running */ }
  topo.loadInsightCategories()
})
</script>

<template>
  <div id="app">
    <AppHeader />
    <AlarmStrip />
    <div class="app-main">
      <IconStrip />
      <div class="app-canvas-wrapper">
        <StripFlyout />
        <div
          id="topo-canvas"
          class="topo-canvas"
          @click="ui.dismissPanels()"
        >
          <TopoColumns />
          <TopoEdges />
          <NodePanel />
          <AreaPanel />
          <PlantPanel />
        </div>
        <ApprovalPanel />
      </div>
    </div>
    <StatusBar />
    <ConfigShell />
  </div>
</template>

<style scoped>
#app {
  display: flex;
  flex-direction: column;
  height: 100dvh;
  overflow: hidden;
}

.app-main {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.app-canvas-wrapper {
  flex: 1;
  position: relative;
  overflow: hidden;
  display: flex;
}

.topo-canvas {
  flex: 1;
  position: relative;
  overflow: hidden;
  display: flex;
}
</style>
