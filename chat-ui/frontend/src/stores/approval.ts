import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useUIStore } from '@/stores/ui'
import { useTopologyStore } from '@/stores/topology'
import { authFetch } from '@/lib/api'

export interface PendingApproval {
  id: string
  nodeId: string
  specialist: string
  action: string
  impact: string
  error?: string
}

export interface BackendActionProposal {
  type: 'action_proposed'
  action_id: string
  description: string
  action_type: string
  target: string
  attribute: string
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
    const attributeSuffix = event.attribute ? `.${event.attribute}` : ''
    push({
      id: event.action_id,
      nodeId: event.target,
      specialist: node?.specialist ?? 'System',
      action: event.description,
      impact: `${event.action_type}: ${event.target}${attributeSuffix} → ${event.value}`,
    })
    const ui = useUIStore()
    ui.approvalOpen = true
  }

  async function resolve(id: string, decision: 'approve' | 'deny') {
    const item = queue.value.find(a => a.id === id)
    if (!item) return

    try {
      const res = await authFetch('/api/action/respond', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action_id: id,
          decision: decision === 'approve' ? 'approved' : 'denied',
        }),
      })
      if (!res.ok) {
        throw new Error(`${res.status} ${await res.text()}`)
      }
    } catch (e) {
      // Backend didn't confirm the decision — keep the item in the queue and
      // surface the failure instead of silently dequeuing it. A dropped POST
      // here previously left the operator believing an action went through
      // (or was denied) while the backend future stayed pending, un-acted-on,
      // until it timed out 300s later.
      item.error = e instanceof Error ? e.message : String(e)
      return
    }

    queue.value = queue.value.filter(a => a.id !== id)
    const ui = useUIStore()
    ui.approvalOpen = queue.value.length > 0
    // Don't touch activeNodeId — leave the operator's current view undisturbed.
    // The backend processes the decision; SSE continuation flows into the open panel if it's
    // the same node, or is silently consumed if the operator has moved elsewhere.
  }

  function dismiss(id: string) {
    // Closing without an explicit choice is treated as a denial so the
    // backend future resolves immediately instead of riding out the 300s
    // timeout with the panel gone and no visible pending state.
    void resolve(id, 'deny')
  }

  return { queue, current, hasPending, push, pushFromBackend, resolve, dismiss }
})
