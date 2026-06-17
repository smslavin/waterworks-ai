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

/* ── Default: verified + normal ─────────────────────────── */
.topo-node-circle {
  border-radius: 50%;
  border: 2.5px solid rgba(0, 0, 0, 0.15);
  background: var(--color-verified);
  box-shadow: 0 2px 10px rgba(45, 212, 191, 0.35);
  transition: box-shadow 0.2s, transform 0.15s;
}

/* ── Confidence level fills (normal alarm state) ─────────── */
.topo-node.inferred .topo-node-circle {
  background: var(--color-inferred);
  box-shadow: 0 2px 8px rgba(251, 191, 36, 0.3);
}

.topo-node.suspect .topo-node-circle {
  background: var(--color-bg3);
  border-color: var(--color-border);
  box-shadow: none;
}

/* ── Alarm state overrides (take priority over confidence) ── */
.topo-node.warning .topo-node-circle {
  background: var(--color-warn);
  box-shadow: 0 2px 12px rgba(251, 191, 36, 0.45);
  animation: warning-pulse 2.5s ease-in-out infinite;
}

.topo-node.critical .topo-node-circle {
  background: var(--color-error);
  box-shadow: 0 2px 14px rgba(248, 113, 113, 0.5);
  animation: critical-pulse 1.1s ease-in-out infinite;
}

.topo-node.pending-approval .topo-node-circle {
  background: #a855f7;
  box-shadow: 0 2px 12px rgba(168, 85, 247, 0.45);
  animation: approval-pulse 2s ease-in-out infinite;
}

/* ── Active / hover ──────────────────────────────────────── */
.topo-node:hover .topo-node-circle {
  box-shadow: 0 0 0 4px rgba(255, 255, 255, 0.18), 0 2px 10px rgba(45, 212, 191, 0.35);
  transform: scale(1.06);
}

.topo-node.inferred:hover .topo-node-circle {
  box-shadow: 0 0 0 4px rgba(255, 255, 255, 0.18), 0 2px 8px rgba(251, 191, 36, 0.3);
}

.topo-node.warning:hover .topo-node-circle {
  box-shadow: 0 0 0 4px rgba(255, 255, 255, 0.18), 0 2px 12px rgba(251, 191, 36, 0.45);
}

.topo-node.critical:hover .topo-node-circle {
  box-shadow: 0 0 0 4px rgba(255, 255, 255, 0.18), 0 2px 14px rgba(248, 113, 113, 0.5);
}

.topo-node.active .topo-node-circle {
  box-shadow: 0 0 0 5px rgba(255, 255, 255, 0.25), 0 2px 10px rgba(45, 212, 191, 0.35);
  animation: node-pulse 1.8s ease-in-out infinite;
}

.topo-node.save-flash .topo-node-circle {
  animation: save-flash 0.6s ease-out;
}

/* ── Labels ──────────────────────────────────────────────── */
.topo-node-label {
  font-size: 11px;
  font-weight: 600;
  font-family: var(--mono);
  color: var(--color-verified);
  text-align: center;
  white-space: nowrap;
}

.topo-node.inferred .topo-node-label  { color: var(--color-inferred); }
.topo-node.suspect .topo-node-label   { color: var(--color-text2); }
.topo-node.warning .topo-node-label   { color: var(--color-warn); }
.topo-node.critical .topo-node-label  { color: var(--color-error); }
.topo-node.pending-approval .topo-node-label { color: #a855f7; }

.topo-node-type {
  font-size: 9px;
  color: var(--color-text2);
  font-family: var(--mono);
  text-align: center;
}

.node-memory {
  font-size: 9px;
  color: var(--color-verified);
  font-family: var(--mono);
  text-align: center;
  margin-top: -3px;
  letter-spacing: 0.03em;
}
</style>
