import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useUIStore } from '@/stores/ui'

describe('useUIStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('initial state', () => {
    it('starts in operational mode', () => {
      const ui = useUIStore()
      expect(ui.configMode).toBe(false)
    })

    it('has no active node, area, or panel', () => {
      const ui = useUIStore()
      expect(ui.activeNodeId).toBeNull()
      expect(ui.activeArea).toBeNull()
      expect(ui.activePanel).toBeNull()
    })

    it('starts with reactive mode off', () => {
      const ui = useUIStore()
      expect(ui.reactiveOn).toBe(false)
    })

    it('starts in single-agent mode without deep reasoning', () => {
      const ui = useUIStore()
      expect(ui.multiAgent).toBe(false)
      expect(ui.deepReasoning).toBe(false)
    })
  })

  describe('configMode', () => {
    it('enterConfigMode sets configMode to true', () => {
      const ui = useUIStore()
      ui.enterConfigMode()
      expect(ui.configMode).toBe(true)
    })

    it('exitConfigMode sets configMode to false', () => {
      const ui = useUIStore()
      ui.enterConfigMode()
      ui.exitConfigMode()
      expect(ui.configMode).toBe(false)
    })
  })

  describe('panel management', () => {
    it('setActiveNode opens node panel and clears area', () => {
      const ui = useUIStore()
      ui.setActiveArea('Intake')
      ui.setActiveNode('RawWater_01')
      expect(ui.activeNodeId).toBe('RawWater_01')
      expect(ui.activeArea).toBeNull()
      expect(ui.activePanel).toBe('node')
    })

    it('setActiveArea opens area panel and clears node', () => {
      const ui = useUIStore()
      ui.setActiveNode('RawWater_01')
      ui.setActiveArea('Intake')
      expect(ui.activeArea).toBe('Intake')
      expect(ui.activeNodeId).toBeNull()
      expect(ui.activePanel).toBe('area')
    })

    it('openPlantPanel clears node and area', () => {
      const ui = useUIStore()
      ui.setActiveNode('RawWater_01')
      ui.openPlantPanel()
      expect(ui.activeNodeId).toBeNull()
      expect(ui.activeArea).toBeNull()
      expect(ui.activePanel).toBe('plant')
    })

    it('dismissPanels clears node, area, and panel', () => {
      const ui = useUIStore()
      ui.setActiveNode('RawWater_01')
      ui.dismissPanels()
      expect(ui.activeNodeId).toBeNull()
      expect(ui.activePanel).toBeNull()
    })

    it('dismissPanels also closes flyout and siteNav', () => {
      const ui = useUIStore()
      ui.toggleFlyout('health')
      ui.siteNavOpen = true
      ui.dismissPanels()
      expect(ui.activeFlyout).toBeNull()
      expect(ui.siteNavOpen).toBe(false)
    })
  })

  describe('crumb panels', () => {
    it('openCrumbPanel sets activePanel to "plant" and crumbLevel', () => {
      const ui = useUIStore()
      ui.openCrumbPanel('enterprise')
      expect(ui.activePanel).toBe('plant')
      expect(ui.crumbLevel).toBe('enterprise')
    })

    it('openCrumbPanel clears activeNodeId and activeArea', () => {
      const ui = useUIStore()
      ui.setActiveNode('RawWater_01')
      ui.openCrumbPanel('region')
      expect(ui.activeNodeId).toBeNull()
      expect(ui.activeArea).toBeNull()
    })
  })

  describe('siteNav', () => {
    it('toggleSiteNav opens the site nav', () => {
      const ui = useUIStore()
      ui.toggleSiteNav()
      expect(ui.siteNavOpen).toBe(true)
    })

    it('toggleSiteNav closes it again', () => {
      const ui = useUIStore()
      ui.toggleSiteNav()
      ui.toggleSiteNav()
      expect(ui.siteNavOpen).toBe(false)
    })
  })

  describe('flyout', () => {
    it('toggleFlyout opens a flyout', () => {
      const ui = useUIStore()
      ui.toggleFlyout('health')
      expect(ui.activeFlyout).toBe('health')
    })

    it('toggleFlyout closes an already-open flyout', () => {
      const ui = useUIStore()
      ui.toggleFlyout('health')
      ui.toggleFlyout('health')
      expect(ui.activeFlyout).toBeNull()
    })

    it('toggleFlyout switches to a different flyout', () => {
      const ui = useUIStore()
      ui.toggleFlyout('health')
      ui.toggleFlyout('faults')
      expect(ui.activeFlyout).toBe('faults')
    })

    it('closeFlyout clears the active flyout', () => {
      const ui = useUIStore()
      ui.toggleFlyout('notif')
      ui.closeFlyout()
      expect(ui.activeFlyout).toBeNull()
    })
  })

  describe('toggles', () => {
    it('toggleMultiAgent flips multiAgent', () => {
      const ui = useUIStore()
      ui.toggleMultiAgent()
      expect(ui.multiAgent).toBe(true)
      ui.toggleMultiAgent()
      expect(ui.multiAgent).toBe(false)
    })

    it('toggleDeepReasoning flips deepReasoning', () => {
      const ui = useUIStore()
      ui.toggleDeepReasoning()
      expect(ui.deepReasoning).toBe(true)
    })

    it('toggleReactive flips reactiveOn', () => {
      const ui = useUIStore()
      ui.toggleReactive()
      expect(ui.reactiveOn).toBe(true)
    })
  })
})
