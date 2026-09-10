import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, fireEvent, cleanup } from '@testing-library/vue'
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ApprovalPanel from '@/components/approval/ApprovalPanel.vue'
import { useUIStore } from '@/stores/ui'
import { useApprovalStore, type PendingApproval } from '@/stores/approval'

const MOCK: PendingApproval = {
  id: 'ap1',
  nodeId: 'RawWater_01',
  specialist: 'Intake',
  action: 'Reduce pump speed by 15%',
  impact: 'Intake flow will decrease ~15%. Monitor bearing temperature.',
}

function renderPanel(approvalOpen = true) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const ui = useUIStore()
  const approvals = useApprovalStore()
  if (approvalOpen) approvals.push(MOCK)
  ui.approvalOpen = approvalOpen
  return {
    pinia, ui, approvals,
    ...render(ApprovalPanel, { global: { plugins: [pinia] } }),
  }
}

describe('ApprovalPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }))
  })
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('is hidden when approvalOpen is false', () => {
    const { container } = renderPanel(false)
    expect(container.querySelector('.approval-panel')).toBeNull()
  })

  it('is visible when approvalOpen is true and queue has items', () => {
    const { container } = renderPanel(true)
    expect(container.querySelector('.approval-panel')).toBeTruthy()
  })

  it('renders the pending node id', () => {
    const { container } = renderPanel(true)
    expect(container.querySelector('.approval-node')?.textContent?.trim()).toBe('RawWater_01')
  })

  it('renders the action text', () => {
    const { container } = renderPanel(true)
    expect(container.querySelector('.approval-action')?.textContent).toContain('Reduce pump speed by 15%')
  })

  it('renders the impact text', () => {
    const { container } = renderPanel(true)
    expect(container.querySelector('.approval-impact')?.textContent).toContain('Intake flow will decrease')
  })

  it('shows the active site, so an operator with multiple plants open knows which one this is', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const ui = useUIStore()
    const approvals = useApprovalStore()
    ui.setActiveSite('Eastside', 'Metro Region')
    approvals.push(MOCK)
    ui.approvalOpen = true
    const { container } = render(ApprovalPanel, { global: { plugins: [pinia] } })
    expect(container.querySelector('.approval-site')?.textContent).toBe('Eastside')
  })

  describe('approve', () => {
    it('removes the approval from the queue', async () => {
      const { container, approvals } = renderPanel(true)
      await fireEvent.click(container.querySelector('.approve-btn')!)
      await flushPromises()
      expect(approvals.queue).toHaveLength(0)
    })

    it('closes the approval panel', async () => {
      const { container, ui } = renderPanel(true)
      await fireEvent.click(container.querySelector('.approve-btn')!)
      await flushPromises()
      expect(ui.approvalOpen).toBe(false)
    })

    it('does not change the active node panel', async () => {
      const pinia = createPinia()
      setActivePinia(pinia)
      const ui = useUIStore()
      const approvals = useApprovalStore()
      ui.setActiveNode('HighService_02')
      approvals.push(MOCK)
      ui.approvalOpen = true
      const { container } = render(ApprovalPanel, { global: { plugins: [pinia] } })
      await fireEvent.click(container.querySelector('.approve-btn')!)
      await flushPromises()
      expect(ui.activeNodeId).toBe('HighService_02')
    })
  })

  describe('deny', () => {
    it('removes the approval from the queue', async () => {
      const { container, approvals } = renderPanel(true)
      await fireEvent.click(container.querySelector('.deny-btn')!)
      await flushPromises()
      expect(approvals.queue).toHaveLength(0)
    })

    it('does not change the active node panel', async () => {
      const pinia = createPinia()
      setActivePinia(pinia)
      const ui = useUIStore()
      const approvals = useApprovalStore()
      ui.setActiveNode('HighService_02')
      approvals.push(MOCK)
      ui.approvalOpen = true
      const { container } = render(ApprovalPanel, { global: { plugins: [pinia] } })
      await fireEvent.click(container.querySelector('.deny-btn')!)
      await flushPromises()
      expect(ui.activeNodeId).toBe('HighService_02')
    })
  })

  describe('close button', () => {
    it('resolves the approval as denied so the backend future does not ride out the timeout', async () => {
      const { container, ui, approvals } = renderPanel(true)
      await fireEvent.click(container.querySelector('.approval-close')!)
      await flushPromises()
      expect(approvals.queue).toHaveLength(0)
      expect(ui.approvalOpen).toBe(false)
    })
  })

  describe('backend confirmation failure', () => {
    it('keeps the approval queued and shows an error instead of silently dequeuing it', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500, text: () => Promise.resolve('boom') }))
      const { container, approvals } = renderPanel(true)
      await fireEvent.click(container.querySelector('.approve-btn')!)
      await flushPromises()
      expect(approvals.queue).toHaveLength(1)
      expect(container.querySelector('.approval-error')?.textContent).toContain('500')
    })
  })
})
