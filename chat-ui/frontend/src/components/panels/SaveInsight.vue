<script setup lang="ts">
import { ref, watch } from 'vue'
import { useTopologyStore } from '@/stores/topology'

const props = defineProps<{
  nodeId: string
  streamDone: boolean
  open: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

const topo = useTopologyStore()

const pendingClassification = ref('')
const note = ref('')

const CLASSIFICATIONS = [
  'Fault pattern',
  'Maintenance flag',
  'False positive',
  'Baseline shift',
  'Operator note',
]

watch(() => props.nodeId, () => {
  emit('update:open', false)
  pendingClassification.value = ''
  note.value = ''
})

function commitSave() {
  if (!pendingClassification.value) return
  topo.saveInsight(props.nodeId, note.value || undefined)
  pendingClassification.value = ''
  note.value = ''
  emit('update:open', false)
}
</script>

<template>
  <Transition name="classify">
    <div v-if="open" class="save-classify">
      <div class="save-classify-label">
        Save as · <span class="save-classify-node">{{ nodeId }}</span>
      </div>
      <div class="save-confirm-row">
        <select v-model="pendingClassification" class="save-select">
          <option value="" disabled>Category...</option>
          <option v-for="cls in CLASSIFICATIONS" :key="cls" :value="cls">{{ cls }}</option>
        </select>
        <input
          v-model="note"
          class="save-annotation"
          placeholder="Note (optional)"
        />
        <button
          class="save-confirm-btn"
          :class="{ ready: pendingClassification !== '' }"
          :disabled="pendingClassification === ''"
          @click="commitSave"
        >
          Save
        </button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.save-classify {
  padding: 10px 14px;
  border-top: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.save-classify-label {
  font-size: 11px;
  color: var(--color-text2);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.save-classify-node {
  color: var(--color-text1);
  font-family: var(--font-mono);
}

.save-confirm-row {
  display: flex;
  gap: 6px;
}

.save-select {
  width: 130px;
  flex-shrink: 0;
  appearance: none;
  background: var(--color-bg3) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%23a1a1aa' stroke-width='1.5' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") no-repeat right 8px center;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 5px 24px 5px 10px;
  font-size: 12px;
  color: var(--color-text1);
  cursor: pointer;
  outline: none;
  transition: border-color 0.15s;
}

.save-select:focus {
  border-color: var(--color-accent);
}

.save-select option {
  background: var(--color-bg2);
  color: var(--color-text1);
}

.save-annotation {
  flex: 1;
  background: var(--color-bg3);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 5px 10px;
  font-size: 12px;
  color: var(--color-text1);
  outline: none;
}

.save-annotation:focus {
  border-color: var(--color-accent);
}

.save-confirm-btn {
  padding: 5px 14px;
  border-radius: 6px;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text2);
  font-size: 12px;
  font-weight: 600;
  cursor: default;
  opacity: 0.5;
  transition: opacity 0.15s, border-color 0.15s, color 0.15s, background 0.15s;
}

.save-confirm-btn.ready {
  cursor: pointer;
  opacity: 1;
  border-color: var(--color-verified);
  color: var(--color-verified);
}

.save-confirm-btn.ready:hover {
  background: rgba(45, 212, 191, 0.12);
}

.classify-enter-active,
.classify-leave-active {
  transition: opacity 0.15s, transform 0.15s;
}

.classify-enter-from,
.classify-leave-to {
  opacity: 0;
  transform: translateY(4px);
}
</style>
