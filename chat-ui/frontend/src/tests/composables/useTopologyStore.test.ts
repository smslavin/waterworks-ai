import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useTopologyStore, alarmStateFromFindingsStatus, AREA_ORDER } from '@/stores/topology'

// AREA_ORDER is a module-level `reactive()` array (see stores/topology.ts) —
// a singleton shared across every test in this file (and the app), not
// something a fresh Pinia instance resets. loadTopology() mutates it via
// .splice() (matching the AREA_ORDER contract callers like ConfigCanvas.vue
// rely on: mutate in place, never reassign), so tests that call
// loadTopology() with a different area list must restore it afterward or
// leak into unrelated tests below (e.g. "areas getter" further down).
const DEFAULT_AREA_ORDER = ['Intake', 'Treatment', 'Distribution']

describe('useTopologyStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    AREA_ORDER.splice(0, AREA_ORDER.length, ...DEFAULT_AREA_ORDER)
    vi.unstubAllGlobals()
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

  describe('loadTopology', () => {
    const MOCK_RESPONSE = {
      areas: ['Alpha', 'Beta'],
      nodes: [
        { id: 'Foo_01', area: 'Alpha', specialist: 'Alpha', equipmentType: 'pump' },
        { id: 'Bar_01', area: 'Beta', specialist: 'Beta', equipmentType: 'tank' },
      ],
    }

    it('replaces nodes and AREA_ORDER with the fetched shape', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(MOCK_RESPONSE),
      }))
      const topo = useTopologyStore()
      await topo.loadTopology()

      expect(topo.nodes).toHaveLength(2)
      expect(topo.nodeById('Foo_01')).toMatchObject({
        id: 'Foo_01', area: 'Alpha', specialist: 'Alpha', equipmentType: 'pump',
        confidenceLevel: 'verified', alarmState: 'normal', hasMemory: false, saveCount: 0,
      })
      expect(topo.areas).toEqual(['Alpha', 'Beta'])
    })

    it('leaves edges untouched — no backend source of truth for flow connectivity', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(MOCK_RESPONSE),
      }))
      const topo = useTopologyStore()
      const edgesBefore = topo.edges.length
      await topo.loadTopology()
      expect(topo.edges).toHaveLength(edgesBefore)
    })

    it('keeps the INITIAL_NODES/AREA_ORDER fallback when the fetch fails', async () => {
      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('backend offline')))
      const topo = useTopologyStore()
      await topo.loadTopology()

      expect(topo.nodes).toHaveLength(10)
      expect(topo.areas).toEqual(DEFAULT_AREA_ORDER)
    })

    it('keeps the fallback when the response is not ok', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))
      const topo = useTopologyStore()
      await topo.loadTopology()

      expect(topo.nodes).toHaveLength(10)
      expect(topo.areas).toEqual(DEFAULT_AREA_ORDER)
    })

    it('keeps the fallback when the response body is malformed (missing nodes/areas)', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ unrelated: 'shape' }),
      }))
      const topo = useTopologyStore()
      await topo.loadTopology()

      expect(topo.nodes).toHaveLength(10)
      expect(topo.areas).toEqual(DEFAULT_AREA_ORDER)
    })

    it('does not throw when fetch itself is undefined (older test/runtime environments)', async () => {
      vi.stubGlobal('fetch', undefined)
      const topo = useTopologyStore()
      await expect(topo.loadTopology()).resolves.toBeUndefined()
      expect(topo.nodes).toHaveLength(10)
    })
  })
})
