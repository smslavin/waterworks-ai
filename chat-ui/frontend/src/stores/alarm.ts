import { defineStore } from 'pinia'
import { ref } from 'vue'

export type AlarmSeverity = 'critical' | 'warning'

export interface Alarm {
  id: string
  nodeId: string
  severity: AlarmSeverity
  message: string
  timestamp: string
}

const INITIAL_ALARMS: Alarm[] = [
  { id: 'a1', nodeId: 'RawWater_02',    severity: 'critical', message: 'Bearing temp 68°C — threshold exceeded',         timestamp: '3 min ago' },
  { id: 'a2', nodeId: 'HighService_01', severity: 'critical', message: 'Discharge pressure 79 PSI — above limit',        timestamp: '1 min ago' },
  { id: 'a3', nodeId: 'UV_01',          severity: 'warning',  message: 'Lamp intensity degradation — replace within 9d', timestamp: '12 min ago' },
]

export const useAlarmStore = defineStore('alarm', () => {
  const alarms = ref<Alarm[]>(INITIAL_ALARMS.map(a => ({ ...a })))

  function acknowledge(id: string) {
    const idx = alarms.value.findIndex(a => a.id === id)
    if (idx !== -1) alarms.value.splice(idx, 1)
  }

  function addAlarm(alarm: Alarm) {
    if (!alarms.value.find(a => a.id === alarm.id)) {
      alarms.value.push(alarm)
    }
  }

  return { alarms, acknowledge, addAlarm }
})
