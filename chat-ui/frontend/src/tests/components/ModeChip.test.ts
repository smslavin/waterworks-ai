import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { nextTick } from 'vue'
import { render, fireEvent, cleanup } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'
import ModeChip from '@/components/header/ModeChip.vue'
import { useUIStore } from '@/stores/ui'

function renderChip() {
  return render(ModeChip, {
    global: { plugins: [createPinia()] },
  })
}

describe('ModeChip', () => {
  beforeEach(() => { setActivePinia(createPinia()) })
  afterEach(() => cleanup())

  it('shows "Single Agent" when multiAgent is false', () => {
    const { container } = renderChip()
    expect(container.querySelector('.mode-chip')?.textContent?.trim()).toContain('Single Agent')
  })

  it('shows "Multi Agent" when toggled on', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const ui = useUIStore()
    const { container } = render(ModeChip, { global: { plugins: [pinia] } })
    ui.toggleMultiAgent()
    await nextTick()
    expect(container.querySelector('.mode-chip')?.textContent?.trim()).toContain('Multi Agent')
  })

  it('has active class when multiAgent is true', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const ui = useUIStore()
    ui.multiAgent = true
    const { container } = render(ModeChip, { global: { plugins: [pinia] } })
    expect(container.querySelector('.mode-chip')?.classList).toContain('active')
  })

  it('toggles multiAgent on click', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const ui = useUIStore()
    const { container } = render(ModeChip, { global: { plugins: [pinia] } })
    expect(ui.multiAgent).toBe(false)
    await fireEvent.click(container.querySelector('.mode-chip')!)
    expect(ui.multiAgent).toBe(true)
  })
})
