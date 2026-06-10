import { expect, Page, test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const DEEP_LINK_QUERY =
  'layout=grid&node=review_page%3Aweak&source=concept%3Achunking&target=concept%3Aattention&path=1'

const SCREENSHOT_DIR = path.resolve(
  process.cwd(),
  '..',
  '.agent-sessions',
  'prompt43_graph_browser_audit',
  'screenshots'
)

function collectPageErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (error) => {
    errors.push(error.message)
  })
  return errors
}

async function expectNoPageErrors(errors: string[]) {
  expect(errors, `unexpected browser errors:\n${errors.join('\n')}`).toEqual([])
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => {
    const width = Math.max(document.body.scrollWidth, document.documentElement.scrollWidth)
    return {
      overflow: width > window.innerWidth,
      scrollWidth: width,
      innerWidth: window.innerWidth,
    }
  })
  expect(
    overflow.overflow,
    `page overflows horizontally: scrollWidth=${overflow.scrollWidth}, innerWidth=${overflow.innerWidth}`
  ).toBe(false)
}

async function captureScreenshot(page: Page, name: string) {
  if (process.env.GRAPH_UX_SCREENSHOTS !== '1') return
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true })
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, `${name}.png`),
    fullPage: true,
  })
}

async function waitForCytoscapeGraph(page: Page) {
  await page.waitForFunction(
    () => {
      const cy = (window as any).__graphCy
      return (
        cy &&
        typeof cy.nodes === 'function' &&
        typeof cy.edges === 'function' &&
        cy.nodes().length > 0 &&
        cy.edges().length > 0
      )
    },
    null,
    { timeout: 30_000 }
  )
}

async function waitForGraphify(page: Page) {
  await page.waitForFunction(
    () => {
      const state = (window as any).__graphifyExplorerState
      return state && state.ready === true && state.totalNodes > 0
    },
    null,
    { timeout: 30_000 }
  )
}

async function setDesktop(page: Page) {
  await page.setViewportSize({ width: 1440, height: 1000 })
}

async function setMobile(page: Page) {
  await page.setViewportSize({ width: 390, height: 844 })
}

test('graph landing has portfolio CTAs and no desktop/mobile overflow', async ({ page }) => {
  const errors = collectPageErrors(page)

  await setDesktop(page)
  const response = await page.goto('/graph/', { waitUntil: 'domcontentloaded' })
  expect(response?.status() ?? 0).toBeLessThan(400)
  await expect(page.getByRole('heading', { name: 'Knowledge Graph', level: 1 })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open Interactive Graph' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open Graphify Explorer' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'View Technical Reference' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'View Resource Relationships' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'View Graph JSON/Data' })).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'graph-landing-desktop')

  await setMobile(page)
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Knowledge Graph', level: 1 })).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'graph-landing-mobile')

  await expectNoPageErrors(errors)
})

test('graph explore default and deep-link states render early without overflow', async ({ page }) => {
  const errors = collectPageErrors(page)

  await setDesktop(page)
  await page.goto('/graph/explore', { waitUntil: 'domcontentloaded' })
  await waitForCytoscapeGraph(page)
  await expect(page.getByRole('heading', { name: 'Graph Workspace', level: 1 })).toBeVisible()
  const desktopCanvas = page.locator('#graph-canvas')
  await expect(desktopCanvas).toBeVisible()
  const desktopBox = await desktopCanvas.boundingBox()
  expect(desktopBox, 'desktop graph canvas has no bounding box').not.toBeNull()
  expect(desktopBox!.y, `desktop graph canvas starts too low at ${desktopBox!.y}px`).toBeLessThan(960)
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'graph-explore-default-desktop')

  await page.goto(`/graph/explore?${DEEP_LINK_QUERY}`, { waitUntil: 'domcontentloaded' })
  await waitForCytoscapeGraph(page)
  await page.waitForFunction(
    () => {
      const explorer = (window as any).__graphExplorerState
      const url = (window as any).__graphUrlState
      return (
        explorer &&
        url &&
        explorer.selectedNodeId === 'review_page:weak' &&
        explorer.layout === 'grid' &&
        explorer.pathFinder?.sourceId === 'concept:chunking' &&
        explorer.pathFinder?.targetId === 'concept:attention'
      )
    },
    null,
    { timeout: 30_000 }
  )
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'graph-explore-deep-link-desktop')

  await setMobile(page)
  await page.reload({ waitUntil: 'domcontentloaded' })
  await waitForCytoscapeGraph(page)
  const mobileCanvas = page.locator('#graph-canvas')
  await expect(mobileCanvas).toBeVisible()
  const mobileBox = await mobileCanvas.boundingBox()
  expect(mobileBox, 'mobile graph canvas has no bounding box').not.toBeNull()
  expect(mobileBox!.y, `mobile graph canvas starts too low at ${mobileBox!.y}px`).toBeLessThan(900)
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'graph-explore-deep-link-mobile')

  await expectNoPageErrors(errors)
})

