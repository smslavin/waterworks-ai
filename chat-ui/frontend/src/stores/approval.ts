import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useUIStore } from '@/stores/ui'

export interface PendingApproval {
  id: string
  nodeId: string
  specialist: string
  action: string
  impact: string
}

const INITIAL_QUEUE: PendingApproval[] = [
  {
    id: 'ap1',
    nodeId: 'RawWater_01',
    specialist: 'Intake',
    action: 'Reduce pump speed by 15%',
    impact: 'Intake flow will decrease ~15%. Monitor bearing temperature for recovery over the next 5 minutes.',
  },
]

export const useApprovalStore = defineStore('approval', () => {
  const queue = ref<PendingApproval[]>(INITIAL_QUEUE.map(a => ({ ...a })))

  const current = computed(() => queue.value[0] ?? null)
  const hasPending = computed(() => queue.value.length > 0)

  function resolve(id: string, decision: 'approve' | 'deny') {
    const item = queue.value.find(a => a.id === id)
    if (!item) return
    queue.value = queue.value.filter(a => a.id !== id)

    const ui = useUIStore()
    ui.postApprovalDecision = decision
    ui.approvalOpen = queue.value.length > 0
    ui.setActiveNode(item.nodeId)
  }

  function push(approval: PendingApproval) {
    if (!queue.value.find(a => a.id === approval.id)) {
      queue.value.push(approval)
    }
  }

  return { queue, current, hasPending, resolve, push }
})
