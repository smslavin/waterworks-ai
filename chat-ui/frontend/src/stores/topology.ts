import { defineStore } from 'pinia'
import { ref, reactive, computed } from 'vue'

export type ConfidenceLevel = 'verified' | 'inferred' | 'suspect'
export type AlarmState = 'normal' | 'warning' | 'critical' | 'pending-approval'

export interface InsightCategory {
  id: string
  label: string
  target: 'graph_observation' | 'work_item' | 'confidence_feedback' | 'topology_edit' | 'specialist_memory'
  requires_review: boolean
  correlates_to?: string[]
}

export interface TopologyNode {
  id: string
  area: string
  specialist: string
  equipmentType: string
  confidenceLevel: ConfidenceLevel
  alarmState: AlarmState
  hasMemory: boolean
  saveCount: number
  note?: string
}

export interface TopologyEdge {
  from: string
  to: string
}

// Seeded from topology.yaml's process_areas order (Intake, Treatment,
// Distribution for this plant's own topology.yaml) — a reasonable
// empty-state default, since this renders before loadTopology()'s fetch of
// GET /api/topology resolves. A `reactive()` array (not a plain const, and
// no longer `as const`) so that ConfigCanvas.vue's `v-for="area in
// AREA_ORDER"` — which reads this module binding directly rather than
// through the store — re-renders once loadTopology() replaces its contents
// with the real, possibly-different area list for whichever plant this
// browser is actually pointed at (see enterprise.yaml's per-site
// topology_file). Mutated in place via .splice() so every importer's
// binding (this file, ConfigCanvas.vue, StatusBar.vue, SiteNav.vue) stays
// in sync — reassigning `AREA_ORDER = [...]` here would not update those.
export const AREA_ORDER = reactive<string[]>(['Intake', 'Treatment', 'Distribution'])

/** Mirrors the backend's own status aggregation — multi_agent_loop.py's
 * `overall_status` computation in run_multi_agent() (search that file for
 * `overall_status = (`, currently ~line 1168): "Fault Detected" wins if any
 * specialist's FINDINGS reported Fault, else "Anomaly Detected" if any
 * reported Anomaly, else "Normal" (or "Unknown" if no specialist reported a
 * status at all). This function reimplements that same Fault > Anomaly >
 * Normal precedence via fuzzy substring match, applied to one specialist's
 * status string at a time (see applySpecialistFindings below) rather than
 * aggregated across all specialists the way the backend's version is.
 *
 * KNOWN, DELIBERATE DUPLICATION — not fixed as part of the topology
 * data-source fix (see backend.py's /api/topology + this file's
 * loadTopology()). A real fix would mean exposing multi_agent_loop.py's
 * status-aggregation logic through an API instead of reimplementing its
 * precedence rule here a second time, which is out of scope for a
 * data-source fix. Nothing enforces these two staying in sync — if the
 * Python precedence rule ever changes, this function has to be updated by
 * hand to match.
 *
 * Returns null for Unknown/Error — those shouldn't touch alarmState. */
export function alarmStateFromFindingsStatus(status: string): AlarmState | null {
  if (status === 'Unknown' || status === 'Error') return null
  if (status.includes('Fault')) return 'critical'
  if (status.includes('Anomaly')) return 'warning'
  return 'normal'
}

