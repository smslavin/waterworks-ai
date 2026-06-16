<script setup lang="ts">
import { useUIStore } from '@/stores/ui'
import { usePanelDismiss } from '@/composables/usePanelDismiss'
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
</template>

<style scoped>
#app {
  display: flex;
  flex-direction: column;
  height: 100dvh;
  overflow: hidden;
}

.topo-canvas {
  flex: 1;
  position: relative;
  overflow: hidden;
  display: flex;
}
</style>
