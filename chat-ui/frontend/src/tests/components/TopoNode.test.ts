import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { render, fireEvent, cleanup, within } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'
import TopoNode from '@/components/topo/TopoNode.vue'
import type { TopologyNode } from '@/stores/topology'

function makeNode(overrides: Partial<TopologyNode> = {}): TopologyNode {
  return {
    id: 'TestNode_01',
    area: 'Intake',
    specialist: 'Intake',
    equipmentType: 'pump',
    confidenceLevel: 'verified',
    alarmState: 'normal',
    hasMemory: false,
    saveCount: 0,
    ...overrides,
  }
}

function renderNode(node: TopologyNode) {
  return render(TopoNode, {
    props: { node },
    global: { plugins: [createPinia()] },
  })
}

describe('TopoNode', () => {
  beforeEach(() => { setActivePinia(createPinia()) })
  afterEach(() => cleanup())

  describe('rendering', () => {
    it('renders the node id', () => {
      const { container } = renderNode(makeNode())
      expect(within(container as HTMLElement).getByText('TestNode_01')).toBeTruthy()
    })

    it('renders the equipment type', () => {
      const { container } = renderNode(makeNode())
      expect(within(container as HTMLElement).getByText('pump')).toBeTruthy()
    })
  })

  describe('confidence level classes', () => {
    it('applies verified class', () => {
      const { container } = renderNode(makeNode({ confidenceLevel: 'verified' }))
      expect(container.querySelector('.topo-node')?.classList).toContain('verified')
    })

    it('applies inferred class', () => {
      const { container } = renderNode(makeNode({ confidenceLevel: 'inferred' }))
      expect(container.querySelector('.topo-node')?.classList).toContain('inferred')
    })

    it('applies suspect class', () => {
      const { container } = renderNode(makeNode({ confidenceLevel: 'suspect' }))
      expect(container.querySelector('.topo-node')?.classList).toContain('suspect')
    })
  })

  describe('alarm state classes', () => {
    it('applies no alarm class for normal state', () => {
      const { container } = renderNode(makeNode({ alarmState: 'normal' }))
      const classes = container.querySelector('.topo-node')?.classList
      expect(classes).not.toContain('warning')
      expect(classes).not.toContain('critical')
      expect(classes).not.toContain('pending-approval')
    })

    it('applies warning class', () => {
      const { container } = renderNode(makeNode({ alarmState: 'warning' }))
      expect(container.querySelector('.topo-node')?.classList).toContain('warning')
    })

    it('applies critical class', () => {
      const { container } = renderNode(makeNode({ alarmState: 'critical' }))
      expect(container.querySelector('.topo-node')?.classList).toContain('critical')
    })

    it('applies pending-approval class', () => {
      const { container } = renderNode(makeNode({ alarmState: 'pending-approval' }))
      expect(container.querySelector('.topo-node')?.classList).toContain('pending-approval')
    })
  })

  describe('memory badge', () => {
    it('does not show memory badge when hasMemory is false', () => {
      const { container } = renderNode(makeNode({ hasMemory: false }))
      expect(container.querySelector('.node-memory')).toBeNull()
    })

    it('shows "● mem" for first save', () => {
      const { container } = renderNode(makeNode({ hasMemory: true, saveCount: 1 }))
      expect(within(container as HTMLElement).getByText('● mem')).toBeTruthy()
    })

    it('shows count for multiple saves', () => {
      const { container } = renderNode(makeNode({ hasMemory: true, saveCount: 3 }))
      expect(within(container as HTMLElement).getByText('● 3 mem')).toBeTruthy()
    })
  })

  describe('click', () => {
    it('emits click with node id', async () => {
      const { container, emitted } = renderNode(makeNode({ id: 'RawWater_01' }))
      await fireEvent.click(container.querySelector('.topo-node')!)
      expect(emitted().click).toBeTruthy()
      expect(emitted().click![0]).toEqual(['RawWater_01'])
    })
  })

  describe('data-id attribute', () => {
    it('sets data-id for edge drawing', () => {
      const { container } = renderNode(makeNode({ id: 'UV_01' }))
      expect(container.querySelector('[data-id="UV_01"]')).toBeTruthy()
    })
  })
})
