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

const pendingClassification = ref<string | null>(null)
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
  pendingClassification.value = null
  note.value = ''
})

function selectClassification(cls: string) {
  pendingClassification.value = cls
}

function commitSave() {
  if (!pendingClassification.value) return
  topo.saveInsight(props.nodeId)
  pendingClassification.value = null
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
      <div class="classify-chips">
        <button
          v-for="cls in CLASSIFICATIONS"
          :key="cls"
          class="classify-chip"
          :class="{ selected: pendingClassification === cls }"
          @click="selectClassification(cls)"
        >
          {{ cls }}
        </button>
      </div>
      <div class="save-confirm-row">
        <input
          v-model="note"
          class="save-annotation"
          placeholder="Add a note (optional)"
        />
        <button
          class="save-confirm-btn"
          :class="{ ready: pendingClassification !== null }"
          :disabled="pendingClassification === null"
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

.classify-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.classify-chip {
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text2);
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}

.classify-chip:hover {
  border-color: var(--color-accent);
  color: var(--color-text1);
}

.classify-chip.selected {
  border-color: var(--color-verified);
  color: var(--color-verified);
  background: rgba(45, 212, 191, 0.1);
}

.save-confirm-row {
  display: flex;
  gap: 8px;
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
