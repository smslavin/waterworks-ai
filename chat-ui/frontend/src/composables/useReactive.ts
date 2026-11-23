import { onMounted, onUnmounted, watch } from 'vue'
import { useUIStore } from '@/stores/ui'
import { useAlarmStore } from '@/stores/alarm'
import { useTopologyStore } from '@/stores/topology'
import type { AlarmState } from '@/stores/topology'
import { useApprovalStore, type BackendActionProposal } from '@/stores/approval'
import { authFetch } from '@/lib/api'

const RECONNECT_MS = 5000

export function useReactive() {
  const ui = useUIStore()
  const alarm = useAlarmStore()
  const topo = useTopologyStore()
  const approval = useApprovalStore()

  let eventController: AbortController | null = null

  // Sync reactiveOn indicator from backend (stream is always open)
  async function syncState() {
    try {
      const resp = await fetch('/api/reactive')
      if (!resp.ok) return
      const data = await resp.json() as { enabled: boolean }
      if (data.enabled && ui.multiAgent) {
        ui.reactiveOn = true
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

  // /api/events only reaches subscribers connected when an event fires. A
  // proposal made while this page was closed or reconnecting would otherwise
  // sit unseen until it timed out (gh-81), so load whatever is still waiting
  // each time the stream (re)opens. Runs after the subscription exists, so
  // nothing falls between the two; the store drops duplicates.
  async function loadPendingActions() {
    try {
      const resp = await authFetch('/api/alerts/recent')
      if (!resp.ok) return
      const data = await resp.json() as { pending_actions?: BackendActionProposal[] }
      for (const proposal of data.pending_actions ?? []) {
        approval.pushFromBackend(proposal)
      }
    } catch { /* backend unreachable — the stream's reconnect retries */ }
  }

  function scheduleReconnect() {
    setTimeout(() => {
      // Skip if the stream was stopped, or another connection already started.
      if (eventController === null || !eventController.signal.aborted) return
      eventController = new AbortController()
      void consumeAlertStream(eventController.signal)
    }, RECONNECT_MS)
  }

  async function consumeAlertStream(signal: AbortSignal) {
    try {
      // Gated when chat-ui is exposed (gh-78): send the token.
      const resp = await authFetch('/api/events', { signal })
      if (!resp.ok || !resp.body) throw new Error(`/api/events: ${resp.status}`)
      void loadPendingActions()

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
    }
    // The stream ended: a network error, a refused connection, or the server
    // closing it (a chat-ui restart). Reconnect unless it was stopped.
    if (signal.aborted || eventController === null) return
    eventController.abort()
    scheduleReconnect()
  }

  function handleAlertEvent(evt: Record<string, unknown>) {
    const type = evt.type as string
    if (type === 'ping' || type === 'reactive_advisory') return

    // Reactive-triggered Cascade sessions propose control actions the same way
    // direct chat sessions do (control__propose_action), but the event arrives
    // on this stream (/api/events), not the chat stream — route it to the same
    // approval dialog rather than letting it fall through to the generic alarm
    // handling below (which expects instance_id/attribute and would silently
    // drop it).
    if (type === 'action_proposed') {
      approval.pushFromBackend(evt as unknown as BackendActionProposal)
      return
    }
    // A decision made elsewhere (another desktop, or the 300 s timeout)
    // closes the dialog here too; for this page's own answers it's a no-op.
    if (type === 'action_decision') {
      approval.remove(String(evt.action_id ?? ''))
      return
    }

    // Warning and critical diagnoses both arrive in a follow-up update event,
    // after the alarm itself — patch content onto the existing alarm
    if (type === 'reactive_warning_update' || type === 'reactive_critical_update') {
      const id = `${String(evt.instance_id ?? '')}_${String(evt.attribute ?? 'unknown')}`
      const content = evt.content ? String(evt.content) : ''
      if (content) alarm.setAlarmContent(id, content)
      return
    }

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
      content: evt.content ? String(evt.content) : undefined,
    })

    topo.setAlarmState(instanceId, severity as AlarmState)
  }

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
    } else {
      // Multi-agent turned on — sync reactiveOn indicator (stream is already open)
      await syncState()
    }
  })

  onMounted(() => {
    startAlertStream()  // always connect on mount, same as old EventSource approach
    void syncState()
  })
  onUnmounted(stopAlertStream)

  return { toggle }
}
