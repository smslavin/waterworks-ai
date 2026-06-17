import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useTopologyStore } from '@/stores/topology'

describe('useTopologyStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('initial state', () => {
    it('has 10 nodes', () => {
      const topo = useTopologyStore()
      expect(topo.nodes).toHaveLength(10)
    })

    it('has 11 edges', () => {
      const topo = useTopologyStore()
      expect(topo.edges).toHaveLength(11)
    })
  })

  describe('areas getter', () => {
    it('returns areas in Intake → Treatment → Distribution order', () => {
      const topo = useTopologyStore()
      expect(topo.areas).toEqual(['Intake', 'Treatment', 'Distribution'])
    })
  })

  describe('nodesByArea getter', () => {
    it('groups Intake nodes correctly', () => {
      const topo = useTopologyStore()
      expect(topo.nodesByArea['Intake']).toHaveLength(2)
      expect(topo.nodesByArea['Intake']!.map(n => n.id)).toEqual(['RawWater_01', 'RawWater_02'])
    })

    it('groups Treatment nodes correctly', () => {
      const topo = useTopologyStore()
      expect(topo.nodesByArea['Treatment']).toHaveLength(5)
    })

    it('groups Distribution nodes correctly', () => {
      const topo = useTopologyStore()
      expect(topo.nodesByArea['Distribution']).toHaveLength(3)
    })
  })

  describe('nodeById', () => {
    it('returns the correct node', () => {
      const topo = useTopologyStore()
      const node = topo.nodeById('UV_01')
      expect(node?.equipmentType).toBe('uv_reactor')
      expect(node?.area).toBe('Treatment')
    })

    it('returns undefined for unknown id', () => {
      const topo = useTopologyStore()
      expect(topo.nodeById('NonExistent')).toBeUndefined()
    })
  })

  describe('setAlarmState', () => {
    it('updates the alarm state of a node', () => {
      const topo = useTopologyStore()
      topo.setAlarmState('Clarifier_01', 'warning')
      expect(topo.nodeById('Clarifier_01')?.alarmState).toBe('warning')
    })

    it('is a no-op for unknown id', () => {
      const topo = useTopologyStore()
      expect(() => topo.setAlarmState('NonExistent', 'critical')).not.toThrow()
    })
  })

  describe('saveInsight', () => {
    it('sets hasMemory to true', () => {
      const topo = useTopologyStore()
      topo.saveInsight('UV_01')
      expect(topo.nodeById('UV_01')?.hasMemory).toBe(true)
    })

    it('increments saveCount on each call', () => {
      const topo = useTopologyStore()
      topo.saveInsight('UV_01')
      topo.saveInsight('UV_01')
      expect(topo.nodeById('UV_01')?.saveCount).toBe(2)
    })

    it('is a no-op for unknown id', () => {
      const topo = useTopologyStore()
      expect(() => topo.saveInsight('NonExistent')).not.toThrow()
    })
  })
})
