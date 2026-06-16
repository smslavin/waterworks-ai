import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAlarmStore } from '@/stores/alarm'

describe('useAlarmStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('initial state', () => {
    it('starts with 3 alarms', () => {
      const alarm = useAlarmStore()
      expect(alarm.alarms).toHaveLength(3)
    })

    it('has 2 criticals and 1 warning', () => {
      const alarm = useAlarmStore()
      expect(alarm.alarms.filter(a => a.severity === 'critical')).toHaveLength(2)
      expect(alarm.alarms.filter(a => a.severity === 'warning')).toHaveLength(1)
    })
  })

  describe('acknowledge', () => {
    it('removes the alarm by id', () => {
      const alarm = useAlarmStore()
      const id = alarm.alarms[0].id
      alarm.acknowledge(id)
      expect(alarm.alarms.find(a => a.id === id)).toBeUndefined()
    })

    it('decrements the count', () => {
      const alarm = useAlarmStore()
      alarm.acknowledge(alarm.alarms[0].id)
      expect(alarm.alarms).toHaveLength(2)
    })

    it('is a no-op for an unknown id', () => {
      const alarm = useAlarmStore()
      alarm.acknowledge('does-not-exist')
      expect(alarm.alarms).toHaveLength(3)
    })

    it('can acknowledge all alarms', () => {
      const alarm = useAlarmStore()
      const ids = alarm.alarms.map(a => a.id)
      ids.forEach(id => alarm.acknowledge(id))
      expect(alarm.alarms).toHaveLength(0)
    })
  })

  describe('addAlarm', () => {
    it('adds a new alarm', () => {
      const alarm = useAlarmStore()
      alarm.addAlarm({ id: 'new1', nodeId: 'Clarifier_01', severity: 'warning', message: 'Test' })
      expect(alarm.alarms).toHaveLength(4)
    })

    it('does not add a duplicate', () => {
      const alarm = useAlarmStore()
      const existing = alarm.alarms[0]
      alarm.addAlarm({ ...existing })
      expect(alarm.alarms).toHaveLength(3)
    })
  })
})
