import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { render, fireEvent, cleanup } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'
import TopoColumn from '@/components/topo/TopoColumn.vue'
import type { TopologyNode } from '@/stores/topology'

const INTAKE_NODES: TopologyNode[] = [
  { id: 'RawWater_01', area: 'Intake', specialist: 'Intake', equipmentType: 'pump', confidenceLevel: 'verified', alarmState: 'pending-approval', hasMemory: false, saveCount: 0 },
  { id: 'RawWater_02', area: 'Intake', specialist: 'Intake', equipmentType: 'pump', confidenceLevel: 'verified', alarmState: 'critical',         hasMemory: false, saveCount: 0 },
]

function renderColumn(area: string, nodes: TopologyNode[]) {
  return render(TopoColumn, {
    props: { area, nodes },
    global: { plugins: [createPinia()] },
  })
}

describe('TopoColumn', () => {
  beforeEach(() => { setActivePinia(createPinia()) })
  afterEach(() => cleanup())

  it('renders the area label', () => {
    const { container } = renderColumn('Intake', INTAKE_NODES)
    expect(container.querySelector('.topo-column-label')?.textContent?.trim()).toBe('Intake')
  })

  it('renders the correct number of nodes', () => {
    const { container } = renderColumn('Intake', INTAKE_NODES)
    expect(container.querySelectorAll('.topo-node')).toHaveLength(2)
  })

  it('sets data-area attribute', () => {
    const { container } = renderColumn('Treatment', [])
    expect(container.querySelector('[data-area="Treatment"]')).toBeTruthy()
  })

  it('emits label-click with area name when label is clicked', async () => {
    const { container, emitted } = renderColumn('Intake', INTAKE_NODES)
    await fireEvent.click(container.querySelector('.topo-column-label')!)
    expect(emitted()['label-click']).toBeTruthy()
    expect(emitted()['label-click'][0]).toEqual(['Intake'])
  })

  it('emits node-click with node id when a node is clicked', async () => {
    const { container, emitted } = renderColumn('Intake', INTAKE_NODES)
    await fireEvent.click(container.querySelectorAll('.topo-node')[0])
    expect(emitted()['node-click']).toBeTruthy()
    expect(emitted()['node-click'][0]).toEqual(['RawWater_01'])
  })
})
