import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { nextTick } from 'vue'
import { render, fireEvent, cleanup } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'
import StatusBar from '@/components/statusbar/StatusBar.vue'
import { useUIStore } from '@/stores/ui'
import { useTopologyStore } from '@/stores/topology'

function renderBar() {
  const pinia = createPinia()
  setActivePinia(pinia)
  return {
    pinia,
    ui: useUIStore(),
    topo: useTopologyStore(),
    ...render(StatusBar, { global: { plugins: [pinia] } }),
  }
}

describe('StatusBar', () => {
  beforeEach(() => { setActivePinia(createPinia()) })
  afterEach(() => cleanup())

  describe('area dots', () => {
    it('renders one dot button per area', () => {
      const { container } = renderBar()
      expect(container.querySelectorAll('.area-dot-btn')).toHaveLength(3)
    })

    it('Intake dot is critical when a node in Intake is critical', () => {
      const { container, topo } = renderBar()
      topo.setAlarmState('RawWater_01', 'critical')
      topo.setAlarmState('RawWater_02', 'critical')
      const dots = container.querySelectorAll('.area-dot')
      expect(dots[0].classList).toContain('critical')
    })

    it('Intake dot is warning when worst node state is warning', async () => {
      const { container, topo } = renderBar()
      topo.setAlarmState('RawWater_01', 'normal')
      topo.setAlarmState('RawWater_02', 'warning')
      await nextTick()
      const dots = container.querySelectorAll('.area-dot')
      expect(dots[0].classList).toContain('warning')
    })

    it('clicking area dot calls setActiveArea', async () => {
      const { container, ui } = renderBar()
      const btns = container.querySelectorAll('.area-dot-btn')
      await fireEvent.click(btns[1])
      expect(ui.activeArea).toBe('Treatment')
    })
  })

  describe('breadcrumb trail', () => {
    it('shows default crumb trail (Enterprise, Metro Region, Waterworks)', () => {
      const { container } = renderBar()
      const items = container.querySelectorAll('.crumb-item')
      const labels = Array.from(items).map(el => el.textContent?.trim())
      expect(labels).toContain('Enterprise')
      expect(labels).toContain('Metro Region')
      expect(labels).toContain('Waterworks')
    })

    it('appends active area to crumb trail', async () => {
      const { container, ui } = renderBar()
      ui.setActiveArea('Treatment')
      await nextTick()
      const items = container.querySelectorAll('.crumb-item')
      const labels = Array.from(items).map(el => el.textContent?.trim())
      expect(labels).toContain('Treatment')
    })

    it('appends area + node to crumb trail when node is active', async () => {
      const { container, ui } = renderBar()
      ui.setActiveNode('UV_01')
      await nextTick()
      const items = container.querySelectorAll('.crumb-item')
      const labels = Array.from(items).map(el => el.textContent?.trim())
      expect(labels).toContain('Treatment')
      expect(labels).toContain('UV_01')
    })

    it('"Waterworks" crumb click calls openCrumbPanel("plant")', async () => {
      const { container, ui } = renderBar()
      const items = container.querySelectorAll('.crumb-item')
      const waterworksBtn = Array.from(items).find(el => el.textContent?.trim() === 'Waterworks')
      await fireEvent.click(waterworksBtn!)
      expect(ui.activePanel).toBe('plant')
      expect(ui.crumbLevel).toBe('plant')
    })

    it('"Enterprise" crumb click calls openCrumbPanel("enterprise")', async () => {
      const { container, ui } = renderBar()
      const items = container.querySelectorAll('.crumb-item')
      const btn = Array.from(items).find(el => el.textContent?.trim() === 'Enterprise')
      await fireEvent.click(btn!)
      expect(ui.crumbLevel).toBe('enterprise')
    })
  })

  describe('reactive toggle', () => {
    it('has active class when reactiveOn is true', () => {
      const { container } = renderBar()
      expect(container.querySelector('.reactive-toggle')?.classList).toContain('active')
    })

    it('does not have active class when reactiveOn is false', async () => {
      const { container, ui } = renderBar()
      ui.toggleReactive()
      await nextTick()
      expect(container.querySelector('.reactive-toggle')?.classList).not.toContain('active')
    })

    it('clicking toggle calls toggleReactive', async () => {
      const { container, ui } = renderBar()
      expect(ui.reactiveOn).toBe(true)
      await fireEvent.click(container.querySelector('.reactive-toggle')!)
      expect(ui.reactiveOn).toBe(false)
    })
  })

  describe('site nav toggle', () => {
    it('globe button is not active by default', () => {
      const { container } = renderBar()
      expect(container.querySelector('.globe-btn')?.classList).not.toContain('active')
    })

    it('clicking globe calls toggleSiteNav', async () => {
      const { container, ui } = renderBar()
      await fireEvent.click(container.querySelector('.globe-btn')!)
      expect(ui.siteNavOpen).toBe(true)
    })
  })
})
