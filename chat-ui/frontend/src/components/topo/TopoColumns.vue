<script setup lang="ts">
import { useTopologyStore } from '@/stores/topology'
import { useUIStore } from '@/stores/ui'
import TopoColumn from './TopoColumn.vue'

const topo = useTopologyStore()
const ui = useUIStore()
</script>

<template>
  <div class="topo-columns">
    <TopoColumn
      v-for="area in topo.areas"
      :key="area"
      :area="area"
      :nodes="topo.nodesByArea[area]"
      @node-click="ui.setActiveNode"
      @label-click="ui.setActiveArea"
    />
    <div class="canvas-hint">
      click a node to diagnose · click a column label for area summary
    </div>
  </div>
</template>

<style scoped>
.topo-columns {
  display: flex;
  justify-content: space-evenly;
  padding: 48px 64px 40px;
  flex: 1;
  align-items: flex-start;
  position: relative;
}

.canvas-hint {
  position: absolute;
  bottom: 16px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 11px;
  color: var(--color-text2);
  opacity: 0.45;
  pointer-events: none;
  white-space: nowrap;
  letter-spacing: 0.03em;
}
</style>
