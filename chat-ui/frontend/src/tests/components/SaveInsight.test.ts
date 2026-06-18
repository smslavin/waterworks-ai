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

  describe('classification chips', () => {
    it('renders classification chips when open', () => {
      const { container } = renderSave('UV_01', true)
      expect(container.querySelectorAll('.classify-chip').length).toBeGreaterThan(0)
    })

    it('marks selected chip', async () => {
      const { container } = renderSave('UV_01', true)
      const chip = container.querySelectorAll('.classify-chip')[0]!
      await fireEvent.click(chip)
      expect(chip.classList).toContain('selected')
    })

    it('confirm button is disabled before chip selection', () => {
      const { container } = renderSave('UV_01', true)
      const btn = container.querySelector<HTMLButtonElement>('.save-confirm-btn')
      expect(btn?.disabled).toBe(true)
    })

    it('confirm button becomes enabled after chip selection', async () => {
      const { container } = renderSave('UV_01', true)
      await fireEvent.click(container.querySelectorAll('.classify-chip')[0]!)
      const btn = container.querySelector<HTMLButtonElement>('.save-confirm-btn')
      expect(btn?.disabled).toBe(false)
    })
  })

  describe('commit save', () => {
    it('calls saveInsight on confirm and emits update:open=false', async () => {
      const emitted: unknown[] = []
      const { container, topo, emitted: vueEmitted } = renderSave('UV_01', true)

      await fireEvent.click(container.querySelectorAll('.classify-chip')[0]!)
      await fireEvent.click(container.querySelector('.save-confirm-btn')!)

      expect(topo.nodeById('UV_01')?.saveCount).toBe(1)
      expect(topo.nodeById('UV_01')?.hasMemory).toBe(true)
      expect((vueEmitted()['update:open'] as unknown[][])?.[0]).toEqual([false])
      void emitted
    })

    it('resets selection after commit', async () => {
      const { container } = renderSave('UV_01', true)
      const chip = container.querySelectorAll('.classify-chip')[0]!
      await fireEvent.click(chip)
      await fireEvent.click(container.querySelector('.save-confirm-btn')!)
      // Drawer would close (open=false) but since prop is controlled by parent,
      // the chip selection is cleared regardless
      expect(chip.classList).not.toContain('selected')
    })
  })
})
