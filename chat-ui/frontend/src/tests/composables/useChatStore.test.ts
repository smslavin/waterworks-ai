import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChatStore } from '@/stores/chat'

describe('useChatStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('startStream', () => {
    it('clears content, sets streaming, clears streamDone', () => {
      const chat = useChatStore()
      chat.appendToken('node', 'old content')
      chat.startStream('node')
      expect(chat.content['node']).toBe('')
      expect(chat.streaming['node']).toBe(true)
      expect(chat.streamDone['node']).toBe(false)
    })
  })

  describe('appendToken', () => {
    it('builds content incrementally', () => {
      const chat = useChatStore()
      chat.startStream('node')
      chat.appendToken('node', 'Hello')
      chat.appendToken('node', ' world')
      expect(chat.content['node']).toBe('Hello world')
    })

    it('initialises missing key', () => {
      const chat = useChatStore()
      chat.appendToken('area', 'Hi')
      expect(chat.content['area']).toBe('Hi')
    })
  })

  describe('finishStream', () => {
    it('sets streaming false, streamDone true', () => {
      const chat = useChatStore()
      chat.startStream('node')
      chat.finishStream('node')
      expect(chat.streaming['node']).toBe(false)
      expect(chat.streamDone['node']).toBe(true)
    })
  })

  describe('clearContent', () => {
    it('resets all flags for a key', () => {
      const chat = useChatStore()
      chat.startStream('node')
      chat.appendToken('node', 'some text')
      chat.clearContent('node')
      expect(chat.content['node']).toBe('')
      expect(chat.streaming['node']).toBe(false)
      expect(chat.streamDone['node']).toBe(false)
    })
  })

  describe('multiple keys are independent', () => {
    it('node and area streams do not interfere', () => {
      const chat = useChatStore()
      chat.startStream('node')
      chat.startStream('area')
      chat.appendToken('node', 'node content')
      chat.appendToken('area', 'area content')
      expect(chat.content['node']).toBe('node content')
      expect(chat.content['area']).toBe('area content')
    })
  })
})
