<script setup lang="ts">
import { computed } from 'vue'
import { useUIStore } from '@/stores/ui'
import type { TopologyNode } from '@/stores/topology'

const props = defineProps<{ node: TopologyNode }>()
const emit = defineEmits<{ click: [id: string] }>()

const ui = useUIStore()

const isActive = computed(() => ui.activeNodeId === props.node.id)

const circleSizePx = computed(() => {
  if (props.node.confidenceLevel === 'verified') return 44
  if (props.node.confidenceLevel === 'inferred') return 36
  return 28
})

const memoryLabel = computed(() => {
  if (!props.node.hasMemory) return ''
  return props.node.saveCount > 1 ? `● ${props.node.saveCount} mem` : '● mem'
})
</script>

<template>
  <div
    class="topo-node"
    :class="[
      node.confidenceLevel,
      node.alarmState !== 'normal' ? node.alarmState : '',
      { active: isActive, 'has-memory': node.hasMemory },
    ]"
    :data-id="node.id"
    @click.stop="emit('click', node.id)"
  >
    <div
      class="topo-node-circle"
      :style="{ width: `${circleSizePx}px`, height: `${circleSizePx}px` }"
    />
    <div class="topo-node-label">{{ node.id }}</div>
    <div class="topo-node-type">{{ node.equipmentType }}</div>
    <div v-if="node.hasMemory" class="node-memory">{{ memoryLabel }}</div>
  </div>
</template>

<style scoped>
.topo-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  position: relative;
}

.topo-node-circle {
  border-radius: 50%;
  border: 2px solid var(--border);
  background: var(--bg2);
  transition: border-color 0.2s, box-shadow 0.2s;
}

.topo-node:hover .topo-node-circle,
.topo-node.active .topo-node-circle {
  border-color: var(--accent);
}

.topo-node.active .topo-node-circle {
  animation: node-pulse 1.8s ease-in-out infinite;
}

.topo-node.warning .topo-node-circle {
  border-color: var(--warn);
  animation: warning-pulse 2.5s ease-in-out infinite;
}

.topo-node.critical .topo-node-circle {
  border-color: var(--error);
  animation: critical-pulse 1.1s ease-in-out infinite;
}

.topo-node.pending-approval .topo-node-circle {
  border-color: #a855f7;
  animation: approval-pulse 2s ease-in-out infinite;
}

.topo-node.save-flash .topo-node-circle {
  animation: save-flash 0.6s ease-out;
}

.topo-node-label {
  font-size: 11px;
  font-weight: 600;
  font-family: var(--mono);
  color: var(--text);
  text-align: center;
  white-space: nowrap;
}

.topo-node-type {
  font-size: 9px;
  color: var(--text2);
  font-family: var(--mono);
  text-align: center;
}

.node-memory {
  font-size: 9px;
  color: var(--verified);
  font-family: var(--mono);
  text-align: center;
  margin-top: -3px;
  letter-spacing: 0.03em;
}
</style>
