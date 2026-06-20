<script setup lang="ts">
import { computed, ref, watch, onMounted } from 'vue'
import { useUIStore } from '@/stores/ui'
import { useTopologyStore } from '@/stores/topology'
import { useAlarmStore } from '@/stores/alarm'

const ui = useUIStore()
const topo = useTopologyStore()
const alarm = useAlarmStore()

// ── Models ────────────────────────────────────────────────────────────────────

const cloudModels = ref<string[]>([])
const localModels = ref<string[]>([])
const modelsLoaded = ref(false)

function shortModelName(m: string): string {
  if (m.includes('opus'))   return 'Opus'
  if (m.includes('sonnet')) return 'Sonnet'
  if (m.includes('haiku'))  return 'Haiku'
  return m
}

onMounted(async () => {
  try {
    const data = await fetch('/api/models').then(r => r.json()) as { cloud: string[]; local: string[] }
    cloudModels.value = data.cloud ?? []
    localModels.value = data.local ?? []
    if (!ui.selectedModel && cloudModels.value.length) {
      ui.selectedModel = cloudModels.value[0]
    }
  } catch { /* backend offline */ }
  modelsLoaded.value = true
})
const visible = computed(() => ui.activeFlyout !== null)

// ── Health ────────────────────────────────────────────────────────────────────

type HealthStatus = 'ok' | 'error' | 'loading'

const HEALTH_SERVICES = [
  { key: 'aggregator',  name: 'mcp-aggregator', port: 8100 },
  { key: 'influxdb',    name: 'influxdb',        port: 8086 },
  { key: 'mqtt',        name: 'mosquitto',       port: 1883 },
  { key: 'simulator',   name: 'simulator',       port: 8090 },
  { key: 'audit_mcp',   name: 'audit-mcp',       port: 8004 },
  { key: 'control_mcp', name: 'control-mcp',     port: 8005 },
  { key: 'memory_mcp',  name: 'memory-mcp',      port: 8006 },
]

const healthData = ref<Record<string, HealthStatus>>({})

watch(() => ui.activeFlyout, async (key) => {
  if (key !== 'health') return
  HEALTH_SERVICES.forEach(s => { healthData.value[s.key] = 'loading' })
  try {
    const resp = await fetch('/api/health')
    if (!resp.ok) throw new Error(`${resp.status}`)
    const data = await resp.json() as Record<string, string>
    HEALTH_SERVICES.forEach(s => {
      healthData.value[s.key] = data[s.key] === 'ok' ? 'ok' : 'error'
    })
  } catch {
    HEALTH_SERVICES.forEach(s => { healthData.value[s.key] = 'error' })
  }
})

// ── Faults ────────────────────────────────────────────────────────────────────

const faultStatus = ref<Record<string, string>>({})   // instance → current mode
const faultModes  = ref<Record<string, string[]>>({}) // instance → available modes
const faultLoading = ref(false)

watch(() => ui.activeFlyout, async (key) => {
  if (key !== 'faults') return
  faultLoading.value = true
  try {
    const [statusResp, modesResp] = await Promise.all([
      fetch('/api/fault/status'),
      fetch('/api/fault/modes'),
    ])
    if (statusResp.ok) faultStatus.value = await statusResp.json() as Record<string, string>
    if (modesResp.ok)  faultModes.value  = await modesResp.json()  as Record<string, string[]>
  } catch { /* simulator offline */ }
  faultLoading.value = false
})

async function injectFault(target: string, mode: string) {
  faultStatus.value[target] = mode  // optimistic
  topo.setAlarmState(target, mode === 'normal' ? 'normal' : 'critical')
  if (mode === 'normal') {
    alarm.acknowledge(target)
  } else {
    alarm.addAlarm({
      id: target,
      nodeId: target,
      severity: 'critical',
      message: mode.replace(/_/g, ' '),
      timestamp: new Date().toISOString(),
    })
  }
  try {
    await fetch('/api/fault', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target, mode }),
    })
  } catch { /* ignore — status already updated optimistically */ }
}

const faultInstances = computed(() => Object.keys(faultStatus.value))
const activeFaultCount = computed(() =>
  Object.values(faultStatus.value).filter(m => m !== 'normal').length
)
</script>

