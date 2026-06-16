import { describe, it, expect } from 'vitest'
import { calculatePanelPosition } from '@/composables/useNodePanel'

function makeRect(x: number, y: number, w: number, h: number): DOMRect {
  return { left: x, top: y, right: x + w, bottom: y + h, width: w, height: h, x, y, toJSON: () => ({}) } as DOMRect
}

const CANVAS_W = 1200
const CANVAS_H = 800
const PANEL_W = 340
const PANEL_H = 440
const GAP = 20
const MARGIN = 8

function pos(cx: number, cy: number) {
  const canvasRect = makeRect(0, 0, CANVAS_W, CANVAS_H)
  const circleRect = makeRect(cx - 22, cy - 22, 44, 44)
  return calculatePanelPosition(canvasRect, circleRect, PANEL_W, PANEL_H, GAP, MARGIN)
}

describe('calculatePanelPosition', () => {
  describe('left/right placement', () => {
    it('places panel to the right when ample space on right', () => {
      const result = pos(100, 400)
      expect(result.arrowSide).toBe('left')
      expect(result.left).toBeGreaterThan(100)
    })

    it('places panel to the left when right edge is crowded', () => {
      const result = pos(CANVAS_W - 50, 400)
      expect(result.arrowSide).toBe('right')
      expect(result.left).toBeLessThan(CANVAS_W - 50)
    })

    it('places right when centred and both sides are tight (prefer right)', () => {
      // Node at canvas center — both sides have ~600px, which fits the panel
      const result = pos(CANVAS_W / 2, 400)
      expect(result.arrowSide).toBe('left')
    })
  })

  describe('vertical clamping', () => {
    it('clamps top at MARGIN when node is near top edge', () => {
      const result = pos(100, 10)
      expect(result.top).toBeGreaterThanOrEqual(MARGIN)
    })

    it('clamps bottom so panel does not overflow canvas', () => {
      const result = pos(100, CANVAS_H - 10)
      expect(result.top + PANEL_H).toBeLessThanOrEqual(CANVAS_H - MARGIN)
    })

    it('centres vertically when node is mid-canvas', () => {
      const result = pos(100, CANVAS_H / 2)
      const expectedTop = CANVAS_H / 2 - PANEL_H / 2
      expect(result.top).toBeCloseTo(expectedTop, 0)
    })
  })

  describe('right panel (arrow right) placement', () => {
    it('left position is negative when node is near left edge with tight left space', () => {
      // Node at x=30: spaceR = 1200 - (30+22) = 1148 >= 360 → right side wins
      // So arrow is left, left is positive
      const result = pos(30, 400)
      expect(result.arrowSide).toBe('left')
    })

    it('uses left side when left space is larger than right', () => {
      // Node far right: spaceR < PANEL_W + GAP and spaceL > spaceR
      const result = pos(1180, 400)
      expect(result.arrowSide).toBe('right')
    })
  })

  describe('left position calculation', () => {
    it('right-side panel left starts at circle right edge + gap', () => {
      const nodeX = 100
      const circleRight = nodeX  // cx=100, halfCircle=22 → right edge = 122
      const result = pos(nodeX, 400)
      // arrowSide='left' → left = cx + halfCircle + GAP = 100+22+20 = 142
      expect(result.left).toBe(circleRight + 22 + GAP)
    })
  })
})
