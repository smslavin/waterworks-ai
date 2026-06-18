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
})