// Empty-state fallback only, for the render before loadTopology()'s fetch of
// GET /api/topology resolves (or if it fails — backend offline, older
// backend without the route, etc.) — NOT the permanent source of truth.
// Happens to equal this plant's own topology.yaml today, which is why the
// wtp demo looks identical whether or not the fetch has landed yet; a
// genuinely different second plant (different equipment/areas/specialists —
// see enterprise.yaml's per-site topology_file) will briefly render this
// shape and then be replaced by its own real one once loadTopology() lands.
const INITIAL_NODES: TopologyNode[] = [
  { id: 'RawWater_01',      area: 'Intake',       specialist: 'Intake',       equipmentType: 'pump',        confidenceLevel: 'verified', alarmState: 'normal', hasMemory: false, saveCount: 0 },
  { id: 'RawWater_02',      area: 'Intake',       specialist: 'Intake',       equipmentType: 'pump',        confidenceLevel: 'verified', alarmState: 'normal', hasMemory: false, saveCount: 0 },
  { id: 'Clarifier_01',    area: 'Treatment',    specialist: 'Treatment',    equipmentType: 'clarifier',   confidenceLevel: 'verified', alarmState: 'normal', hasMemory: false, saveCount: 0 },
  { id: 'UV_01',            area: 'Treatment',    specialist: 'Treatment',    equipmentType: 'uv_reactor',  confidenceLevel: 'verified', alarmState: 'normal', hasMemory: false, saveCount: 0 },
  { id: 'UV_02',            area: 'Treatment',    specialist: 'Treatment',    equipmentType: 'uv_reactor',  confidenceLevel: 'verified', alarmState: 'normal', hasMemory: false, saveCount: 0 },
  { id: 'Chlorine_01',     area: 'Treatment',    specialist: 'Treatment',    equipmentType: 'dosing_pump', confidenceLevel: 'verified', alarmState: 'normal', hasMemory: false, saveCount: 0 },
  { id: 'Fluoride_01',     area: 'Treatment',    specialist: 'Treatment',    equipmentType: 'dosing_pump', confidenceLevel: 'verified', alarmState: 'normal', hasMemory: false, saveCount: 0 },
  { id: 'HighService_01',  area: 'Distribution', specialist: 'Distribution', equipmentType: 'pump',        confidenceLevel: 'verified', alarmState: 'normal', hasMemory: false, saveCount: 0 },
  { id: 'HighService_02',  area: 'Distribution', specialist: 'Distribution', equipmentType: 'pump',        confidenceLevel: 'verified', alarmState: 'normal', hasMemory: false, saveCount: 0 },
  { id: 'FinishedWater_01', area: 'Distribution', specialist: 'Distribution', equipmentType: 'tank',       confidenceLevel: 'verified', alarmState: 'normal', hasMemory: false, saveCount: 0 },
]

// Flow-diagram lines only — NOT fetched from the backend, and never
// overwritten by loadTopology(). topology.yaml's schema (fieldworks.topology
// EquipmentInstance/ProcessArea — see chat-ui/topology.py) has no
// upstream/downstream or connectivity field at all, so there is nothing
// authoritative for GET /api/topology to derive real edges from; inventing
// a heuristic (e.g. chaining equipment in topology.yaml's declaration
// order) would draw plausible-looking but fabricated connections for a
// genuinely different second plant, which is the exact failure mode this
// fix is meant to remove. So this stays a local, non-authoritative display
// layout for this plant's own topology.yaml specifically. A genuinely
// different second plant's fetched node ids won't match these from/to
// values — TopoEdges.vue's centerOf() already no-ops (skips the line) for
// any id it can't find in the DOM, so the safe failure mode is simply no
// flow lines, not wrong ones. Known, deliberate scope boundary — see
// alarmStateFromFindingsStatus's comment above for the sibling case
// (backend status-aggregation logic duplicated, also left unfixed here).
const INITIAL_EDGES: TopologyEdge[] = [
  { from: 'RawWater_01',    to: 'Clarifier_01'    },
  { from: 'RawWater_02',    to: 'Clarifier_01'    },
  { from: 'Clarifier_01',  to: 'UV_01'            },
  { from: 'Clarifier_01',  to: 'UV_02'            },
  { from: 'UV_01',          to: 'Chlorine_01'     },
  { from: 'UV_02',          to: 'Chlorine_01'     },
  { from: 'Chlorine_01',   to: 'Fluoride_01'      },
  { from: 'Fluoride_01',   to: 'HighService_01'   },
  { from: 'Fluoride_01',   to: 'HighService_02'   },
  { from: 'HighService_01', to: 'FinishedWater_01' },
  { from: 'HighService_02', to: 'FinishedWater_01' },
]

/** Shape of GET /api/topology's response — see backend.py's
 * topology_endpoint(). Only the fields that actually vary per plant/
 * topology.yaml (id/area/specialist/equipmentType) travel over the wire;
 * session-local fields (confidenceLevel/alarmState/hasMemory/saveCount)
 * are seeded fresh client-side the same way INITIAL_NODES always did. */
