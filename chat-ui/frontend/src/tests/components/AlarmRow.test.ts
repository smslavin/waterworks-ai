import { describe, it, expect, afterEach } from 'vitest'
import { render, fireEvent, cleanup } from '@testing-library/vue'
import { createPinia } from 'pinia'
import AlarmRow from '@/components/alarm/AlarmRow.vue'
import type { Alarm } from '@/stores/alarm'

function renderRow(alarm: Partial<Alarm> = {}) {
  const a: Alarm = {
    id: 'a1',
    nodeId: 'RawWater_02',
    severity: 'critical',
    message: 'Bearing temp 68°C — threshold exceeded',
    timestamp: '3 min ago',
    ...alarm,
  }
  return render(AlarmRow, {
    props: { alarm: a },
    global: { plugins: [createPinia()] },
  })
}

describe('AlarmRow', () => {
  afterEach(() => cleanup())

  it('renders the node id', () => {
    const { container } = renderRow()
    expect(container.querySelector('.alarm-node')?.textContent).toBe('RawWater_02')
  })

  it('renders the message', () => {
    const { container } = renderRow()
    expect(container.querySelector('.alarm-message')?.textContent).toContain('Bearing temp')
  })

  it('applies critical class to badge for critical alarms', () => {
    const { container } = renderRow({ severity: 'critical' })
    expect(container.querySelector('.alarm-badge')?.classList).toContain('critical')
  })

  it('applies warning class to badge for warning alarms', () => {
    const { container } = renderRow({ severity: 'warning' })
    expect(container.querySelector('.alarm-badge')?.classList).toContain('warning')
  })

  it('applies severity class to the row', () => {
    const { container } = renderRow({ severity: 'critical' })
    expect(container.querySelector('.alarm-row')?.classList).toContain('critical')
  })

  it('emits ack when ACK button is clicked', async () => {
    const { container, emitted } = renderRow()
    await fireEvent.click(container.querySelector('.alarm-ack')!)
    expect(emitted().ack).toBeTruthy()
  })
})
