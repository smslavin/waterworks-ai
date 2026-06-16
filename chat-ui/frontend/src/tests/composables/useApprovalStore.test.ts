import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useApprovalStore } from '@/stores/approval'
import { useUIStore } from '@/stores/ui'

describe('useApprovalStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('initial state', () => {
    it('starts with 1 pending approval', () => {
      const approvals = useApprovalStore()
      expect(approvals.queue).toHaveLength(1)
    })

    it('hasPending is true initially', () => {
      const approvals = useApprovalStore()
      expect(approvals.hasPending).toBe(true)
    })

    it('current is the first queue item', () => {
      const approvals = useApprovalStore()
      expect(approvals.current?.nodeId).toBe('RawWater_01')
    })
  })

  describe('resolve — approve', () => {
    it('removes the item from the queue', () => {
      const approvals = useApprovalStore()
      const id = approvals.current!.id
      approvals.resolve(id, 'approve')
      expect(approvals.queue).toHaveLength(0)
    })

    it('sets postApprovalDecision to "approve" in UIStore', () => {
      const approvals = useApprovalStore()
      const ui = useUIStore()
      const id = approvals.current!.id
      approvals.resolve(id, 'approve')
      expect(ui.postApprovalDecision).toBe('approve')
    })

    it('re-opens the node panel for the resolved node', () => {
      const approvals = useApprovalStore()
      const ui = useUIStore()
      const item = approvals.current!
      approvals.resolve(item.id, 'approve')
      expect(ui.activeNodeId).toBe(item.nodeId)
      expect(ui.activePanel).toBe('node')
    })

    it('closes approvalOpen when queue is empty', () => {
      const approvals = useApprovalStore()
      const ui = useUIStore()
      ui.approvalOpen = true
      approvals.resolve(approvals.current!.id, 'approve')
      expect(ui.approvalOpen).toBe(false)
    })
  })

  describe('resolve — deny', () => {
    it('removes item and sets decision to "deny"', () => {
      const approvals = useApprovalStore()
      const ui = useUIStore()
      const id = approvals.current!.id
      approvals.resolve(id, 'deny')
      expect(approvals.queue).toHaveLength(0)
      expect(ui.postApprovalDecision).toBe('deny')
    })

    it('re-opens the node panel', () => {
      const approvals = useApprovalStore()
      const ui = useUIStore()
      const item = approvals.current!
      approvals.resolve(item.id, 'deny')
      expect(ui.activeNodeId).toBe(item.nodeId)
    })
  })

  describe('resolve — unknown id', () => {
    it('is a no-op for unknown id', () => {
      const approvals = useApprovalStore()
      approvals.resolve('not-real', 'approve')
      expect(approvals.queue).toHaveLength(1)
    })
  })

  describe('push', () => {
    it('adds a new approval to the queue', () => {
      const approvals = useApprovalStore()
      approvals.push({ id: 'ap2', nodeId: 'UV_01', specialist: 'Treatment', action: 'Replace lamp', impact: 'UV dose will drop.' })
      expect(approvals.queue).toHaveLength(2)
    })

    it('does not add a duplicate', () => {
      const approvals = useApprovalStore()
      approvals.push({ ...approvals.current! })
      expect(approvals.queue).toHaveLength(1)
    })
  })
})
