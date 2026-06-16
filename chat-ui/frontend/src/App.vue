<script setup lang="ts">
import { useUIStore } from '@/stores/ui'
import TopoColumns from '@/components/topo/TopoColumns.vue'
import TopoEdges from '@/components/topo/TopoEdges.vue'

const ui = useUIStore()
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
