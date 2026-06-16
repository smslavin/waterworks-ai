import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { nextTick } from 'vue'
import { render, fireEvent, cleanup } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'
import AlarmStrip from '@/components/alarm/AlarmStrip.vue'
import { useAlarmStore } from '@/stores/alarm'

function renderStrip() {
  return render(AlarmStrip, {
    global: { plugins: [createPinia()] },
  })
}

describe('AlarmStrip', () => {
  beforeEach(() => { setActivePinia(createPinia()) })
  afterEach(() => cleanup())

  it('renders a row for each alarm', () => {
    const { container } = renderStrip()
    expect(container.querySelectorAll('.alarm-row')).toHaveLength(3)
  })

  it('renders criticals before warnings', () => {
    const { container } = renderStrip()
    const rows = container.querySelectorAll('.alarm-row')
    expect(rows[0].classList).toContain('critical')
    expect(rows[1].classList).toContain('critical')
    expect(rows[2].classList).toContain('warning')
  })

  it('removes a row when ACK is clicked', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const { container } = render(AlarmStrip, { global: { plugins: [pinia] } })
    const ackBtns = container.querySelectorAll('.alarm-ack')
    await fireEvent.click(ackBtns[0])
    expect(container.querySelectorAll('.alarm-row')).toHaveLength(2)
  })

  it('is hidden when all alarms are acknowledged', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const alarmStore = useAlarmStore()
    const { container } = render(AlarmStrip, { global: { plugins: [pinia] } })
    const ids = alarmStore.alarms.map(a => a.id)
    ids.forEach(id => alarmStore.acknowledge(id))
    await nextTick()
    expect(container.querySelector('.alarm-strip')).toBeNull()
  })
})
