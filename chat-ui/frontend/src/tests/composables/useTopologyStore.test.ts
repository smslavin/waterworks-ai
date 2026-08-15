import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useTopologyStore, alarmStateFromFindingsStatus } from '@/stores/topology'

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

  describe('alarmStateFromFindingsStatus', () => {
    it('maps "Fault Detected" to critical', () => {
      expect(alarmStateFromFindingsStatus('Fault Detected')).toBe('critical')
    })

    it('maps "Anomaly Detected" to warning', () => {
      expect(alarmStateFromFindingsStatus('Anomaly Detected')).toBe('warning')
    })

    it('maps "Normal" to normal', () => {
      expect(alarmStateFromFindingsStatus('Normal')).toBe('normal')
    })

    it('prefers Fault over Anomaly when both substrings are present', () => {
      expect(alarmStateFromFindingsStatus('Fault Detected (Anomaly escalated)')).toBe('critical')
    })

    it('returns null for Unknown', () => {
      expect(alarmStateFromFindingsStatus('Unknown')).toBeNull()
    })

    it('returns null for Error', () => {
      expect(alarmStateFromFindingsStatus('Error')).toBeNull()
    })
  })

  describe('applySpecialistFindings', () => {
    it('colors every node owned by the specialist', () => {
      const topo = useTopologyStore()
      topo.applySpecialistFindings('treatment', 'Fault Detected')
      for (const node of topo.nodesByArea['Treatment']!) {
        expect(node.alarmState).toBe('critical')
      }
    })

    it('matches specialist case-insensitively (evt.specialist is lowercase, TopologyNode.specialist is capitalized)', () => {
      const topo = useTopologyStore()
      topo.applySpecialistFindings('intake', 'Anomaly Detected')
      expect(topo.nodeById('RawWater_01')?.alarmState).toBe('warning')
    })

    it('does not touch nodes owned by a different specialist', () => {
      const topo = useTopologyStore()
      topo.applySpecialistFindings('treatment', 'Fault Detected')
      expect(topo.nodeById('RawWater_01')?.alarmState).toBe('normal')
    })

    it('is a no-op for Unknown status', () => {
      const topo = useTopologyStore()
      topo.setAlarmState('Clarifier_01', 'critical')
      topo.applySpecialistFindings('treatment', 'Unknown')
      expect(topo.nodeById('Clarifier_01')?.alarmState).toBe('critical')
    })

    it('is a no-op for an unrecognized specialist (e.g. historian, which owns no nodes)', () => {
      const topo = useTopologyStore()
      expect(() => topo.applySpecialistFindings('historian', 'Fault Detected')).not.toThrow()
      expect(topo.nodes.every(n => n.alarmState === 'normal')).toBe(true)
    })
  })

  describe('saveInsight', () => {
    it('sets hasMemory to true', () => {
      const topo = useTopologyStore()
      topo.saveInsight('UV_01', 'fault_pattern')
      expect(topo.nodeById('UV_01')?.hasMemory).toBe(true)
    })

    it('increments saveCount on each call', () => {
      const topo = useTopologyStore()
      topo.saveInsight('UV_01', 'fault_pattern')
      topo.saveInsight('UV_01', 'operator_note')
      expect(topo.nodeById('UV_01')?.saveCount).toBe(2)
    })

    it('is a no-op for unknown id', () => {
      const topo = useTopologyStore()
      expect(() => topo.saveInsight('NonExistent', 'fault_pattern')).not.toThrow()
    })
  })
})
