import { expect, test, Page } from '@playwright/test'

async function gotoGraphify(page: Page) {
  await page.goto('/graph/graphify', { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(
    () => {
      const state = (window as any).__graphifyExplorerState
      return (
        state &&
        state.ready === true &&
        state.stabilized === true &&
        state.fitComplete === true &&
        state.totalNodes > 0 &&
        state.visibleNodes > 0 &&
        state.visibleEdges > 0 &&
        state.networkWidth > 0 &&
        state.networkHeight > 0 &&
        state.networkScale >= 0.85
      )
    },
    null,
    { timeout: 30_000 }
  )
}

async function expectGraphifyCanvasNotBlank(page: Page) {
  const sample = await page.getByTestId('graphify-network').evaluate((element) => {
    const canvas = element.querySelector('canvas') as HTMLCanvasElement | null
    if (!canvas) return { hasCanvas: false, coloredPixels: 0, width: 0, height: 0 }
    const context = canvas.getContext('2d')
    if (!context) return { hasCanvas: true, coloredPixels: 0, width: canvas.width, height: canvas.height }
    const step = Math.max(4, Math.floor(Math.min(canvas.width, canvas.height) / 80))
    const data = context.getImageData(0, 0, canvas.width, canvas.height).data
    let coloredPixels = 0
    for (let y = 0; y < canvas.height; y += step) {
      for (let x = 0; x < canvas.width; x += step) {
        const index = (y * canvas.width + x) * 4
        const alpha = data[index + 3]
        const red = data[index]
        const green = data[index + 1]
        const blue = data[index + 2]
        if (alpha > 16 && (red > 20 || green > 20 || blue > 20)) coloredPixels += 1
      }
    }
    return { hasCanvas: true, coloredPixels, width: canvas.width, height: canvas.height }
  })
  expect(sample.hasCanvas, 'Graphify network canvas was not mounted').toBe(true)
  expect(sample.width, 'Graphify canvas width should be nonzero').toBeGreaterThan(0)
  expect(sample.height, 'Graphify canvas height should be nonzero').toBeGreaterThan(0)
  expect(sample.coloredPixels, 'Graphify canvas appears visually blank').toBeGreaterThan(20)
}

test('/graph/graphify loads the enhanced graph explorer', async ({ page }) => {
  await gotoGraphify(page)
  await expect(page.getByRole('heading', { name: 'Graphify Explorer', level: 1 })).toBeVisible()
  await expect(page.getByTestId('graphify-explorer')).toBeVisible()
  await expect(page.getByTestId('graphify-network')).toBeVisible()
  await expectGraphifyCanvasNotBlank(page)
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
      return (
        state &&
        state.ready === true &&
        state.stabilized === true &&
        state.fitComplete === true &&
        state.totalNodes > 0 &&
        state.networkScale >= 0.85
      )
    },
    null,
    { timeout: 30_000 }
  )
  const mobileOverflow = await page.evaluate(() => {
    return Math.max(document.body.scrollWidth, document.documentElement.scrollWidth) > window.innerWidth
  })
  expect(mobileOverflow).toBe(false)
})
