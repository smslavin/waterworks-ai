<script setup lang="ts">
import type { TopologyNode } from '@/stores/topology'
import TopoNode from './TopoNode.vue'

defineProps<{
  area: string
  nodes: TopologyNode[]
}>()

const emit = defineEmits<{
  'node-click': [id: string]
  'label-click': [area: string]
}>()
</script>

<template>
  <div class="topo-column" :data-area="area">
    <div class="topo-column-label" @click.stop="emit('label-click', area)">
      {{ area }}
    </div>
    <TopoNode
      v-for="node in nodes"
      :key="node.id"
      :node="node"
      @click="emit('node-click', $event)"
    />
  </div>
</template>

<style scoped>
.topo-column {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 44px;
}

.topo-column-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text2);
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px solid var(--border);
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
  white-space: nowrap;
}

.topo-column-label:hover {
  color: var(--text);
  border-color: var(--accent);
}
</style>
