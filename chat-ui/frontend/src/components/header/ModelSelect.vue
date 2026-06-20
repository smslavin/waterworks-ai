<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useUIStore } from '@/stores/ui'

const ui = useUIStore()

interface ModelList {
  cloud: string[]
  local: string[]
}

const loading = ref(true)
const cloudModels = ref<string[]>([])
const localModels = ref<string[]>([])

function shortName(m: string): string {
  if (m.includes('opus'))   return 'Opus'
  if (m.includes('sonnet')) return 'Sonnet'
  if (m.includes('haiku'))  return 'Haiku'
  return m.split('-')[0] ?? m
}

onMounted(async () => {
  try {
    const data = await fetch('/api/models').then(r => r.json()) as ModelList
    cloudModels.value = data.cloud ?? []
    localModels.value = data.local ?? []
    if (!ui.selectedModel && cloudModels.value.length) {
      ui.selectedModel = cloudModels.value[0]
    }
  } catch { /* backend offline */ }
  loading.value = false
})
</script>

<template>
  <div class="model-select-wrap">
    <select
      v-model="ui.selectedModel"
      class="model-select"
      :disabled="loading"
      title="Model"
    >
      <option v-if="loading" value="">Loading…</option>
      <template v-else>
        <optgroup v-if="cloudModels.length" label="Cloud">
          <option v-for="m in cloudModels" :key="m" :value="m">{{ shortName(m) }}</option>
        </optgroup>
        <optgroup v-if="localModels.length" label="Local">
          <option v-for="m in localModels" :key="m" :value="m">{{ m }}</option>
        </optgroup>
        <option v-if="!cloudModels.length && !localModels.length" value="">No models</option>
      </template>
    </select>
  </div>
</template>

<style scoped>
.model-select-wrap {
  display: flex;
  align-items: center;
}

.model-select {
  appearance: none;
  background: var(--color-bg3) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%23a1a1aa' stroke-width='1.5' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") no-repeat right 7px center;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 3px 22px 3px 9px;
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text1);
  cursor: pointer;
  outline: none;
  height: 26px;
  transition: border-color 0.12s;
  min-width: 72px;
}

.model-select:hover {
  border-color: var(--color-text2);
}

.model-select:focus {
  border-color: var(--color-accent);
}

.model-select option,
.model-select optgroup {
  background: var(--color-bg2);
  color: var(--color-text1);
}

.model-select:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>
