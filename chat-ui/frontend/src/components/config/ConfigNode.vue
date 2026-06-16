<script setup lang="ts">
import { computed } from 'vue'
import type { TopologyNode } from '@/stores/topology'

const props = defineProps<{ node: TopologyNode }>()

const circleSizePx = computed(() => {
  const map = { verified: 36, inferred: 30, suspect: 24 } as const
  return map[props.node.confidenceLevel] ?? 30
})

const confidenceLetter = computed(() => {
  const map = { verified: 'V', inferred: 'I', suspect: 'S' } as const
  return map[props.node.confidenceLevel] ?? '?'
})
</script>

<template>
  <div class="config-node" :class="node.confidenceLevel">
    <div
      class="config-node-circle"
      :style="{ width: `${circleSizePx}px`, height: `${circleSizePx}px` }"
    >
      <span class="config-node-confidence">{{ confidenceLetter }}</span>
    </div>
    <div class="config-node-label">{{ node.id }}</div>
    <div class="config-node-type">{{ node.equipmentType }}</div>
  </div>
</template>

<style scoped>
.config-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  padding: 10px 8px;
  border-radius: 8px;
  transition: background 0.15s;
  animation: node-reveal 0.3s ease;
}

.config-node:hover {
  background: rgba(99, 102, 241, 0.06);
}

.config-node-circle {
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.config-node.verified  .config-node-circle { background: rgba(45, 212, 191, 0.2); border: 2px solid var(--color-verified); }
.config-node.inferred  .config-node-circle { background: rgba(251, 191, 36, 0.15); border: 2px solid var(--color-warn); border-style: dashed; }
.config-node.suspect   .config-node-circle { background: rgba(99, 102, 241, 0.1); border: 2px solid rgba(99, 102, 241, 0.4); border-style: dashed; }

.config-node-confidence {
  font-size: 10px;
  font-weight: 700;
}

.config-node.verified  .config-node-confidence { color: var(--color-verified); }
.config-node.inferred  .config-node-confidence { color: var(--color-warn); }
.config-node.suspect   .config-node-confidence { color: var(--color-config); }

.config-node-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text1);
  font-family: var(--font-mono);
  text-align: center;
}

.config-node-type {
  font-size: 10px;
  color: var(--color-text2);
  text-align: center;
}
</style>
