import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useApprovalStore, type PendingApproval } from '@/stores/approval'
import { useUIStore } from '@/stores/ui'

const MOCK: PendingApproval = {
  id: 'ap1',
  nodeId: 'RawWater_01',
  specialist: 'Intake',
  action: 'Reduce pump speed by 15%',
  impact: 'Flow will decrease ~15%.',
}

describe('useApprovalStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }))
  })
  afterEach(() => { vi.unstubAllGlobals() })

  describe('initial state', () => {
    it('starts empty', () => {
      expect(useApprovalStore().queue).toHaveLength(0)
    })

    it('hasPending is false initially', () => {
      expect(useApprovalStore().hasPending).toBe(false)
    })

    it('current is null initially', () => {
      expect(useApprovalStore().current).toBeNull()
    })
  })

  describe('push', () => {
    it('adds an approval to the queue', () => {
      const approvals = useApprovalStore()
      approvals.push(MOCK)
      expect(approvals.queue).toHaveLength(1)
      expect(approvals.hasPending).toBe(true)
    })

    it('does not add a duplicate', () => {
      const approvals = useApprovalStore()
      approvals.push(MOCK)
      approvals.push({ ...MOCK })
      expect(approvals.queue).toHaveLength(1)
    })
  })

  describe('resolve — approve', () => {
    it('removes the item from the queue', async () => {
      const approvals = useApprovalStore()
      approvals.push(MOCK)
      await approvals.resolve(MOCK.id, 'approve')
      expect(approvals.queue).toHaveLength(0)
    })

    it('sets postApprovalDecision to "approve" in UIStore', async () => {
      const approvals = useApprovalStore()
      const ui = useUIStore()
      approvals.push(MOCK)
      await approvals.resolve(MOCK.id, 'approve')
      expect(ui.postApprovalDecision).toBe('approve')
    })

    it('re-opens the node panel for the resolved node', async () => {
      const approvals = useApprovalStore()
      const ui = useUIStore()
      approvals.push(MOCK)
      await approvals.resolve(MOCK.id, 'approve')
      expect(ui.activeNodeId).toBe(MOCK.nodeId)
      expect(ui.activePanel).toBe('node')
    })

    it('closes approvalOpen when queue is empty', async () => {
      const approvals = useApprovalStore()
      const ui = useUIStore()
      approvals.push(MOCK)
      ui.approvalOpen = true
      await approvals.resolve(MOCK.id, 'approve')
      expect(ui.approvalOpen).toBe(false)
    })

    it('posts approved decision to /api/action/respond', async () => {
      const approvals = useApprovalStore()
      approvals.push(MOCK)
      await approvals.resolve(MOCK.id, 'approve')
      expect(fetch).toHaveBeenCalledWith('/api/action/respond', expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ action_id: MOCK.id, decision: 'approved' }),
      }))
    })
  })

  describe('resolve — deny', () => {
    it('removes item and sets decision to "deny"', async () => {
      const approvals = useApprovalStore()
      const ui = useUIStore()
      approvals.push(MOCK)
      await approvals.resolve(MOCK.id, 'deny')
      expect(approvals.queue).toHaveLength(0)
      expect(ui.postApprovalDecision).toBe('deny')
    })

    it('re-opens the node panel', async () => {
      const approvals = useApprovalStore()
      const ui = useUIStore()
      approvals.push(MOCK)
      await approvals.resolve(MOCK.id, 'deny')
      expect(ui.activeNodeId).toBe(MOCK.nodeId)
    })

    it('posts denied decision to /api/action/respond', async () => {
      const approvals = useApprovalStore()
      approvals.push(MOCK)
      await approvals.resolve(MOCK.id, 'deny')
      expect(fetch).toHaveBeenCalledWith('/api/action/respond', expect.objectContaining({
        body: JSON.stringify({ action_id: MOCK.id, decision: 'denied' }),
      }))
    })
  })

  describe('resolve — unknown id', () => {
    it('is a no-op for unknown id', async () => {
      const approvals = useApprovalStore()
      approvals.push(MOCK)
      await approvals.resolve('not-real', 'approve')
      expect(approvals.queue).toHaveLength(1)
    })
  })
})
