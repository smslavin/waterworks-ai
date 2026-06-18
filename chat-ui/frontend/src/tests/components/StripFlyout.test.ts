import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { nextTick } from 'vue'
import { render, fireEvent, cleanup } from '@testing-library/vue'
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import StripFlyout from '@/components/strip/StripFlyout.vue'
import { useUIStore } from '@/stores/ui'

function renderFlyout() {
  const pinia = createPinia()
  setActivePinia(pinia)
  return {
    ui: useUIStore(),
    ...render(StripFlyout, { global: { plugins: [pinia] } }),
  }
}

describe('StripFlyout', () => {
  beforeEach(() => { setActivePinia(createPinia()) })
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  describe('flyout visibility', () => {
    it('is hidden when no flyout is active', () => {
      const { container } = renderFlyout()
      expect(container.querySelector('.strip-flyout')).toBeNull()
    })

    it('shows "Service Health" title when health flyout is open', async () => {
      const { ui, container } = renderFlyout()
      ui.toggleFlyout('health')
      await nextTick()
      expect(container.querySelector('.flyout-title')?.textContent?.trim()).toBe('Service Health')
    })

    it('close button calls closeFlyout', async () => {
      const { ui, container } = renderFlyout()
      ui.toggleFlyout('health')
      await nextTick()
      await fireEvent.click(container.querySelector('.flyout-close')!)
      expect(ui.activeFlyout).toBeNull()
    })
  })

  describe('health flyout', () => {
    it('shows 7 service rows', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          aggregator: 'ok', influxdb: 'ok', mqtt: 'ok', simulator: 'ok',
          audit_mcp: 'ok', control_mcp: 'ok', memory_mcp: 'ok',
        }),
      }))
      const { ui, container } = renderFlyout()
      ui.toggleFlyout('health')
      await flushPromises()
      expect(container.querySelectorAll('.health-row')).toHaveLength(7)
    })

    it('dots are ok-class when all services return ok', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          aggregator: 'ok', influxdb: 'ok', mqtt: 'ok', simulator: 'ok',
          audit_mcp: 'ok', control_mcp: 'ok', memory_mcp: 'ok',
        }),
      }))
      const { ui, container } = renderFlyout()
      ui.toggleFlyout('health')
      await flushPromises()
      const dots = container.querySelectorAll('.health-dot')
      dots.forEach(dot => expect(dot.classList).toContain('ok'))
    })

    it('dots are err-class when all services return error', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          aggregator: 'error', influxdb: 'error', mqtt: 'error', simulator: 'error',
          audit_mcp: 'error', control_mcp: 'error', memory_mcp: 'error',
        }),
      }))
      const { ui, container } = renderFlyout()
      ui.toggleFlyout('health')
      await flushPromises()
      const dots = container.querySelectorAll('.health-dot')
      dots.forEach(dot => expect(dot.classList).toContain('err'))
    })

    it('mixed ok/error: first dot ok, last dot err', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          aggregator: 'ok', influxdb: 'ok', mqtt: 'ok', simulator: 'ok',
          audit_mcp: 'ok', control_mcp: 'ok', memory_mcp: 'error',
        }),
      }))
      const { ui, container } = renderFlyout()
      ui.toggleFlyout('health')
      await flushPromises()
      const dots = container.querySelectorAll('.health-dot')
      expect(dots[0]!.classList).toContain('ok')
      expect(dots[6]!.classList).toContain('err')
    })

    it('dots are warn-class (loading) before fetch resolves', async () => {
      let resolve!: (v: unknown) => void
      vi.stubGlobal('fetch', vi.fn().mockReturnValue(
        new Promise(r => { resolve = r })
      ))
      const { ui, container } = renderFlyout()
      ui.toggleFlyout('health')
      await nextTick()
      const dots = container.querySelectorAll('.health-dot')
      dots.forEach(dot => expect(dot.classList).toContain('warn'))
      resolve({ ok: true, json: () => Promise.resolve({ aggregator: 'ok', influxdb: 'ok', mqtt: 'ok', simulator: 'ok', audit_mcp: 'ok', control_mcp: 'ok', memory_mcp: 'ok' }) })
    })

    it('dots are err-class when fetch fails', async () => {
      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network error')))
      const { ui, container } = renderFlyout()
      ui.toggleFlyout('health')
      await flushPromises()
      const dots = container.querySelectorAll('.health-dot')
      dots.forEach(dot => expect(dot.classList).toContain('err'))
    })

    it('re-fetches when health flyout is reopened', async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          aggregator: 'ok', influxdb: 'ok', mqtt: 'ok', simulator: 'ok',
          audit_mcp: 'ok', control_mcp: 'ok', memory_mcp: 'ok',
        }),
      })
      vi.stubGlobal('fetch', mockFetch)
      const { ui } = renderFlyout()
      ui.toggleFlyout('health')
      await flushPromises()
      ui.closeFlyout()
      await nextTick()
      ui.toggleFlyout('health')
      await flushPromises()
      expect(mockFetch).toHaveBeenCalledTimes(2)
    })
  })

  describe('faults flyout', () => {
    const MOCK_STATUS = { RawWater_01: 'normal', UV_01: 'suction_starvation', Clarifier_01: 'normal' }
    const MOCK_MODES  = {
      RawWater_01: ['normal', 'suction_starvation', 'cavitation'],
      UV_01:       ['normal', 'suction_starvation', 'lamp_failure'],
      Clarifier_01: ['normal', 'high_turbidity'],
    }

    function mockFaultFetch() {
      vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
        if (url === '/api/fault/status') return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_STATUS) })
        if (url === '/api/fault/modes')  return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_MODES) })
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
      }))
    }

    it('shows a row per instance', async () => {
      mockFaultFetch()
      const { ui, container } = renderFlyout()
      ui.toggleFlyout('faults')
      await flushPromises()
      expect(container.querySelectorAll('.fault-row')).toHaveLength(3)
    })

    it('highlights rows with non-normal faults', async () => {
      mockFaultFetch()
      const { ui, container } = renderFlyout()
      ui.toggleFlyout('faults')
      await flushPromises()
      const active = container.querySelectorAll('.fault-row.fault-active')
      expect(active).toHaveLength(1)
      expect(active[0]!.querySelector('.fault-instance')!.textContent).toBe('UV_01')
    })

    it('shows active fault count badge', async () => {
      mockFaultFetch()
      const { ui, container } = renderFlyout()
      ui.toggleFlyout('faults')
      await flushPromises()
      expect(container.querySelector('.fault-count-badge')?.textContent).toContain('1 active')
    })

    it('select has correct value for each instance', async () => {
      mockFaultFetch()
      const { ui, container } = renderFlyout()
      ui.toggleFlyout('faults')
      await flushPromises()
      const selects = container.querySelectorAll<HTMLSelectElement>('.fault-select')
      expect(selects[0]!.value).toBe('normal')
      expect(selects[1]!.value).toBe('suction_starvation')
    })

    it('changing select calls fetch with correct body', async () => {
      const mockFetch = vi.fn().mockImplementation((url: string) => {
        if (url === '/api/fault/status') return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_STATUS) })
        if (url === '/api/fault/modes')  return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_MODES) })
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
      })
      vi.stubGlobal('fetch', mockFetch)
      const { ui, container } = renderFlyout()
      ui.toggleFlyout('faults')
      await flushPromises()
      const select = container.querySelectorAll<HTMLSelectElement>('.fault-select')[0]!
      await fireEvent.change(select, { target: { value: 'cavitation' } })
      await flushPromises()
      expect(mockFetch).toHaveBeenCalledWith('/api/fault', expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ target: 'RawWater_01', mode: 'cavitation' }),
      }))
    })

    it('shows "Simulator offline" when fetch fails', async () => {
      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
      const { ui, container } = renderFlyout()
      ui.toggleFlyout('faults')
      await flushPromises()
      expect(container.querySelector('.flyout-empty')?.textContent).toContain('offline')
    })
  })
})
