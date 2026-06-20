import { onMounted, onUnmounted, watch } from 'vue'
import { useUIStore } from '@/stores/ui'
import { useAlarmStore } from '@/stores/alarm'
import { useTopologyStore } from '@/stores/topology'
import type { AlarmState } from '@/stores/topology'

export function useReactive() {
  const ui = useUIStore()
  const alarm = useAlarmStore()
  const topo = useTopologyStore()

  let eventController: AbortController | null = null

  // Sync initial state from backend on mount
  async function syncState() {
    try {
      const resp = await fetch('/api/reactive')
      if (!resp.ok) return
      const data = await resp.json() as { enabled: boolean }
      if (data.enabled && ui.multiAgent) {
        ui.reactiveOn = true
        startAlertStream()
      }
    } catch { /* backend not running — leave default */ }
  }

  // Called by the toggle button in StatusBar
  async function toggle() {
    if (!ui.multiAgent) return
    const desired = !ui.reactiveOn
    try {
      const resp = await fetch('/api/reactive/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enable: desired }),
      })
      const data = await resp.json() as { enabled: boolean }
      ui.reactiveOn = data.enabled
    } catch {
      ui.reactiveOn = desired   // optimistic fallback when backend unreachable
    }
    if (ui.reactiveOn) startAlertStream()
    else stopAlertStream()
  }

  function startAlertStream() {
    if (eventController) return   // already connected
    eventController = new AbortController()
    void consumeAlertStream(eventController.signal)
  }

  function stopAlertStream() {
    eventController?.abort()
    eventController = null
  }

  async function consumeAlertStream(signal: AbortSignal) {
    try {
      const resp = await fetch('/api/events', { signal })
      if (!resp.ok || !resp.body) return

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw) continue
          try { handleAlertEvent(JSON.parse(raw) as Record<string, unknown>) }
          catch { /* ignore malformed */ }
        }
      }
    } catch (err) {
      if ((err as Error).name === 'AbortError') return
      // Reconnect after 5 s if still running
      setTimeout(() => {
        if (ui.reactiveOn) {
          eventController = new AbortController()
          void consumeAlertStream(eventController.signal)
        }
      }, 5000)
    }
  }

  function handleAlertEvent(evt: Record<string, unknown>) {
    const type = evt.type as string
    // Ignore keepalives, advisories, and updates (initial warning already shown)
    if (type === 'ping' || type === 'reactive_advisory' || type === 'reactive_warning_update') return

    const instanceId = String(evt.instance_id ?? '')
    const attribute  = String(evt.attribute  ?? 'unknown')
    if (!instanceId) return
    const severity: 'critical' | 'warning' = type === 'reactive_critical' ? 'critical' : 'warning'
    const value = evt.value != null ? Number(evt.value).toFixed(2) : '?'
    const nr = evt.normal_range
    const normalRange = Array.isArray(nr) ? (nr as number[]).join('–') : String(nr ?? '?')

    alarm.addAlarm({
      id: `${instanceId}_${attribute}`,
      nodeId: instanceId,
      severity,
      message: `${attribute}: ${value} (normal: ${normalRange})`,
      timestamp: 'just now',
    })

    topo.setAlarmState(instanceId, severity as AlarmState)
  }

  // When multi-agent is turned off, stop the stream and tell the backend
  watch(() => ui.multiAgent, async (enabled) => {
    if (!enabled) {
      stopAlertStream()
      try {
        await fetch('/api/reactive/toggle', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enable: false }),
        })
      } catch { /* ignore */ }
    }
  })

  onMounted(syncState)
  onUnmounted(stopAlertStream)

  return { toggle }
}
