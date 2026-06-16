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
  </div>
</template>

<style scoped>
.topo-columns {
  display: flex;
  gap: 80px;
  padding: 48px 80px 40px;
  flex: 1;
  align-items: flex-start;
}
</style>
