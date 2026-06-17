<script setup lang="ts">
import { ref, onUnmounted } from 'vue'

type DiscoverState = 'idle' | 'discovering' | 'done'

const discoverState = ref<DiscoverState>('idle')
const discoveredCount = ref(0)
let discoverTimer: ReturnType<typeof setTimeout> | null = null

onUnmounted(() => { if (discoverTimer !== null) clearTimeout(discoverTimer) })

function startDiscover() {
  if (discoverState.value === 'discovering') return
  discoverState.value = 'discovering'
  discoveredCount.value = 0
  discoverTimer = setTimeout(() => {
    discoveredCount.value = 3
    discoverState.value = 'done'
    discoverTimer = null
  }, 2200)
}

function commit() {
  discoverState.value = 'idle'
  discoveredCount.value = 0
}
</script>

<template>
  <div class="config-toolbar">
    <div class="toolbar-left">
      <button
        class="discover-btn"
        :class="{ discovering: discoverState === 'discovering' }"
        :disabled="discoverState === 'discovering'"
        @click="startDiscover"
      >
        <span v-if="discoverState === 'discovering'" class="discover-spinner" />
        <svg v-else width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        {{ discoverState === 'discovering' ? 'Discovering…' : 'Discover' }}
      </button>

      <Transition name="badge">
        <span v-if="discoverState === 'done'" class="discovered-badge">
          {{ discoveredCount }} nodes found
        </span>
      </Transition>
    </div>

    <div class="toolbar-right">
      <span class="toolbar-legend">
        <span class="legend-dot verified" />verified
        <span class="legend-dot inferred" />inferred
        <span class="legend-dot suspect" />suspect
      </span>
      <button class="commit-btn" @click="commit">
        Commit Topology
      </button>
    </div>
  </div>
</template>

<style scoped>
.config-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 20px;
  background: #0d0d18;
  border-bottom: 1px solid rgba(99, 102, 241, 0.25);
  flex-shrink: 0;
}

.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.discover-btn {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 16px;
  border-radius: 7px;
  border: 1px solid var(--color-config);
  background: transparent;
  color: var(--color-config);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
  animation: none;
}

.discover-btn:not(:disabled):hover {
  background: rgba(99, 102, 241, 0.1);
}

.discover-btn.discovering {
  animation: cfg-pulse 1.4s ease-in-out infinite;
}

.discover-btn:disabled {
  cursor: default;
}

.discover-spinner {
  width: 11px;
  height: 11px;
  border: 2px solid rgba(99, 102, 241, 0.3);
  border-top-color: var(--color-config);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  flex-shrink: 0;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.discovered-badge {
  font-size: 11px;
  color: var(--color-ok);
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(74, 222, 128, 0.1);
  border: 1px solid rgba(74, 222, 128, 0.3);
}

.toolbar-legend {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--color-text2);
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.legend-dot.verified { background: var(--color-verified); }
.legend-dot.inferred { background: var(--color-warn); }
.legend-dot.suspect  { background: var(--color-border); }

.commit-btn {
  padding: 7px 16px;
  border-radius: 7px;
  border: 1px solid rgba(99, 102, 241, 0.4);
  background: rgba(99, 102, 241, 0.1);
  color: var(--color-text1);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}

.commit-btn:hover {
  border-color: var(--color-config);
  background: rgba(99, 102, 241, 0.18);
}

.badge-enter-active,
.badge-leave-active {
  transition: opacity 0.2s, transform 0.2s;
}

.badge-enter-from,
.badge-leave-to {
  opacity: 0;
  transform: translateX(-6px);
}
</style>
