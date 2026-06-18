import { test, expect } from '@playwright/test'

test('operational view loads', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.app-header')).toBeVisible()
  await expect(page.locator('.topo-columns')).toBeVisible()
  await expect(page.locator('.status-bar')).toBeVisible()
})

test('topology nodes render', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.topo-node').first()).toBeVisible()
})

test('alarm strip is hidden when there are no active alarms', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.alarm-strip')).toBeHidden()
})

test('clicking a node opens the node panel', async ({ page }) => {
  await page.goto('/')
  await page.locator('.topo-node').first().click()
  await expect(page.locator('.float-panel')).toBeVisible()
})

test('clicking the canvas dismisses the node panel', async ({ page }) => {
  await page.goto('/')
  await page.locator('.topo-node').first().click()
  await expect(page.locator('.float-panel')).toBeVisible()
  await page.locator('.topo-canvas').click({ position: { x: 10, y: 10 } })
  await expect(page.locator('.float-panel')).toBeHidden()
})

test('site nav opens and shows regions', async ({ page }) => {
  await page.goto('/')
  await page.locator('.globe-btn').click()
  await expect(page.locator('.site-nav')).toBeVisible()
  // Back button drills up to region list
  await page.locator('.site-nav-back').click()
  await expect(page.locator('.site-row')).toHaveCount(2) // Metro Region + Valley Region
})