interface TopologyApiNode {
  id: string
  area: string
  specialist: string
  equipmentType: string
}

interface TopologyApiResponse {
  areas: string[]
  nodes: TopologyApiNode[]
}

export const useTopologyStore = defineStore('topology', () => {
  const nodes = ref<TopologyNode[]>(INITIAL_NODES.map(n => ({ ...n })))
  const edges = ref<TopologyEdge[]>(INITIAL_EDGES.map(e => ({ ...e })))
  const insightCategories = ref<InsightCategory[]>([])

  const nodesByArea = computed(() => {
    const result: Record<string, TopologyNode[]> = {}
    for (const area of AREA_ORDER) {
      result[area] = nodes.value.filter(n => n.area === area)
    }
    return result
  })

  const areas = computed(() =>
    AREA_ORDER.filter(a => nodes.value.some(n => n.area === a))
  )

  function nodeById(id: string): TopologyNode | undefined {
    return nodes.value.find(n => n.id === id)
  }

  function setAlarmState(id: string, state: AlarmState) {
    const node = nodes.value.find(n => n.id === id)
    if (node) node.alarmState = state
  }

  function applySpecialistFindings(specialist: string, status: string) {
    const state = alarmStateFromFindingsStatus(status)
    if (state === null) return
    const target = specialist.toLowerCase()
    for (const node of nodes.value) {
      if (node.specialist.toLowerCase() === target) node.alarmState = state
    }
  }

  /** Fetches this plant's real equipment/area shape from GET /api/topology
   * (see backend.py's topology_endpoint(), derived from the same _topology
   * object every other backend.py route uses) and replaces the
   * INITIAL_NODES/AREA_ORDER empty-state fallback with it. Called from
   * App.vue's onMounted, same trigger point as the other on-mount fetches
   * in this app (GET /api/site, GET /api/fault/status,
   * loadInsightCategories below) — not self-invoked here in the store, so
   * that component-level tests that mount pieces of the UI without App.vue
   * (StripFlyout, StatusBar, SiteNav, …) keep seeing the deterministic
   * INITIAL_NODES/AREA_ORDER fallback instead of an unmocked fetch racing
   * their assertions.
   *
   * Only replaces `nodes`/AREA_ORDER — `edges` is deliberately left alone;
   * see INITIAL_EDGES's comment above for why there's no real backend
   * source for flow connectivity to fetch. A malformed/unexpected response
   * shape (wrong field types, missing keys) is treated the same as a
   * failed fetch: silently keep whatever was already rendering. */
  async function loadTopology() {
    try {
      const res = await fetch('/api/topology')
      if (!res.ok) return
      const data = (await res.json()) as Partial<TopologyApiResponse>

      if (Array.isArray(data.nodes) && data.nodes.length > 0) {
        nodes.value = data.nodes.map(n => ({
          id: n.id,
          area: n.area,
          specialist: n.specialist,
          equipmentType: n.equipmentType,
          confidenceLevel: 'verified',
          alarmState: 'normal',
          hasMemory: false,
          saveCount: 0,
        }))
      }

      if (Array.isArray(data.areas) && data.areas.length > 0) {
        AREA_ORDER.splice(0, AREA_ORDER.length, ...data.areas)
      }
    } catch {
      // backend offline / older backend without this route / network error
      // — non-fatal: UI keeps rendering the INITIAL_NODES/AREA_ORDER
      // fallback already seeded above.
    }
  }

  async function loadInsightCategories() {
    try {
      const res = await fetch('/api/insight/categories')
      if (res.ok) insightCategories.value = await res.json()
    } catch {
      // non-fatal: UI falls back to empty list
    }
  }

  async function saveInsight(id: string, categoryId: string, note?: string) {
    const node = nodes.value.find(n => n.id === id)
    if (!node) return
    // optimistic update
    node.hasMemory = true
    node.saveCount++
    if (note) node.note = note
    try {
      await fetch('/api/insight', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nodeId: id, categoryId, note }),
      })
    } catch {
      // fire-and-forget; optimistic state already applied
    }
  }

  return { nodes, edges, nodesByArea, areas, insightCategories, nodeById, setAlarmState, applySpecialistFindings, loadTopology, loadInsightCategories, saveInsight }
})
