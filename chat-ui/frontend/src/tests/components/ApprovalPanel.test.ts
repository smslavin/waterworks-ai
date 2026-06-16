import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { render, fireEvent, cleanup } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'
import ApprovalPanel from '@/components/approval/ApprovalPanel.vue'
import { useUIStore } from '@/stores/ui'
import { useApprovalStore } from '@/stores/approval'

function renderPanel(approvalOpen = true) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const ui = useUIStore()
  ui.approvalOpen = approvalOpen
  return {
    pinia,
    ui,
    approvals: useApprovalStore(),
    ...render(ApprovalPanel, { global: { plugins: [pinia] } }),
  }
}

describe('ApprovalPanel', () => {
  beforeEach(() => { setActivePinia(createPinia()) })
  afterEach(() => cleanup())

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
    const action = container.querySelector('.approval-action')?.textContent
    expect(action).toContain('Reduce pump speed by 15%')
  })

  it('renders the impact text', () => {
    const { container } = renderPanel(true)
    const impact = container.querySelector('.approval-impact')?.textContent
    expect(impact).toContain('Intake flow will decrease')
  })

  describe('approve', () => {
    it('resolves with "approve" decision', async () => {
      const { container, ui } = renderPanel(true)
      await fireEvent.click(container.querySelector('.approve-btn')!)
      expect(ui.postApprovalDecision).toBe('approve')
    })

    it('re-opens node panel for the resolved node', async () => {
      const { container, ui } = renderPanel(true)
      await fireEvent.click(container.querySelector('.approve-btn')!)
      expect(ui.activeNodeId).toBe('RawWater_01')
      expect(ui.activePanel).toBe('node')
    })

    it('removes the approval from the queue', async () => {
      const { container, approvals } = renderPanel(true)
      await fireEvent.click(container.querySelector('.approve-btn')!)
      expect(approvals.queue).toHaveLength(0)
    })
  })

  describe('deny', () => {
    it('resolves with "deny" decision', async () => {
      const { container, ui } = renderPanel(true)
      await fireEvent.click(container.querySelector('.deny-btn')!)
      expect(ui.postApprovalDecision).toBe('deny')
    })

    it('re-opens node panel for the resolved node', async () => {
      const { container, ui } = renderPanel(true)
      await fireEvent.click(container.querySelector('.deny-btn')!)
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
