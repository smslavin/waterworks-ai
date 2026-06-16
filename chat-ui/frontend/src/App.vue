<script setup lang="ts">
import { useUIStore } from '@/stores/ui'
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

const ui = useUIStore()
usePanelDismiss()
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
      </div>
    </div>
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
