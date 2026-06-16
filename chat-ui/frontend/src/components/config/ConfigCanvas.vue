<script setup lang="ts">
import { useTopologyStore } from '@/stores/topology'
import { AREA_ORDER } from '@/stores/topology'
import ConfigNode from './ConfigNode.vue'

const topo = useTopologyStore()
</script>

<template>
  <div class="config-canvas">
    <div
      v-for="area in AREA_ORDER"
      :key="area"
      class="config-column"
    >
      <div class="config-column-label">{{ area }}</div>
      <div class="config-column-nodes">
        <ConfigNode
          v-for="node in topo.nodesByArea[area]"
          :key="node.id"
          :node="node"
        />
      </div>
    </div>

    <div class="config-canvas-hint">
      Nodes discovered from MQTT/OPC-UA topology inference.
      Confidence: <strong>V</strong>=verified &nbsp; <strong>I</strong>=inferred &nbsp; <strong>S</strong>=suspect
    </div>
  </div>
</template>

<style scoped>
.config-canvas {
  flex: 1;
  overflow-y: auto;
  display: flex;
  gap: 48px;
  padding: 32px 40px;
  align-items: flex-start;
  background: #0a0a14;
  position: relative;
}

.config-column {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  min-width: 160px;
}

.config-column-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-config);
  padding: 3px 14px;
  border-radius: 999px;
  border: 1px solid rgba(99, 102, 241, 0.35);
  margin-bottom: 8px;
}

.config-column-nodes {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.config-canvas-hint {
  position: absolute;
  bottom: 16px;
  right: 24px;
  font-size: 11px;
  color: var(--color-text2);
  line-height: 1.6;
  text-align: right;
}

.config-canvas-hint strong {
  color: var(--color-config);
}
</style>
