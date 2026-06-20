import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export type ConfidenceLevel = 'verified' | 'inferred' | 'suspect'
export type AlarmState = 'normal' | 'warning' | 'critical' | 'pending-approval'

export interface TopologyNode {
  id: string
  area: string
  specialist: string
  equipmentType: string
  confidenceLevel: ConfidenceLevel
  alarmState: AlarmState
  hasMemory: boolean
  saveCount: number
}

export interface TopologyEdge {
  from: string
  to: string
}

export const AREA_ORDER = ['Intake', 'Treatment', 'Distribution'] as const

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

export const useTopologyStore = defineStore('topology', () => {
  const nodes = ref<TopologyNode[]>(INITIAL_NODES.map(n => ({ ...n })))
  const edges = ref<TopologyEdge[]>(INITIAL_EDGES.map(e => ({ ...e })))

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

  function saveInsight(id: string) {
    const node = nodes.value.find(n => n.id === id)
    if (!node) return
    node.hasMemory = true
    node.saveCount++
  }

  return { nodes, edges, nodesByArea, areas, nodeById, setAlarmState, saveInsight }
})
