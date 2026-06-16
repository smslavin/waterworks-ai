<script setup lang="ts">
import { useUIStore } from '@/stores/ui'
import ConfigHeader from './ConfigHeader.vue'
import ConfigToolbar from './ConfigToolbar.vue'
import ConfigCanvas from './ConfigCanvas.vue'

const ui = useUIStore()
</script>

<template>
  <Transition name="config">
    <div v-if="ui.configMode" class="config-shell">
      <ConfigHeader />
      <ConfigToolbar />
      <ConfigCanvas />
    </div>
  </Transition>
</template>

<style scoped>
.config-shell {
  position: fixed;
  inset: 0;
  z-index: 200;
  display: flex;
  flex-direction: column;
  background: #0a0a14;
  overflow: hidden;
}

.config-enter-active,
.config-leave-active {
  transition: opacity 0.28s ease;
}

.config-enter-from,
.config-leave-to {
  opacity: 0;
}
</style>
