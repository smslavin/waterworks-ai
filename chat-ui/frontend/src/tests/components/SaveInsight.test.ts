import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, fireEvent, cleanup } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'
import SaveInsight from '@/components/panels/SaveInsight.vue'
import { useTopologyStore } from '@/stores/topology'
import type { InsightCategory } from '@/stores/topology'

const MOCK_CATEGORIES: InsightCategory[] = [
  { id: 'fault_pattern',   label: 'Fault pattern',   target: 'graph_observation', requires_review: false },
  { id: 'maintenance_flag', label: 'Maintenance flag', target: 'work_item',        requires_review: true  },
  { id: 'operator_note',   label: 'Operator note',   target: 'specialist_memory', requires_review: false },
]

function renderSave(nodeId = 'UV_01', open = true) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const topo = useTopologyStore()
  topo.insightCategories = MOCK_CATEGORIES
  return {
    pinia,
    topo,
    ...render(SaveInsight, {
      props: { nodeId, streamDone: true, open },
      global: { plugins: [pinia] },
    }),
  }
}

describe('SaveInsight', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }))
  })
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  describe('drawer visibility', () => {
    it('is hidden when open=false', () => {
      const { container } = renderSave('UV_01', false)
      expect(container.querySelector('.save-classify')).toBeNull()
    })

    it('is visible when open=true', () => {
      const { container } = renderSave('UV_01', true)
      expect(container.querySelector('.save-classify')).toBeTruthy()
    })
  })

  describe('chip rendering', () => {
    it('renders a chip for each category', () => {
      const { container } = renderSave('UV_01', true)
      const chips = container.querySelectorAll('.chip')
      expect(chips.length).toBe(MOCK_CATEGORIES.length)
    })

    it('note row is hidden before chip selection', () => {
      const { container } = renderSave('UV_01', true)
      expect(container.querySelector('.save-confirm-row')).toBeNull()
    })

    it('chip becomes selected on click', async () => {
      const { container } = renderSave('UV_01', true)
      const chip = container.querySelectorAll('.chip')[0] as HTMLButtonElement
      await fireEvent.click(chip)
      expect(chip.classList.contains('selected')).toBe(true)
    })

    it('note row appears after chip selection', async () => {
      const { container } = renderSave('UV_01', true)
      await fireEvent.click(container.querySelectorAll('.chip')[0]!)
      expect(container.querySelector('.save-confirm-row')).toBeTruthy()
    })
  })

  describe('commit save', () => {
    it('calls saveInsight with categoryId and emits update:open=false', async () => {
      const { container, topo, emitted } = renderSave('UV_01', true)
      await fireEvent.click(container.querySelectorAll('.chip')[0]!)
      await fireEvent.click(container.querySelector('.save-confirm-btn')!)

      expect(topo.nodeById('UV_01')?.saveCount).toBe(1)
      expect(topo.nodeById('UV_01')?.hasMemory).toBe(true)
      expect((emitted()['update:open'] as unknown[][])?.[0]).toEqual([false])
    })

    it('resets chip selection after commit', async () => {
      const { container } = renderSave('UV_01', true)
      const chip = container.querySelectorAll('.chip')[0] as HTMLButtonElement
      await fireEvent.click(chip)
      await fireEvent.click(container.querySelector('.save-confirm-btn')!)
      expect(chip.classList.contains('selected')).toBe(false)
    })

    it('posts to /api/insight with correct body', async () => {
      const mockFetch = vi.fn().mockResolvedValue({ ok: true })
      vi.stubGlobal('fetch', mockFetch)
      const { container } = renderSave('UV_01', true)
      await fireEvent.click(container.querySelectorAll('.chip')[0]!)
      await fireEvent.click(container.querySelector('.save-confirm-btn')!)

      const call = mockFetch.mock.calls.find((c: unknown[]) => (c[0] as string) === '/api/insight')
      expect(call).toBeTruthy()
      const body = JSON.parse((call![1] as RequestInit).body as string)
      expect(body.nodeId).toBe('UV_01')
      expect(body.categoryId).toBe('fault_pattern')
    })
  })
})
