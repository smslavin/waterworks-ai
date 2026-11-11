import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChatStore, type Verdict } from '@/stores/chat'
import { useVerdict } from '@/composables/useVerdict'

// gh-25: the backend parses FINDINGS/SUMMARY once and sends a "verdict" event;
// panels read it here instead of running their own regexes over the text.

const BLOCK = 'SUMMARY:\n**Status:** Anomaly Detected\n**Overview:** Low flow.\n\n**Key points:**\n- RawWater_01 flow 40% below setpoint'

function summary(overrides: Partial<Verdict> = {}): Verdict {
  return {
    kind: 'summary',
    status: 'Anomaly Detected',
    confidence: null,
    overview: 'Low flow.',
    points: ['RawWater_01 flow 40% below setpoint'],
    block: BLOCK,
    ...overrides,
  }
}

describe('useVerdict', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('is null until a verdict arrives', () => {
    const chat = useChatStore()
    chat.startStream('area')
    chat.appendToken('area', BLOCK)
    const { verdict, analysisText, statusKey } = useVerdict('area')
    expect(verdict.value).toBeNull()
    expect(analysisText.value).toBe(BLOCK)
    expect(statusKey.value).toBe('unknown')
  })

  it('exposes the verdict and the text without its block', () => {
    const chat = useChatStore()
    chat.startStream('plant')
    chat.appendToken('plant', `${BLOCK}\n\nDetailed breakdown here.`)
    chat.setVerdict('plant', summary())
    const { verdict, analysisText, statusKey } = useVerdict('plant')
    expect(verdict.value?.points).toEqual(['RawWater_01 flow 40% below setpoint'])
    expect(analysisText.value).toBe('Detailed breakdown here.')
    expect(statusKey.value).toBe('anomaly')
  })

  it('removes a trailing FINDINGS block too', () => {
    const chat = useChatStore()
    const block = 'FINDINGS:\nStatus: Fault Detected\nConfidence: 0.9\nKey observations:\n- seal leak'
    chat.startStream('node')
    chat.appendToken('node', `Checked the pump.\n\n${block}`)
    chat.setVerdict('node', summary({ kind: 'findings', status: 'Fault Detected', confidence: 0.9, overview: null, block }))
    const { analysisText, statusKey } = useVerdict('node')
    expect(analysisText.value).toBe('Checked the pump.')
    expect(statusKey.value).toBe('fault')
  })

  it('keeps the full text if the block is not found in it', () => {
    const chat = useChatStore()
    chat.startStream('area')
    chat.appendToken('area', 'Something else entirely.')
    chat.setVerdict('area', summary())
    expect(useVerdict('area').analysisText.value).toBe('Something else entirely.')
  })

  it('is cleared when a new stream starts', () => {
    const chat = useChatStore()
    chat.setVerdict('area', summary())
    chat.startStream('area')
    expect(useVerdict('area').verdict.value).toBeNull()
  })

  it('is cleared with the content', () => {
    const chat = useChatStore()
    chat.setVerdict('area', summary())
    chat.clearContent('area')
    expect(chat.verdict['area']).toBeNull()
  })
})
