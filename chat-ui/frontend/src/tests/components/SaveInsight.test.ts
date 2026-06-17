import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { render, fireEvent, cleanup, within } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'
import SaveInsight from '@/components/panels/SaveInsight.vue'
import { useTopologyStore } from '@/stores/topology'

function renderSave(nodeId = 'UV_01', streamDone = false) {
  return render(SaveInsight, {
    props: { nodeId, streamDone },
    global: { plugins: [createPinia()] },
  })
}

describe('SaveInsight', () => {
  beforeEach(() => { setActivePinia(createPinia()) })
  afterEach(() => cleanup())

  describe('bookmark button state', () => {
    it('is disabled when stream is not done', () => {
      const { container } = renderSave('UV_01', false)
      const btn = container.querySelector<HTMLButtonElement>('.save-bookmark-btn')
      expect(btn?.disabled).toBe(true)
    })

    it('is enabled when stream is done', () => {
      const { container } = renderSave('UV_01', true)
      const btn = container.querySelector<HTMLButtonElement>('.save-bookmark-btn')
      expect(btn?.disabled).toBe(false)
    })

    it('has active class when stream done and not yet saved', () => {
      const { container } = renderSave('UV_01', true)
      expect(container.querySelector('.save-bookmark-btn.active')).toBeTruthy()
    })
  })

  describe('classify drawer', () => {
    it('is hidden initially', () => {
      const { container } = renderSave('UV_01', true)
      expect(container.querySelector('.save-classify')).toBeNull()
    })

    it('opens when bookmark button is clicked', async () => {
      const { container } = renderSave('UV_01', true)
      await fireEvent.click(container.querySelector('.save-bookmark-btn')!)
      expect(container.querySelector('.save-classify')).toBeTruthy()
    })

    it('closes again on second click', async () => {
      const { container } = renderSave('UV_01', true)
      await fireEvent.click(container.querySelector('.save-bookmark-btn')!)
      await fireEvent.click(container.querySelector('.save-bookmark-btn')!)
      expect(container.querySelector('.save-classify')).toBeNull()
    })
  })

  describe('classification chips', () => {
    it('renders classification chips when drawer is open', async () => {
      const { container } = renderSave('UV_01', true)
      await fireEvent.click(container.querySelector('.save-bookmark-btn')!)
      const chips = container.querySelectorAll('.classify-chip')
      expect(chips.length).toBeGreaterThan(0)
    })

    it('marks selected chip', async () => {
      const { container } = renderSave('UV_01', true)
      await fireEvent.click(container.querySelector('.save-bookmark-btn')!)
      const chip = container.querySelectorAll('.classify-chip')[0]!
      await fireEvent.click(chip)
      expect(chip.classList).toContain('selected')
    })

    it('confirm button is disabled before chip selection', async () => {
      const { container } = renderSave('UV_01', true)
      await fireEvent.click(container.querySelector('.save-bookmark-btn')!)
      const confirmBtn = container.querySelector<HTMLButtonElement>('.save-confirm-btn')
      expect(confirmBtn?.disabled).toBe(true)
    })

    it('confirm button becomes enabled after chip selection', async () => {
      const { container } = renderSave('UV_01', true)
      await fireEvent.click(container.querySelector('.save-bookmark-btn')!)
      await fireEvent.click(container.querySelectorAll('.classify-chip')[0]!)
      const confirmBtn = container.querySelector<HTMLButtonElement>('.save-confirm-btn')
      expect(confirmBtn?.disabled).toBe(false)
    })
  })

  describe('commit save', () => {
    it('calls saveInsight and closes drawer on confirm', async () => {
      const pinia = createPinia()
      setActivePinia(pinia)
      const topo = useTopologyStore()

      const { container } = render(SaveInsight, {
        props: { nodeId: 'UV_01', streamDone: true },
        global: { plugins: [pinia] },
      })

      await fireEvent.click(container.querySelector('.save-bookmark-btn')!)
      await fireEvent.click(container.querySelectorAll('.classify-chip')[0]!)
      await fireEvent.click(container.querySelector('.save-confirm-btn')!)

      expect(topo.nodeById('UV_01')?.saveCount).toBe(1)
      expect(topo.nodeById('UV_01')?.hasMemory).toBe(true)
      expect(container.querySelector('.save-classify')).toBeNull()
    })

    it('shows saved badge after commit', async () => {
      const pinia = createPinia()
      setActivePinia(pinia)

      const { container } = render(SaveInsight, {
        props: { nodeId: 'UV_01', streamDone: true },
        global: { plugins: [pinia] },
      })

      await fireEvent.click(container.querySelector('.save-bookmark-btn')!)
      await fireEvent.click(container.querySelectorAll('.classify-chip')[0]!)
      await fireEvent.click(container.querySelector('.save-confirm-btn')!)

      expect(container.querySelector('.save-badge')).toBeTruthy()
      expect(within(container as HTMLElement).getByText('1')).toBeTruthy()
    })
  })
})