<template>
  <Transition name="flyout">
    <div
      v-if="visible"
      class="strip-flyout"
      @click.stop
    >
      <div class="flyout-header">
        <span class="flyout-title">
          {{ ui.activeFlyout === 'notif'    ? 'Notifications'  :
             ui.activeFlyout === 'health'   ? 'Service Health'  :
             ui.activeFlyout === 'settings' ? 'Settings'        :
                                              'Fault Injection' }}
        </span>
        <span
          v-if="ui.activeFlyout === 'faults' && activeFaultCount > 0"
          class="fault-count-badge"
        >{{ activeFaultCount }} active</span>
        <button class="flyout-close" @click.stop="ui.closeFlyout()">✕</button>
      </div>

      <!-- Notifications -->
      <div v-if="ui.activeFlyout === 'notif'" class="flyout-body notif-body">
        <div v-if="alarm.alarms.length === 0" class="flyout-empty">No active alerts</div>
        <div
          v-for="a in [...alarm.alarms].reverse()"
          :key="a.id"
          class="notif-row"
          :class="a.severity"
          @click.stop="ui.setActiveNode(a.nodeId); ui.closeFlyout()"
        >
          <div class="notif-top">
            <span class="notif-severity" :class="a.severity">{{ a.severity }}</span>
            <span class="notif-node">{{ a.nodeId }}</span>
            <button class="notif-ack" @click.stop="alarm.acknowledge(a.id)">ACK</button>
          </div>
          <div class="notif-message">{{ a.message }}</div>
        </div>
      </div>

      <!-- Health -->
      <div v-else-if="ui.activeFlyout === 'health'" class="flyout-body">
        <div
          v-for="svc in HEALTH_SERVICES"
          :key="svc.key"
          class="health-row"
        >
          <span
            class="health-dot"
            :class="healthData[svc.key] === 'ok' ? 'ok' : healthData[svc.key] === 'error' ? 'err' : 'warn'"
          />
          <span class="health-name">{{ svc.name }}</span>
          <span class="health-port">:{{ svc.port }}</span>
        </div>
      </div>

      <!-- Settings -->
      <div v-else-if="ui.activeFlyout === 'settings'" class="flyout-body settings-body">
        <div class="settings-label">Model</div>
        <div v-if="!modelsLoaded" class="flyout-empty">Loading…</div>
        <template v-else>
          <div v-if="cloudModels.length">
            <div class="settings-group">Cloud</div>
            <div
              v-for="m in cloudModels"
              :key="m"
              class="model-row"
              :class="{ selected: ui.selectedModel === m }"
              @click="ui.selectedModel = m"
            >
              <span class="model-dot" :class="{ active: ui.selectedModel === m }" />
              <span class="model-name">{{ shortModelName(m) }}</span>
              <span class="model-id">{{ m }}</span>
            </div>
          </div>
          <div v-if="localModels.length" :class="{ 'settings-gap': cloudModels.length }">
            <div class="settings-group">Local</div>
            <div
              v-for="m in localModels"
              :key="m"
              class="model-row"
              :class="{ selected: ui.selectedModel === m }"
              @click="ui.selectedModel = m"
            >
              <span class="model-dot" :class="{ active: ui.selectedModel === m }" />
              <span class="model-name">{{ m }}</span>
            </div>
          </div>
          <div v-if="!cloudModels.length && !localModels.length" class="flyout-empty">
            No models available
          </div>
        </template>
      </div>

      <!-- Faults -->
      <div v-else-if="ui.activeFlyout === 'faults'" class="flyout-body fault-body">
        <div v-if="faultLoading" class="flyout-empty">Loading…</div>
        <template v-else-if="faultInstances.length > 0">
          <div
            v-for="instance in faultInstances"
            :key="instance"
            class="fault-row"
            :class="{ 'fault-active': faultStatus[instance] !== 'normal' }"
          >
            <span class="fault-instance">{{ instance }}</span>
            <select
              class="fault-select"
              :class="{ 'fault-select-active': faultStatus[instance] !== 'normal' }"
              :value="faultStatus[instance]"
              @change="injectFault(instance, ($event.target as HTMLSelectElement).value)"
            >
              <option
                v-for="mode in (faultModes[instance] ?? ['normal'])"
                :key="mode"
                :value="mode"
              >{{ mode }}</option>
            </select>
          </div>
        </template>
        <div v-else class="flyout-empty">Simulator offline</div>
      </div>

    </div>
  </Transition>
</template>

<style scoped>
.strip-flyout {
  position: absolute;
  left: 0;
  top: 0;
  width: 260px;
  height: 100%;
  background: var(--color-bg2);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  z-index: 40;
  overflow: hidden;
}

.flyout-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
  gap: 8px;
}

.flyout-title {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--color-text1);
  flex: 1;
}

.fault-count-badge {
  font-size: 10px;
  font-weight: 700;
  background: var(--color-warn);
  color: #000;
  border-radius: 999px;
  padding: 1px 7px;
}

