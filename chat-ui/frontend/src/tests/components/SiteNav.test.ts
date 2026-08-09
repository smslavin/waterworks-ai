import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { nextTick } from 'vue'
import { render, fireEvent, cleanup } from '@testing-library/vue'
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import SiteNav from '@/components/statusbar/SiteNav.vue'
import { useUIStore } from '@/stores/ui'

const DIRECTORY = {
  wtp: { name: 'Waterworks', region: 'Metro Region', chat_ui_url: 'http://localhost:8080' },
  wtp2: { name: 'Eastside', region: 'Metro Region', chat_ui_url: 'http://localhost:8010' },
}

function mockSitesFetch(directory: Record<string, unknown> = DIRECTORY) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    json: async () => directory,
  }))
}

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
  beforeEach(() => {
    setActivePinia(createPinia())
    mockSitesFetch()
  })
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('is hidden when siteNavOpen is false', () => {
    const { container } = renderNav(false)
    expect(container.querySelector('.site-nav')).toBeNull()
  })

  it('is visible when siteNavOpen is true', () => {
    const { container } = renderNav(true)
    expect(container.querySelector('.site-nav')).toBeTruthy()
  })

  it('shows this plant even before the directory fetch resolves', () => {
    const { container } = renderNav(true)
    const rows = container.querySelectorAll('.site-row')
    expect(rows).toHaveLength(1)
    expect(rows[0]!.textContent).toContain('Waterworks')
  })

  it('renders sites from the fetched directory once loaded', async () => {
    const { container } = renderNav(true)
    await flushPromises()
    expect(container.querySelectorAll('.site-row')).toHaveLength(2)
    expect(container.textContent).toContain('Eastside')
  })

  it('marks the active site as current', async () => {
    const { container } = renderNav(true)
    await flushPromises()
    const rows = Array.from(container.querySelectorAll('.site-row'))
    const current = rows.find(r => r.textContent?.includes('Waterworks'))
    expect(current?.classList).toContain('current')
  })

  it('falls back to just this plant when the directory fetch fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('enterprise layer down')))
    const { container } = renderNav(true)
    await flushPromises()
    expect(container.querySelectorAll('.site-row')).toHaveLength(1)
    expect(container.querySelector('.site-nav-empty')).toBeTruthy()
  })

  it('shows region list when back button is clicked', async () => {
    const { container } = renderNav(true)
    await flushPromises()
    await fireEvent.click(container.querySelector('.site-nav-back')!)
    // One region present (Metro Region) since both fetched sites share it
    expect(container.querySelectorAll('.site-row')).toHaveLength(1)
  })

  it('close button sets siteNavOpen to false', async () => {
    const { container, ui } = renderNav(true)
    await fireEvent.click(container.querySelector('.site-nav-close')!)
    expect(ui.siteNavOpen).toBe(false)
  })

  it('clicking the current site just closes the nav, without navigating', async () => {
    const { container, ui } = renderNav(true)
    await flushPromises()
    const rows = Array.from(container.querySelectorAll('.site-row'))
    const current = rows.find(r => r.textContent?.includes('Waterworks'))
    await fireEvent.click(current!)
    expect(ui.siteNavOpen).toBe(false)
  })

  it('clicking a different live site navigates the browser there', async () => {
    // jsdom throws on direct assignment to window.location.href; stub the
    // whole global instead — only .href is read by SiteNav.
    const stubLocation = { href: '' }
    vi.stubGlobal('location', stubLocation)
    const { container } = renderNav(true)
    await flushPromises()
    const rows = Array.from(container.querySelectorAll('.site-row'))
    const eastside = rows.find(r => r.textContent?.includes('Eastside'))
    await fireEvent.click(eastside!)
    expect(stubLocation.href).toBe('http://localhost:8010/')
  })

  it('carries multiAgent and reactive toggles as query params on the navigation', async () => {
    const stubLocation = { href: '' }
    vi.stubGlobal('location', stubLocation)
    const { container, ui } = renderNav(true)
    ui.multiAgent = true
    ui.reactiveOn = true
    await flushPromises()
    const rows = Array.from(container.querySelectorAll('.site-row'))
    const eastside = rows.find(r => r.textContent?.includes('Eastside'))
    await fireEvent.click(eastside!)
    const url = new URL(stubLocation.href)
    expect(url.searchParams.get('multiAgent')).toBe('1')
    expect(url.searchParams.get('reactive')).toBe('1')
  })

  it('does not carry toggles that are off', async () => {
    const stubLocation = { href: '' }
    vi.stubGlobal('location', stubLocation)
    const { container } = renderNav(true)
    await flushPromises()
    const rows = Array.from(container.querySelectorAll('.site-row'))
    const eastside = rows.find(r => r.textContent?.includes('Eastside'))
    await fireEvent.click(eastside!)
    const url = new URL(stubLocation.href)
    expect(url.searchParams.has('multiAgent')).toBe(false)
    expect(url.searchParams.has('reactive')).toBe(false)
  })

  it('appears after siteNavOpen becomes true', async () => {
    const { container, ui } = renderNav(false)
    expect(container.querySelector('.site-nav')).toBeNull()
    ui.siteNavOpen = true
    await nextTick()
    expect(container.querySelector('.site-nav')).toBeTruthy()
  })
})
