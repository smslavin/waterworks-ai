import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { nextTick } from 'vue'
import { render, cleanup } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'
import ConfigShell from '@/components/config/ConfigShell.vue'
import { useUIStore } from '@/stores/ui'

function renderShell(configMode = false) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const ui = useUIStore()
  ui.configMode = configMode
  return {
    pinia,
    ui,
    ...render(ConfigShell, { global: { plugins: [pinia] } }),
  }
}

describe('ConfigShell', () => {
  beforeEach(() => { setActivePinia(createPinia()) })
  afterEach(() => cleanup())

  it('is hidden when configMode is false', () => {
    const { container } = renderShell(false)
    expect(container.querySelector('.config-shell')).toBeNull()
  })

  it('is visible when configMode is true', () => {
    const { container } = renderShell(true)
    expect(container.querySelector('.config-shell')).toBeTruthy()
  })

  it('renders config header when visible', () => {
    const { container } = renderShell(true)
    expect(container.querySelector('.config-header')).toBeTruthy()
  })

  it('renders config toolbar when visible', () => {
    const { container } = renderShell(true)
    expect(container.querySelector('.config-toolbar')).toBeTruthy()
  })

  it('renders config canvas when visible', () => {
    const { container } = renderShell(true)
    expect(container.querySelector('.config-canvas')).toBeTruthy()
  })

  it('disappears when configMode is set to false', async () => {
    const { container, ui } = renderShell(true)
    expect(container.querySelector('.config-shell')).toBeTruthy()
    ui.exitConfigMode()
    await nextTick()
    expect(container.querySelector('.config-shell')).toBeNull()
  })

  it('exit button calls exitConfigMode', async () => {
    const { container, ui } = renderShell(true)
    const exitBtn = container.querySelector<HTMLButtonElement>('.exit-btn')
    exitBtn!.click()
    await nextTick()
    expect(ui.configMode).toBe(false)
  })
})