.flyout-close {
  background: transparent;
  border: none;
  color: var(--color-text2);
  font-size: 12px;
  cursor: pointer;
  padding: 2px 4px;
  transition: color 0.12s;
  flex-shrink: 0;
}

.flyout-close:hover {
  color: var(--color-text1);
}

.flyout-body {
  flex: 1;
  overflow-y: auto;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.flyout-empty {
  font-size: 12px;
  color: var(--color-text2);
  font-style: italic;
}

.flyout-hint {
  font-size: 11px;
  color: var(--color-text2);
  line-height: 1.6;
  margin: 0;
}

/* Notifications */
.notif-body {
  padding: 8px 10px;
  gap: 3px;
}

.notif-row {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 7px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.12s;
  border-left: 2px solid transparent;
}

.notif-row.critical {
  border-left-color: var(--color-error);
  background: rgba(248, 113, 113, 0.05);
}

.notif-row.warning {
  border-left-color: var(--color-warn);
  background: rgba(251, 191, 36, 0.04);
}

.notif-row:hover {
  background: var(--color-bg3);
}

.notif-top {
  display: flex;
  align-items: center;
  gap: 6px;
}

.notif-severity {
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 1px 5px;
  border-radius: 3px;
  flex-shrink: 0;
}

.notif-severity.critical {
  background: rgba(248, 113, 113, 0.15);
  color: var(--color-error);
}

.notif-severity.warning {
  background: rgba(251, 191, 36, 0.15);
  color: var(--color-warn);
}

.notif-node {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text1);
  flex: 1;
}

.notif-message {
  font-size: 11px;
  color: var(--color-text2);
  line-height: 1.4;
  padding-left: 2px;
}

.notif-ack {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 2px 6px;
  border-radius: 3px;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text2);
  cursor: pointer;
  flex-shrink: 0;
  transition: border-color 0.12s, color 0.12s;
}

.notif-ack:hover {
  border-color: var(--color-ok);
  color: var(--color-ok);
}

/* Settings */
.settings-body {
  padding: 12px 12px;
  gap: 4px;
}

.settings-label {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--color-text2);
  margin-bottom: 6px;
}

.settings-group {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-text2);
  padding: 2px 4px;
  margin-bottom: 2px;
}

.settings-gap {
  margin-top: 12px;
}

.model-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.12s;
  border: 1px solid transparent;
}

.model-row:hover {
  background: var(--color-bg3);
}

.model-row.selected {
  background: rgba(59, 130, 246, 0.08);
  border-color: rgba(59, 130, 246, 0.25);
}

.model-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  border: 1.5px solid var(--color-border);
  flex-shrink: 0;
  transition: background 0.12s, border-color 0.12s;
}

.model-dot.active {
  background: var(--color-accent);
  border-color: var(--color-accent);
}

.model-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text1);
  flex-shrink: 0;
}

.model-id {
  font-size: 10px;
  color: var(--color-text2);
  font-family: var(--font-mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Health */
.health-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 3px 0;
}

.health-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.health-dot.ok   { background: var(--color-ok); }
.health-dot.warn { background: var(--color-warn); }
.health-dot.err  { background: var(--color-error); }

.health-name {
  font-family: var(--font-mono);
  color: var(--color-text1);
  flex: 1;
  font-size: 11px;
}

.health-port {
  color: var(--color-text2);
  font-size: 11px;
  font-family: var(--font-mono);
}

/* Faults */
.fault-body {
  padding: 10px 12px;
  gap: 4px;
}

.fault-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 6px;
  border-radius: 6px;
  transition: background 0.12s;
}

.fault-row:hover {
  background: var(--color-bg3);
}

.fault-row.fault-active {
  background: rgba(251, 191, 36, 0.08);
}

.fault-instance {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-text2);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fault-row.fault-active .fault-instance {
  color: var(--color-warn);
}

.fault-select {
  font-size: 11px;
  font-family: var(--font-mono);
  background: var(--color-bg3);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  color: var(--color-text2);
  padding: 2px 4px;
  cursor: pointer;
  max-width: 110px;
  outline: none;
}

.fault-select:focus {
  border-color: var(--color-accent);
}

.fault-select.fault-select-active {
  border-color: var(--color-warn);
  color: var(--color-warn);
}

/* Flyout transition */
.flyout-enter-active,
.flyout-leave-active {
  transition: opacity 0.15s, transform 0.15s;
}

.flyout-enter-from,
.flyout-leave-to {
  opacity: 0;
  transform: translateX(-8px);
}
</style>
