import { defineStore } from 'pinia'
import { ref } from 'vue'

export type AlarmSeverity = 'critical' | 'warning'

export interface Alarm {
  id: string
  nodeId: string
  severity: AlarmSeverity
  message: string
  timestamp: string
  content?: string
}

const INITIAL_ALARMS: Alarm[] = []

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

  function setAlarmContent(id: string, content: string) {
    const a = alarms.value.find(a => a.id === id)
    if (a) a.content = content
  }

  return { alarms, acknowledge, addAlarm, setAlarmContent }
})
