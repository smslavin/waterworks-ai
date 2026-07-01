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

const selectedId = ref('')
const note = ref('')
const noteVisible = ref(false)

watch(() => props.nodeId, () => {
  emit('update:open', false)
  selectedId.value = ''
  note.value = ''
  noteVisible.value = false
})

function selectChip(id: string) {
  selectedId.value = id
  noteVisible.value = true
}

function commitSave() {
  if (!selectedId.value) return
  topo.saveInsight(props.nodeId, selectedId.value, note.value || undefined)
  selectedId.value = ''
  note.value = ''
  noteVisible.value = false
  emit('update:open', false)
}
</script>

<template>
  <Transition name="classify">
    <div v-if="open" class="save-classify">
      <div class="save-classify-label">
        Save as · <span class="save-classify-node">{{ nodeId }}</span>
      </div>
      <div class="save-chips">
        <button
          v-for="cat in topo.insightCategories"
          :key="cat.id"
          class="chip"
          :class="{ selected: selectedId === cat.id }"
          @click="selectChip(cat.id)"
        >{{ cat.label }}</button>
      </div>
      <Transition name="note-slide">
        <div v-if="noteVisible" class="save-confirm-row">
          <input
            v-model="note"
            class="save-annotation"
            placeholder="Note (optional)"
            autofocus
          />
          <button
            class="save-confirm-btn ready"
            @click="commitSave"
          >
            Save
          </button>
        </div>
      </Transition>
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

.save-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.chip {
  padding: 4px 10px;
  border-radius: 20px;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text2);
  font-size: 12px;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}

.chip:hover {
  border-color: var(--color-text2);
  color: var(--color-text1);
}

.chip.selected {
  border-color: var(--color-verified);
  color: var(--color-verified);
  background: rgba(45, 212, 191, 0.1);
}

.save-confirm-row {
  display: flex;
  gap: 6px;
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

.note-slide-enter-active,
.note-slide-leave-active {
  transition: opacity 0.15s, transform 0.15s;
}

.note-slide-enter-from,
.note-slide-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