test('viewer deep link keeps compatibility handoff and live graph data', async ({ page }) => {
  const errors = collectPageErrors(page)

  await setDesktop(page)
  await page.goto(`/graph/viewer?${DEEP_LINK_QUERY}`, { waitUntil: 'domcontentloaded' })
  await waitForCytoscapeGraph(page)
  await expect(page.getByRole('heading', { name: 'Knowledge Graph Viewer', level: 1 })).toBeVisible()
  const handoff = page.locator('#graph-workspace-handoff')
  await expect(handoff).toBeVisible()
  const handoffLink = page.locator('#graph-workspace-handoff-link')
  await expect(handoffLink).toHaveAttribute('href', `/graph/explore?${DEEP_LINK_QUERY}`)
  await expect(page.locator('#graph-live-stats')).toHaveAttribute('data-state', 'ready')
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'graph-viewer-compatibility-desktop')

  await expectNoPageErrors(errors)
})

test('resource relationships report has summary, graph links, and no overflow', async ({ page }) => {
  const errors = collectPageErrors(page)

  await setDesktop(page)
  const response = await page.goto('/graph/resource-relationships', { waitUntil: 'domcontentloaded' })
  expect(response?.status() ?? 0).toBeLessThan(400)
  await expect(
    page.getByRole('heading', { name: 'Resource Relationships', level: 1 })
  ).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Why This Page Matters', level: 2 })).toBeVisible()
  await expect(page.getByRole('link', { name: /Open the full graph workspace/i })).toBeVisible()
  await expect(page.getByRole('link', { name: /Focus on resource relationships/i })).toBeVisible()
  await expect(page.getByRole('table').first()).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'resource-relationships-desktop')

  await setMobile(page)
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Resource Relationships', level: 1 })).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'resource-relationships-mobile')

  await expectNoPageErrors(errors)
})

test('graphify supports deterministic search/filter controls without overflow', async ({ page }) => {
  const errors = collectPageErrors(page)

  await setDesktop(page)
  await page.goto('/graph/graphify', { waitUntil: 'domcontentloaded' })
  await waitForGraphify(page)
  await expect(page.getByRole('heading', { name: 'Graphify Explorer', level: 1 })).toBeVisible()
  await expect(page.getByTestId('graphify-explorer')).toBeVisible()
  await expect(page.getByTestId('graphify-network')).toBeVisible()

  const networkBox = await page.getByTestId('graphify-network').boundingBox()
  expect(networkBox, 'graphify network has no bounding box').not.toBeNull()
  expect(networkBox!.y, `graphify network starts too low at ${networkBox!.y}px`).toBeLessThan(960)
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'graphify-default-desktop')

  await page.getByTestId('graphify-search').fill('attention')
  await page.getByTestId('graphify-search').press('Enter')
  await expect(page.getByTestId('graphify-inspector')).toContainText('Attention')
  let state = await page.evaluate(() => (window as any).__graphifyExplorerState)
  expect(state.selectedNodeId).toBe('concept:attention')
  expect(state.searchMatchIds).toContain('concept:attention')
  await captureScreenshot(page, 'graphify-search-inspector-desktop')

  const beforeFilter = await page.evaluate(() => (window as any).__graphifyExplorerState.visibleNodes)
  await page.getByTestId('graphify-type-filter-resource').uncheck()
  await page.waitForFunction(
    (previous) => (window as any).__graphifyExplorerState.visibleNodes < previous,
    beforeFilter
  )
  state = await page.evaluate(() => (window as any).__graphifyExplorerState)
  expect(state.visibleNodes).toBeLessThan(beforeFilter)
  await expect(page.getByTestId('graphify-network')).toBeVisible()
  await expectNoHorizontalOverflow(page)

  await setMobile(page)
  await page.goto('/graph/graphify', { waitUntil: 'domcontentloaded' })
  await waitForGraphify(page)
  await expect(page.getByTestId('graphify-network')).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'graphify-default-mobile')

  await expect(page.getByTestId('graphify-fullscreen')).toBeVisible()
  await page.getByTestId('graphify-fullscreen').click()
  await expect(page.getByTestId('graphify-network')).toBeVisible()

  await expectNoPageErrors(errors)
})
