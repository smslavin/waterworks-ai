<script setup lang="ts">
import { computed } from 'vue'
import { useUIStore } from '@/stores/ui'

const ui = useUIStore()
const visible = computed(() => ui.activeFlyout !== null)

const HEALTH_SERVICES = [
  { name: 'mqtt-mcp',        port: 8001 },
  { name: 'opcua-mcp',       port: 8002 },
  { name: 'influxdb-mcp',    port: 8003 },
  { name: 'audit-mcp',       port: 8004 },
  { name: 'control-mcp',     port: 8005 },
  { name: 'memory-mcp',      port: 8006 },
  { name: 'topology-builder', port: 8007 },
  { name: 'mcp-aggregator',  port: 8100 },
]
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
          {{ ui.activeFlyout === 'notif'  ? 'Notifications'   :
             ui.activeFlyout === 'health' ? 'Service Health'   :
             ui.activeFlyout === 'faults' ? 'Fault Injection'  :
                                            'Audit Log' }}
        </span>
        <button class="flyout-close" @click.stop="ui.closeFlyout()">✕</button>
      </div>

      <!-- Notifications -->
      <div v-if="ui.activeFlyout === 'notif'" class="flyout-body">
        <div class="flyout-empty">No reactive alerts</div>
        <p class="flyout-hint">
          Reactive monitoring is watching MQTT streams. Alerts will appear here when
          deadband thresholds are exceeded.
        </p>
      </div>

      <!-- Health -->
      <div v-else-if="ui.activeFlyout === 'health'" class="flyout-body">
        <div
          v-for="svc in HEALTH_SERVICES"
          :key="svc.name"
          class="health-row"
        >
          <span class="health-dot ok" />
          <span class="health-name">{{ svc.name }}</span>
          <span class="health-port">:{{ svc.port }}</span>
        </div>
        <p class="flyout-hint">Live status wired in Phase 7.</p>
      </div>

      <!-- Faults -->
      <div v-else-if="ui.activeFlyout === 'faults'" class="flyout-body">
        <p class="flyout-hint">
          Inject faults via <code>POST /fault?target=&lt;node&gt;&amp;mode=&lt;fault&gt;</code>
          on port 8090.
        </p>
        <p class="flyout-hint">Interactive injection panel wired in Phase 7.</p>
      </div>

      <!-- Audit -->
      <div v-else-if="ui.activeFlyout === 'audit'" class="flyout-body">
        <div class="flyout-empty">No sessions this run</div>
        <p class="flyout-hint">
          Audit entries appear here after AI interactions. Full log at
          <code>chat-ui/audit.jsonl</code>.
        </p>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.strip-flyout {
  position: absolute;
  left: 48px;
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
}

.flyout-title {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--color-text1);
}

.flyout-close {
  background: transparent;
  border: none;
  color: var(--color-text2);
  font-size: 12px;
  cursor: pointer;
  padding: 2px 4px;
  transition: color 0.12s;
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

.flyout-hint code {
  font-family: var(--font-mono);
  background: var(--color-bg3);
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 10px;
}

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
