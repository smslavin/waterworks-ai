import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAlarmStore } from '@/stores/alarm'

const SEED_ALARMS = [
  { id: 'a1', nodeId: 'RawWater_02',    severity: 'critical' as const, message: 'Bearing temp 68°C',        timestamp: '3 min ago' },
  { id: 'a2', nodeId: 'HighService_01', severity: 'critical' as const, message: 'Discharge pressure 79 PSI', timestamp: '1 min ago' },
  { id: 'a3', nodeId: 'UV_01',          severity: 'warning'  as const, message: 'Lamp intensity degradation', timestamp: '12 min ago' },
]

describe('useAlarmStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('initial state', () => {
    it('starts empty — alarms come from reactive monitor, not hardcoded', () => {
      const alarm = useAlarmStore()
      expect(alarm.alarms).toHaveLength(0)
    })
  })

  describe('acknowledge', () => {
    let alarm: ReturnType<typeof useAlarmStore>

    beforeEach(() => {
      alarm = useAlarmStore()
      SEED_ALARMS.forEach(a => alarm.addAlarm(a))
    })

    it('removes the alarm by id', () => {
      const id = alarm.alarms[0]!.id
      alarm.acknowledge(id)
      expect(alarm.alarms.find(a => a.id === id)).toBeUndefined()
    })

    it('decrements the count', () => {
      alarm.acknowledge(alarm.alarms[0]!.id)
      expect(alarm.alarms).toHaveLength(2)
    })

    it('is a no-op for an unknown id', () => {
      alarm.acknowledge('does-not-exist')
      expect(alarm.alarms).toHaveLength(3)
    })

    it('can acknowledge all alarms', () => {
      const ids = alarm.alarms.map(a => a.id)
      ids.forEach(id => alarm.acknowledge(id))
      expect(alarm.alarms).toHaveLength(0)
    })
  })

  describe('addAlarm', () => {
    let alarm: ReturnType<typeof useAlarmStore>

    beforeEach(() => {
      alarm = useAlarmStore()
      SEED_ALARMS.forEach(a => alarm.addAlarm(a))
    })

    it('adds a new alarm', () => {
      alarm.addAlarm({ id: 'new1', nodeId: 'Clarifier_01', severity: 'warning', message: 'Test', timestamp: 'just now' })
      expect(alarm.alarms).toHaveLength(4)
    })

    it('does not add a duplicate', () => {
      const existing = alarm.alarms[0]!
      alarm.addAlarm({ ...existing })
      expect(alarm.alarms).toHaveLength(3)
    })
  })
})
