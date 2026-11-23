import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { useReactive } from '@/composables/useReactive'
import { useApprovalStore } from '@/stores/approval'

const PROPOSAL = {
  type: 'action_proposed',
  action_id: 'act-1',
  description: 'Clear the fault on RawWater_01',
  action_type: 'fault_clear',
  target: 'RawWater_01',
  attribute: '',
  value: 'true',
}

// A /api/events response whose body the test feeds and closes.
function sseStream() {
  let ctrl!: ReadableStreamDefaultController<Uint8Array>
  const body = new ReadableStream<Uint8Array>({ start: c => { ctrl = c } })
  const enc = new TextEncoder()
  return {
    response: { ok: true, status: 200, body } as unknown as Response,
    send: (evt: object) => ctrl.enqueue(enc.encode(`data: ${JSON.stringify(evt)}\n\n`)),
    close: () => ctrl.close(),
  }
}

const Host = defineComponent({ setup() { useReactive(); return () => h('div') } })

describe('useReactive alert stream', () => {
  let streams: ReturnType<typeof sseStream>[]
  let pending: object[]
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    setActivePinia(createPinia())
    streams = []
    pending = [PROPOSAL]
    fetchMock = vi.fn(async (url: string) => {
      if (url === '/api/events') {
        const s = sseStream()
        streams.push(s)
        return s.response
      }
      if (url === '/api/alerts/recent') {
        return { ok: true, json: async () => ({ alerts: [], pending_actions: pending }) }
      }
      return { ok: true, json: async () => ({ enabled: false }) }
    })
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
    document.head.innerHTML = ''
  })

  it('loads proposals made while it was disconnected (gh-81)', async () => {
    const wrapper = mount(Host)
    await flushPromises()
    expect(useApprovalStore().queue.map(a => a.id)).toEqual(['act-1'])
    wrapper.unmount()
  })

  it('sends the API token on the stream and the pending-actions call (gh-78)', async () => {
    document.head.innerHTML = '<meta name="api-token" content="secret">'
    const wrapper = mount(Host)
    await flushPromises()
    for (const url of ['/api/events', '/api/alerts/recent']) {
      const init = fetchMock.mock.calls.find(([u]) => u === url)![1] as RequestInit
      expect(new Headers(init.headers).get('Authorization')).toBe('Bearer secret')
    }
    wrapper.unmount()
  })

  it('drops a proposal another client or the timeout settled', async () => {
    pending = []
    const wrapper = mount(Host)
    await flushPromises()
    streams[0]!.send(PROPOSAL)
    await flushPromises()
    expect(useApprovalStore().queue).toHaveLength(1)
    streams[0]!.send({ type: 'action_decision', action_id: 'act-1', decision: 'timed_out' })
    await flushPromises()
    expect(useApprovalStore().queue).toHaveLength(0)
    wrapper.unmount()
  })

  it('reconnects when the server closes the stream, and reloads what is pending', async () => {
    vi.useFakeTimers()
    pending = []
    const wrapper = mount(Host)
    await flushPromises()
    expect(streams).toHaveLength(1)

    pending = [PROPOSAL]          // proposed while the server was restarting
    streams[0]!.close()
    await flushPromises()
    await vi.advanceTimersByTimeAsync(5000)
    await flushPromises()

    expect(streams).toHaveLength(2)
    expect(useApprovalStore().queue.map(a => a.id)).toEqual(['act-1'])
    wrapper.unmount()
  })

  it('does not reconnect after unmount', async () => {
    vi.useFakeTimers()
    const wrapper = mount(Host)
    await flushPromises()
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(10000)
    expect(streams).toHaveLength(1)
  })
})
