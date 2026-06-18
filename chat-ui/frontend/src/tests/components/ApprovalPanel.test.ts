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

  describe('approve', () => {
    it('resolves with "approve" decision', async () => {
      const { container, ui } = renderPanel(true)
      await fireEvent.click(container.querySelector('.approve-btn')!)
      await flushPromises()
      expect(ui.postApprovalDecision).toBe('approve')
    })

    it('re-opens node panel for the resolved node', async () => {
      const { container, ui } = renderPanel(true)
      await fireEvent.click(container.querySelector('.approve-btn')!)
      await flushPromises()
      expect(ui.activeNodeId).toBe('RawWater_01')
      expect(ui.activePanel).toBe('node')
    })

    it('removes the approval from the queue', async () => {
      const { container, approvals } = renderPanel(true)
      await fireEvent.click(container.querySelector('.approve-btn')!)
      await flushPromises()
      expect(approvals.queue).toHaveLength(0)
    })
  })

  describe('deny', () => {
    it('resolves with "deny" decision', async () => {
      const { container, ui } = renderPanel(true)
      await fireEvent.click(container.querySelector('.deny-btn')!)
      await flushPromises()
      expect(ui.postApprovalDecision).toBe('deny')
    })

    it('re-opens node panel for the resolved node', async () => {
      const { container, ui } = renderPanel(true)
      await fireEvent.click(container.querySelector('.deny-btn')!)
      await flushPromises()
      expect(ui.activeNodeId).toBe('RawWater_01')
    })
  })

  describe('close button', () => {
    it('sets approvalOpen to false without resolving the approval', async () => {
      const { container, ui, approvals } = renderPanel(true)
      await fireEvent.click(container.querySelector('.approval-close')!)
      expect(ui.approvalOpen).toBe(false)
      expect(approvals.queue).toHaveLength(1)
    })
  })
})
