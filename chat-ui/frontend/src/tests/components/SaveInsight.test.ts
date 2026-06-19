import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { render, fireEvent, cleanup } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'
import SaveInsight from '@/components/panels/SaveInsight.vue'
import { useTopologyStore } from '@/stores/topology'

function renderSave(nodeId = 'UV_01', open = true) {
  const pinia = createPinia()
  setActivePinia(pinia)
  return {
    pinia,
    topo: useTopologyStore(),
    ...render(SaveInsight, {
      props: { nodeId, streamDone: true, open },
      global: { plugins: [pinia] },
    }),
  }
}

describe('SaveInsight', () => {
  beforeEach(() => { setActivePinia(createPinia()) })
  afterEach(() => cleanup())

  describe('classify drawer visibility', () => {
    it('is hidden when open=false', () => {
      const { container } = renderSave('UV_01', false)
      expect(container.querySelector('.save-classify')).toBeNull()
    })

    it('is visible when open=true', () => {
      const { container } = renderSave('UV_01', true)
      expect(container.querySelector('.save-classify')).toBeTruthy()
    })
  })

  describe('category dropdown', () => {
    it('renders a category select when open', () => {
      const { container } = renderSave('UV_01', true)
      const select = container.querySelector<HTMLSelectElement>('.save-select')
      expect(select).toBeTruthy()
      expect(select!.querySelectorAll('option').length).toBeGreaterThan(1)
    })

    it('confirm button is disabled before category selection', () => {
      const { container } = renderSave('UV_01', true)
      const btn = container.querySelector<HTMLButtonElement>('.save-confirm-btn')
      expect(btn?.disabled).toBe(true)
    })

    it('confirm button becomes enabled after category selection', async () => {
      const { container } = renderSave('UV_01', true)
      const select = container.querySelector<HTMLSelectElement>('.save-select')!
      await fireEvent.update(select, 'Fault pattern')
      const btn = container.querySelector<HTMLButtonElement>('.save-confirm-btn')
      expect(btn?.disabled).toBe(false)
    })
  })

  describe('commit save', () => {
    it('calls saveInsight on confirm and emits update:open=false', async () => {
      const emitted: unknown[] = []
      const { container, topo, emitted: vueEmitted } = renderSave('UV_01', true)

      const select = container.querySelector<HTMLSelectElement>('.save-select')!
      await fireEvent.update(select, 'Fault pattern')
      await fireEvent.click(container.querySelector('.save-confirm-btn')!)

      expect(topo.nodeById('UV_01')?.saveCount).toBe(1)
      expect(topo.nodeById('UV_01')?.hasMemory).toBe(true)
      expect((vueEmitted()['update:open'] as unknown[][])?.[0]).toEqual([false])
      void emitted
    })

    it('resets selection after commit', async () => {
      const { container } = renderSave('UV_01', true)
      const select = container.querySelector<HTMLSelectElement>('.save-select')!
      await fireEvent.update(select, 'Fault pattern')
      await fireEvent.click(container.querySelector('.save-confirm-btn')!)
      expect(select.value).toBe('')
    })
  })
})
