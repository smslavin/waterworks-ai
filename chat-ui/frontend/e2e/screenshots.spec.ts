/**
 * Screenshot capture for README docs/images/.
 * Run with: npx playwright test --config=playwright.screenshots.config.ts
 * Requires: ./start.sh running (full stack at :8080)
 *
 * Captures:
 *   Screenshot_01    — topology overview (clean state)
 *   Screenshot_05    — fault injection flyout open
 *   Screenshot_06    — node panel analyzing skeleton (streaming started)
 *   Screenshot_alarm — alarm strip active (fault injected)
 */

import { test, expect, type Page } from '@playwright/test'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.resolve(__dirname, '../../../docs/images')

// Injected after page load to eliminate transition/animation timing races.
// Vue <Transition> components still function — transitionend fires instantly.
const NO_TRANSITIONS = `
  *, *::before, *::after {
    transition: none !important;
    animation: none !important;
  }
`

async function loadTopology(page: Page) {
  await page.goto('/')
  await expect(page.locator('.topo-columns')).toBeVisible({ timeout: 15_000 })
  // Let on-mount fetches (fault/status, topology) settle
  await page.waitForTimeout(1_000)
  // Kill transitions so every subsequent screenshot captures final render state
  await page.addStyleTag({ content: NO_TRANSITIONS })
  await page.waitForTimeout(100)
}

async function clearFaults(page: Page) {
  try {
    const resp = await page.request.get('/api/fault/status')
    if (resp.ok()) {
      const status = await resp.json() as Record<string, string>
      for (const [target, mode] of Object.entries(status)) {
        if (mode !== 'normal') {
          await page.request.post('/api/fault', { data: { target, mode: 'normal' } })
        }
      }
    }
  } catch { /* simulator offline */ }
  await page.waitForTimeout(300)
}

// ── Screenshot 01: Topology overview ─────────────────────────────────────────

test('Screenshot_01 — topology overview', async ({ page }) => {
  await clearFaults(page)
  await loadTopology(page)

  // Dismiss any open panels by clicking empty canvas space
  await page.locator('#topo-canvas').click({ position: { x: 20, y: 20 }, force: true })

  await page.screenshot({ path: path.join(OUT, 'Screenshot_01.png') })
  console.log('✓ Screenshot_01 saved')
})

// ── Screenshot 05: Fault injection flyout ────────────────────────────────────

test('Screenshot_05 — fault injection flyout', async ({ page }) => {
  await clearFaults(page)
  await loadTopology(page)

  await page.locator('.strip-btn[title="Fault injection"]').click()

  // Flyout is in the DOM once activeFlyout is set; fault rows load from simulator
  await expect(page.locator('.strip-flyout')).toBeVisible({ timeout: 10_000 })
  await expect(page.locator('.fault-row').first()).toBeVisible({ timeout: 8_000 })

  await page.screenshot({ path: path.join(OUT, 'Screenshot_05.png') })
  console.log('✓ Screenshot_05 saved')
})

// ── Screenshot 06: Node panel with completed response ────────────────────────

test('Screenshot_06 — node panel completed response', async ({ page }) => {
  await loadTopology(page)

  // Click the first node to fire a diagnosis request
  await page.locator('.topo-node').first().click()

  // Panel opens immediately (transitions disabled → full opacity at once)
  await expect(page.locator('.float-panel.visible')).toBeVisible({ timeout: 8_000 })

  // Wait for the model to finish streaming — however long that takes (up to 90s)
  await expect(page.locator('.float-panel.visible .panel-status.done')).toBeVisible({
    timeout: 90_000,
  })

  await page.screenshot({ path: path.join(OUT, 'Screenshot_06.png') })
  console.log('✓ Screenshot_06 saved')
})

// ── Screenshot_alarm: Alarm strip active ─────────────────────────────────────

test('Screenshot_alarm — alarm strip active', async ({ page }) => {
  // Inject fault before page load so App.vue onMounted sees it in /api/fault/status
  try {
    await page.request.post('http://localhost:8080/api/fault', {
      data: { target: 'RawWater_01', mode: 'suction_starvation' },
    })
  } catch {
    console.log('  (simulator offline — alarm strip will be empty)')
  }

  await loadTopology(page)

  try {
    await expect(page.locator('.alarm-strip')).toBeVisible({ timeout: 8_000 })
  } catch {
    console.log('  (alarm strip not visible — check simulator)')
  }

  await page.screenshot({ path: path.join(OUT, 'Screenshot_alarm.png') })
  console.log('✓ Screenshot_alarm saved')

  // Clean up
  try {
    await page.request.post('http://localhost:8080/api/fault', {
      data: { target: 'RawWater_01', mode: 'normal' },
    })
  } catch { /* ignore */ }
})
