import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { nextTick } from 'vue'
import { render, fireEvent, cleanup } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'
import SiteNav from '@/components/statusbar/SiteNav.vue'
import { useUIStore } from '@/stores/ui'

function renderNav(siteNavOpen = false) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const ui = useUIStore()
  ui.siteNavOpen = siteNavOpen
  return {
    pinia,
    ui,
    ...render(SiteNav, { global: { plugins: [pinia] } }),
  }
}

describe('SiteNav', () => {
  beforeEach(() => { setActivePinia(createPinia()) })
  afterEach(() => cleanup())

  it('is hidden when siteNavOpen is false', () => {
    const { container } = renderNav(false)
    expect(container.querySelector('.site-nav')).toBeNull()
  })

  it('is visible when siteNavOpen is true', () => {
    const { container } = renderNav(true)
    expect(container.querySelector('.site-nav')).toBeTruthy()
  })

  it('renders all 4 sites', () => {
    const { container } = renderNav(true)
    expect(container.querySelectorAll('.site-row')).toHaveLength(4)
  })

  it('marks Waterworks as current site', () => {
    const { container } = renderNav(true)
    const rows = container.querySelectorAll('.site-row')
    expect(rows[0].classList).toContain('current')
  })

  it('close button sets siteNavOpen to false', async () => {
    const { container, ui } = renderNav(true)
    await fireEvent.click(container.querySelector('.site-nav-close')!)
    expect(ui.siteNavOpen).toBe(false)
  })

  it('shows correct area status dots for Waterworks', () => {
    const { container } = renderNav(true)
    const waterworksRow = container.querySelector('.site-row.current')
    const dots = waterworksRow?.querySelectorAll('.site-area-dot')
    expect(dots?.[0].classList).toContain('crit')
    expect(dots?.[1].classList).toContain('warn')
    expect(dots?.[2].classList).toContain('crit')
  })

  it('appears after siteNavOpen becomes true', async () => {
    const { container, ui } = renderNav(false)
    expect(container.querySelector('.site-nav')).toBeNull()
    ui.siteNavOpen = true
    await nextTick()
    expect(container.querySelector('.site-nav')).toBeTruthy()
  })
})
