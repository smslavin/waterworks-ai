<script setup lang="ts">
import { computed } from 'vue'
import { useUIStore } from '@/stores/ui'
import { useApprovalStore } from '@/stores/approval'

const ui = useUIStore()
const approvals = useApprovalStore()

const visible = computed(() => ui.approvalOpen && approvals.hasPending)
const approval = computed(() => approvals.current)

async function approve() {
  if (!approval.value) return
  await approvals.resolve(approval.value.id, 'approve')
}

async function deny() {
  if (!approval.value) return
  await approvals.resolve(approval.value.id, 'deny')
}
</script>

<template>
  <Transition name="approval-panel">
    <div
      v-if="visible && approval"
      class="approval-panel"
      @click.stop
    >
      <div class="approval-header">
        <span class="approval-badge">Pending Approval</span>
        <!-- Always this plant's own site — an operator with multiple plants
             open in different tabs needs this to confirm which plant's
             control-mcp a setpoint change actually targets. See M10 Phase 4. -->
        <span class="approval-site">{{ ui.activeSite }}</span>
        <button class="approval-close" @click="ui.approvalOpen = false">✕</button>
      </div>

      <div class="approval-body">
        <div class="approval-node-row">
          <span class="approval-node">{{ approval.nodeId }}</span>
          <span class="approval-specialist">{{ approval.specialist }} Specialist</span>
        </div>

        <div class="approval-action">
          "{{ approval.action }}"
        </div>

        <div class="approval-impact">
          {{ approval.impact }}
        </div>
      </div>

      <div class="approval-footer">
        <button class="deny-btn" @click="deny">Deny</button>
        <button class="approve-btn" @click="approve">Approve</button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.approval-panel {
  position: absolute;
  bottom: 12px;
  left: 12px;
  width: 300px;
  background: var(--color-bg2);
  border: 1px solid #a855f7;
  border-radius: 12px;
  z-index: 60;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(168, 85, 247, 0.2);
}

.approval-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid rgba(168, 85, 247, 0.3);
  background: rgba(168, 85, 247, 0.06);
}

.approval-badge {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #a855f7;
  animation: approval-pill-pulse 2s ease-in-out infinite;
}

.approval-site {
  font-size: 10px;
  font-weight: 600;
  color: var(--color-text2);
  white-space: nowrap;
  margin-left: auto;
  margin-right: 8px;
}

.approval-close {
  background: transparent;
  border: none;
  color: var(--color-text2);
  font-size: 12px;
  cursor: pointer;
  padding: 2px 4px;
  transition: color 0.12s;
}

.approval-close:hover {
  color: var(--color-text1);
}

.approval-body {
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.approval-node-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.approval-node {
  font-size: 14px;
  font-weight: 600;
  font-family: var(--font-mono);
  color: var(--color-text1);
}

.approval-specialist {
  font-size: 11px;
  color: var(--color-text2);
}

.approval-action {
  font-size: 13px;
  color: var(--color-text1);
  font-style: italic;
  line-height: 1.5;
  padding: 8px 10px;
  background: var(--color-bg3);
  border-radius: 6px;
  border-left: 3px solid #a855f7;
}

.approval-impact {
  font-size: 12px;
  color: var(--color-text2);
  line-height: 1.6;
}

.approval-footer {
  display: flex;
  gap: 8px;
  padding: 10px 14px;
  border-top: 1px solid var(--color-border);
}

.deny-btn {
  flex: 1;
  padding: 8px;
  border-radius: 7px;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text2);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
}

.deny-btn:hover {
  border-color: var(--color-error);
  color: var(--color-error);
}

.approve-btn {
  flex: 1;
  padding: 8px;
  border-radius: 7px;
  border: 1px solid #a855f7;
  background: rgba(168, 85, 247, 0.1);
  color: #a855f7;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}

.approve-btn:hover {
  background: rgba(168, 85, 247, 0.2);
}

.approval-panel-enter-active,
.approval-panel-leave-active {
  transition: opacity 0.2s, transform 0.2s;
}

.approval-panel-enter-from,
.approval-panel-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
