import { ref } from 'vue'

const PANEL_WIDTH = 340
const PANEL_GAP = 20
const PANEL_MARGIN = 8

export interface PanelPosition {
  top: number
  left: number
  arrowSide: 'left' | 'right'
}

export function calculatePanelPosition(
  canvasRect: DOMRectReadOnly | DOMRect,
  circleRect: DOMRectReadOnly | DOMRect,
  panelWidth: number,
  panelHeight: number,
  gap: number,
  margin: number,
): PanelPosition {
  const cx = circleRect.left - canvasRect.left + circleRect.width / 2
  const cy = circleRect.top - canvasRect.top + circleRect.height / 2

  const halfCircle = circleRect.width / 2
  const spaceR = canvasRect.width - (cx + halfCircle)
  const spaceL = cx - halfCircle

  let left: number
  let arrowSide: 'left' | 'right'

  if (spaceR >= panelWidth + gap) {
    left = cx + halfCircle + gap
    arrowSide = 'left'
  } else if (spaceL >= panelWidth + gap) {
    left = cx - halfCircle - gap - panelWidth
    arrowSide = 'right'
  } else if (spaceR >= spaceL) {
    left = cx + halfCircle + gap
    arrowSide = 'left'
  } else {
    left = cx - halfCircle - gap - panelWidth
    arrowSide = 'right'
  }

  const clampedH = Math.min(panelHeight, canvasRect.height - margin * 2)
  let top = cy - clampedH / 2
  top = Math.max(margin, Math.min(top, canvasRect.height - clampedH - margin))

  return { top, left, arrowSide }
}

export function useNodePanel() {
  const panelTop = ref(-9999)
  const panelLeft = ref(-9999)
  const arrowSide = ref<'left' | 'right'>('left')

  function positionPanel(nodeEl: HTMLElement) {
    const panel = document.getElementById('node-panel')
    const canvas = document.getElementById('topo-canvas')
    if (!panel || !canvas) return
    const circle = nodeEl.querySelector<HTMLElement>('.topo-node-circle')
    if (!circle) return

    const result = calculatePanelPosition(
      canvas.getBoundingClientRect(),
      circle.getBoundingClientRect(),
      PANEL_WIDTH,
      panel.offsetHeight || 440,
      PANEL_GAP,
      PANEL_MARGIN,
    )
    panelTop.value = result.top
    panelLeft.value = result.left
    arrowSide.value = result.arrowSide
  }

  return { panelTop, panelLeft, arrowSide, positionPanel }
}
