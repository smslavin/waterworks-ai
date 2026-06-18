import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { nextTick } from 'vue'
import { render, fireEvent, cleanup } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'
import AlarmStrip from '@/components/alarm/AlarmStrip.vue'
import { useAlarmStore } from '@/stores/alarm'

function seedCriticals(alarm: ReturnType<typeof useAlarmStore>) {
  alarm.addAlarm({ id: 'a1', nodeId: 'RawWater_02',    severity: 'critical', message: 'Bearing temp 68°C',        timestamp: '3 min ago' })
  alarm.addAlarm({ id: 'a2', nodeId: 'HighService_01', severity: 'critical', message: 'Discharge pressure 79 PSI', timestamp: '1 min ago' })
  alarm.addAlarm({ id: 'a3', nodeId: 'UV_01',          severity: 'warning',  message: 'Lamp intensity degradation', timestamp: '12 min ago' })
}

function renderStrip() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const alarm = useAlarmStore()
  seedCriticals(alarm)
  return {
    alarm,
    ...render(AlarmStrip, { global: { plugins: [pinia] } }),
  }
}

describe('AlarmStrip', () => {
  beforeEach(() => { setActivePinia(createPinia()) })
  afterEach(() => cleanup())

  it('renders only critical alarm rows (warnings go to the header)', () => {
    const { container } = renderStrip()
    expect(container.querySelectorAll('.alarm-row')).toHaveLength(2)
  })

  it('renders only critical rows', () => {
    const { container } = renderStrip()
    const rows = container.querySelectorAll('.alarm-row')
    expect(rows[0]!.classList).toContain('critical')
    expect(rows[1]!.classList).toContain('critical')
  })

  it('removes a row when ACK is clicked', async () => {
    const { container } = renderStrip()
    const ackBtns = container.querySelectorAll('.alarm-ack')
    await fireEvent.click(ackBtns[0]!)
    expect(container.querySelectorAll('.alarm-row')).toHaveLength(1)
  })

  it('is hidden when all critical alarms are acknowledged', async () => {
    const { alarm, container } = renderStrip()
    alarm.alarms
      .filter(a => a.severity === 'critical')
      .forEach(a => alarm.acknowledge(a.id))
    await nextTick()
    expect(container.querySelector('.alarm-strip')).toBeNull()
  })
})
