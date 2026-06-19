import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useUIStore } from '@/stores/ui'
import { useTopologyStore } from '@/stores/topology'

export interface PendingApproval {
  id: string
  nodeId: string
  specialist: string
  action: string
  impact: string
}

export interface BackendActionProposal {
  type: 'action_proposed'
  action_id: string
  description: string
  action_type: string
  target: string
  value: string
}

export const useApprovalStore = defineStore('approval', () => {
  const queue = ref<PendingApproval[]>([])

  const current = computed(() => queue.value[0] ?? null)
  const hasPending = computed(() => queue.value.length > 0)

  function push(approval: PendingApproval) {
    if (!queue.value.find(a => a.id === approval.id)) {
      queue.value.push(approval)
    }
  }

  function pushFromBackend(event: BackendActionProposal) {
    const topo = useTopologyStore()
    const node = topo.nodeById(event.target)
    push({
      id: event.action_id,
      nodeId: event.target,
      specialist: node?.specialist ?? 'System',
      action: event.description,
      impact: `${event.action_type}: ${event.target} → ${event.value}`,
    })
    const ui = useUIStore()
    ui.approvalOpen = true
  }

  async function resolve(id: string, decision: 'approve' | 'deny') {
    const item = queue.value.find(a => a.id === id)
    if (!item) return

    try {
      await fetch('/api/action/respond', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action_id: id,
          decision: decision === 'approve' ? 'approved' : 'denied',
        }),
      })
    } catch { /* backend unreachable — still update UI */ }

    queue.value = queue.value.filter(a => a.id !== id)
    const ui = useUIStore()
    ui.approvalOpen = queue.value.length > 0
    // Don't touch activeNodeId — leave the operator's current view undisturbed.
    // The backend processes the decision; SSE continuation flows into the open panel if it's
    // the same node, or is silently consumed if the operator has moved elsewhere.
  }

  return { queue, current, hasPending, push, pushFromBackend, resolve }
})
