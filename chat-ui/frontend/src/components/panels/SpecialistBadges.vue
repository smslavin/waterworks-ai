<script setup lang="ts">
import { computed } from 'vue'
import { useChatStore, type SpecialistInfo } from '@/stores/chat'

const props = defineProps<{ streamKey: string }>()
const chat = useChatStore()

const specs = computed(() => chat.specialists[props.streamKey] ?? {})
const hasSpecs = computed(() => Object.keys(specs.value).length > 0)

function chipClass(info: SpecialistInfo): string {
  if (!info.done) return 'chip-running'
  switch (info.status) {
    case 'Normal':            return 'chip-normal'
    case 'Anomaly Detected':  return 'chip-anomaly'
    case 'Fault Detected':    return 'chip-fault'
    default:                  return 'chip-unknown'
  }
}
</script>

<template>
  <div v-if="hasSpecs" class="specialist-badges">
    <span class="diag-label">MULTI-AGENT DIAGNOSTIC</span>
    <div class="chips">
      <span
        v-for="(info, name) in specs"
        :key="name"
        class="chip"
        :class="chipClass(info)"
      >
        {{ name }}
        <span v-if="info.done && info.confidence !== null" class="chip-conf">
          {{ Math.round((info.confidence ?? 0) * 100) }}%
        </span>
        <span v-else class="chip-dot" />
      </span>
    </div>
  </div>
</template>

<style scoped>
.specialist-badges {
  padding: 8px 16px;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-shrink: 0;
}

.diag-label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: var(--color-text2);
  text-transform: uppercase;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  border: 1px solid;
}

.chip-running {
  color: var(--color-text2);
  border-color: var(--color-border);
  background: transparent;
}

.chip-normal {
  color: var(--color-ok);
  border-color: rgba(74, 222, 128, 0.3);
  background: rgba(74, 222, 128, 0.06);
}

.chip-anomaly {
  color: var(--color-warn);
  border-color: rgba(251, 191, 36, 0.3);
  background: rgba(251, 191, 36, 0.06);
}

.chip-fault {
  color: var(--color-error);
  border-color: rgba(248, 113, 113, 0.3);
  background: rgba(248, 113, 113, 0.06);
}

.chip-unknown {
  color: var(--color-text2);
  border-color: var(--color-border);
  background: transparent;
}

.chip-conf {
  opacity: 0.85;
}

.chip-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  animation: blink 1s step-end infinite;
}
</style>
