import { expect, test, Page } from '@playwright/test'

async function gotoGraphify(page: Page) {
  await page.goto('/graph/graphify', { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(
    () => {
      const state = (window as any).__graphifyExplorerState
      return state && state.ready === true && state.totalNodes > 0
    },
    null,
    { timeout: 30_000 }
  )
}

test('/graph/graphify loads the enhanced graph explorer', async ({ page }) => {
  await gotoGraphify(page)
  await expect(page.getByRole('heading', { name: 'Graphify Explorer', level: 1 })).toBeVisible()
  await expect(page.getByTestId('graphify-explorer')).toBeVisible()
  await expect(page.getByTestId('graphify-network')).toBeVisible()
})

test('Graphify search focuses a known node and opens the inspector', async ({ page }) => {
  await gotoGraphify(page)
  await page.getByTestId('graphify-search').fill('attention')
  await page.getByTestId('graphify-search').press('Enter')
  await expect(page.getByTestId('graphify-inspector')).toContainText('Attention')
  const state = await page.evaluate(() => (window as any).__graphifyExplorerState)
  expect(state.selectedNodeId).toBe('concept:attention')
  expect(state.searchMatchIds).toContain('concept:attention')
  await expect(page.getByTestId('graphify-open-node')).toBeVisible()
})

test('Graphify reset clears focus without removing filters', async ({ page }) => {
  await gotoGraphify(page)
  await page.getByTestId('graphify-search').fill('attention')
  await page.getByTestId('graphify-search').press('Enter')
  await expect(page.getByTestId('graphify-inspector')).toContainText('Attention')
  await page.getByTestId('graphify-reset').click()
  await expect(page.getByTestId('graphify-inspector')).toContainText('No node selected')
  const state = await page.evaluate(() => (window as any).__graphifyExplorerState)
  expect(state.selectedNodeId).toBe('')
  expect(state.typeFilters.length).toBeGreaterThan(0)
})

test('Graphify type filter toggles deterministically', async ({ page }) => {
  await gotoGraphify(page)
  const before = await page.evaluate(() => (window as any).__graphifyExplorerState.visibleNodes)
  await page.getByTestId('graphify-type-filter-resource').uncheck()
  await page.waitForFunction(
    (previous) => (window as any).__graphifyExplorerState.visibleNodes < previous,
    before
  )
  const after = await page.evaluate(() => (window as any).__graphifyExplorerState.visibleNodes)
  expect(after).toBeLessThan(before)
  await expect(page.getByTestId('graphify-network')).toBeVisible()
})

test('Graphify fullscreen control is present and safe to click', async ({ page }) => {
  await gotoGraphify(page)
  await expect(page.getByTestId('graphify-fullscreen')).toBeVisible()
  await page.getByTestId('graphify-fullscreen').click()
  await expect(page.getByTestId('graphify-network')).toBeVisible()
})

test('Graphify page avoids horizontal overflow on desktop and mobile', async ({ page }) => {
  await gotoGraphify(page)
  const desktopOverflow = await page.evaluate(() => {
    return Math.max(document.body.scrollWidth, document.documentElement.scrollWidth) > window.innerWidth
  })
  expect(desktopOverflow).toBe(false)

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForFunction(
    () => {
      const state = (window as any).__graphifyExplorerState
      return state && state.ready === true && state.totalNodes > 0
    },
    null,
    { timeout: 30_000 }
  )
  const mobileOverflow = await page.evaluate(() => {
    return Math.max(document.body.scrollWidth, document.documentElement.scrollWidth) > window.innerWidth
  })
  expect(mobileOverflow).toBe(false)
})
