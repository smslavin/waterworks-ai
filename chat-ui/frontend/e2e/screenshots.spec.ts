/**
 * Screenshot capture for README docs/images/.
 * Run with: npx playwright test --config=playwright.screenshots.config.ts
 * Requires: ./start.sh running (full stack at :8080)
 *
 * Captures:
 *   Screenshot_01  — topology overview (clean state)
 *   Screenshot_05  — fault injection flyout open
 *   Screenshot_06  — node panel analyzing skeleton (streaming started)
 *   Screenshot_alarm — alarm strip active (fault injected)
 */

import { test, expect, type Page } from '@playwright/test'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.resolve(__dirname, '../../../docs/images')

async function loadTopology(page: Page) {
  await page.goto('/')
  await expect(page.locator('.topo-columns')).toBeVisible({ timeout: 15_000 })
  // Let any on-mount fetches settle
  await page.waitForTimeout(800)
}

async function clearFaults(page: Page) {
  // Reset all instances to normal before/after shots that need a clean state
  try {
    const statusResp = await page.request.get('/api/fault/status')
    if (statusResp.ok()) {
      const status = await statusResp.json() as Record<string, string>
      for (const [target, mode] of Object.entries(status)) {
        if (mode !== 'normal') {
          await page.request.post('/api/fault', {
            data: { target, mode: 'normal' },
          })
        }
      }
    }
  } catch { /* simulator offline — skip */ }
  await page.waitForTimeout(400)
}

// ── Screenshot 01: Topology overview ─────────────────────────────────────────

test('Screenshot_01 — topology overview', async ({ page }) => {
  await clearFaults(page)
  await loadTopology(page)

  // Ensure no panels or flyouts are open
  await page.locator('#topo-canvas').click({ position: { x: 50, y: 50 }, force: true })
  await page.waitForTimeout(300)

  await page.screenshot({
    path: path.join(OUT, 'Screenshot_01.png'),
    fullPage: false,
  })
  console.log('✓ Screenshot_01 saved')
})

// ── Screenshot 05: Fault injection flyout ────────────────────────────────────

test('Screenshot_05 — fault injection flyout', async ({ page }) => {
  await clearFaults(page)
  await loadTopology(page)

  // Open the fault injection flyout
  await page.locator('.strip-btn[title="Fault injection"]').click()

  // Wait for the flyout to appear and fault rows to load (needs simulator)
  await expect(page.locator('.strip-flyout')).toBeVisible({ timeout: 10_000 })
  await expect(page.locator('.fault-row').first()).toBeVisible({ timeout: 8_000 })

  await page.screenshot({
    path: path.join(OUT, 'Screenshot_05.png'),
    fullPage: false,
  })
  console.log('✓ Screenshot_05 saved')
})

// ── Screenshot 06: Node panel analyzing skeleton ──────────────────────────────

test('Screenshot_06 — node panel analyzing skeleton', async ({ page }) => {
  await loadTopology(page)

  // Click first node — fires the diagnosis request
  const firstNode = page.locator('.topo-node').first()
  await firstNode.click()

  // Wait for the panel to open
  await expect(page.locator('.float-panel.visible')).toBeVisible({ timeout: 8_000 })

  // Capture as soon as the skeleton appears (streaming in progress)
  // If the AI responds before this, verdict-card will be there instead — still a good shot
  try {
    await expect(page.locator('.panel-analyzing')).toBeVisible({ timeout: 6_000 })
  } catch {
    // AI responded very fast or backend offline — capture whatever state we have
  }

  await page.screenshot({
    path: path.join(OUT, 'Screenshot_06.png'),
    fullPage: false,
  })
  console.log('✓ Screenshot_06 saved')
})

// ── Screenshot_alarm: Alarm strip with active fault ───────────────────────────
// Saved as Screenshot_alarm.png for review; rename/number as needed.

test('Screenshot_alarm — alarm strip active', async ({ page }) => {
  // Inject a fault before the page loads so App.vue onMounted picks it up
  const baseURL = 'http://localhost:8080'
  const initReq = page.request

  try {
    await initReq.post(`${baseURL}/api/fault`, {
      data: { target: 'RawWater_01', mode: 'suction_starvation' },
    })
  } catch {
    console.log('  (simulator offline — alarm strip will be empty)')
  }

  await loadTopology(page)

  // Wait for alarm strip to become visible
  try {
    await expect(page.locator('.alarm-strip')).toBeVisible({ timeout: 8_000 })
  } catch {
    console.log('  (alarm strip not visible — simulator may be offline)')
  }

  await page.screenshot({
    path: path.join(OUT, 'Screenshot_alarm.png'),
    fullPage: false,
  })
  console.log('✓ Screenshot_alarm saved')

  // Clean up
  try {
    await initReq.post(`${baseURL}/api/fault`, {
      data: { target: 'RawWater_01', mode: 'normal' },
    })
  } catch { /* ignore */ }
})
