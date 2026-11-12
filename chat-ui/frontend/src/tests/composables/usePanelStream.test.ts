import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChatStore } from '@/stores/chat'

// gh-29: NodePanel, AreaPanel and PlantPanel each carried this plumbing.
const calls: { key: string; messages: unknown[]; opts: unknown }[] = []
const stopped: string[] = []
vi.mock('@/composables/useSSE', () => ({
  useSSE: () => ({
    stream: (key: string, messages: unknown[], opts: unknown) => { calls.push({ key, messages, opts }) },
    stopStream: (key: string) => { stopped.push(key) },
  }),
}))

import { usePanelStream } from '@/composables/usePanelStream'

describe('usePanelStream', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    calls.length = 0
    stopped.length = 0
  })

  it('begins a conversation with the panel options read at send time', () => {
    let multi = false
    const p = usePanelStream('area', () => ({ mode: multi ? 'multi' : 'single' }))
    multi = true
    p.begin('Analyze Intake')
    expect(calls).toEqual([
      { key: 'area', messages: [{ role: 'user', content: 'Analyze Intake' }], opts: { mode: 'multi' } },
    ])
  })

  it('sends a follow-up with the whole conversation so far', () => {
    const chat = useChatStore()
    const p = usePanelStream('node', () => ({ mode: 'single' }))
    p.begin('Diagnose RawWater_01')
    chat.appendToken('node', 'Flow is low.')
    chat.finishStream('node')
    p.followUpText.value = '  why?  '
    p.analysisExpanded.value = true
    p.sendFollowUp()

    expect(calls[1]!.messages).toEqual([
      { role: 'user', content: 'Diagnose RawWater_01' },
      { role: 'assistant', content: 'Flow is low.' },
      { role: 'user', content: 'why?' },
    ])
    expect(p.followUpText.value).toBe('')
    expect(p.analysisExpanded.value).toBe(false)
  })

  it('ignores an empty follow-up or one sent mid-stream', () => {
    const chat = useChatStore()
    const p = usePanelStream('plant', () => ({ mode: 'single' }))
    p.followUpText.value = '   '
    p.sendFollowUp()
    chat.startStream('plant')
    p.followUpText.value = 'next?'
    p.sendFollowUp()
    expect(calls).toEqual([])
  })

  it('reset drops the draft and stops the stream', () => {
    const p = usePanelStream('area', () => ({}))
    p.followUpText.value = 'draft'
    p.analysisExpanded.value = true
    p.reset()
    expect(p.followUpText.value).toBe('')
    expect(p.analysisExpanded.value).toBe(false)
    expect(stopped).toEqual(['area'])
  })

  it('statusLine shows context use as a share of the 200k window', () => {
    const chat = useChatStore()
    const p = usePanelStream('node', () => ({}))
    chat.startStream('node')
    expect(p.statusLine('Intake · complete')).toBe('Analyzing…')
    chat.finishStream('node')
    expect(p.statusLine('Intake · complete')).toBe('Intake · complete')
    chat.setInputTokens('node', 50_000)
    expect(p.statusLine('Intake · complete')).toBe('Intake · complete · ctx 25%')
  })
})
