import { expect, Page, test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const SCREENSHOT_DIR = path.resolve(
  process.cwd(),
  '..',
  '..',
  'agent-sessions',
  'harish-llm-wiki',
  'prompt52b_home_graph_formatting',
  'screenshots'
)

function collectPageErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}

async function captureScreenshot(page: Page, name: string) {
  if (process.env.PROMPT52B_SCREENSHOTS !== '1') return
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true })
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, `${name}.png`),
    fullPage: true,
  })
}

async function expectNoHorizontalOverflow(page: Page) {
  const metrics = await page.evaluate(() => {
    const width = Math.max(document.body.scrollWidth, document.documentElement.scrollWidth)
    return {
      scrollWidth: width,
      innerWidth: window.innerWidth,
      overflow: width > window.innerWidth,
    }
  })
  expect(
    metrics.overflow,
    `page overflows horizontally: scrollWidth=${metrics.scrollWidth}, innerWidth=${metrics.innerWidth}`
  ).toBe(false)
}

async function gotoExploreWithCy(page: Page) {
  await page.goto('/graph/explore', { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(
    () => {
      const cy = (window as any).__graphCy
      return cy && typeof cy.nodes === 'function' && cy.nodes().length > 0
    },
    null,
    { timeout: 30_000 }
  )
}

test('homepage feature cards are clickable and form one row on wide desktop', async ({ page }) => {
  const errors = collectPageErrors(page)

  await page.setViewportSize({ width: 1440, height: 1000 })
  const response = await page.goto('/', { waitUntil: 'domcontentloaded' })
  expect(response?.status() ?? 0).toBeLessThan(400)

  const featureLinks = page.locator('.VPFeatures a.VPFeature')
  await expect(featureLinks).toHaveCount(5)
  for (const href of ['/resources/', '/review/', '/explorer/', '/timeline', '/ingest/']) {
    await expect(page.locator(`.VPFeatures a.VPFeature[href="${href}"]`)).toBeVisible()
  }

  const boxes = await featureLinks.evaluateAll((links) =>
    links.map((link) => {
      const rect = link.getBoundingClientRect()
      return { top: rect.top, left: rect.left, width: rect.width, height: rect.height }
    })
  )
  expect(boxes, 'expected five home feature boxes').toHaveLength(5)
  const firstRowTop = boxes[0].top
  for (const box of boxes) {
    expect(Math.abs(box.top - firstRowTop), `home feature orphaned to another row: ${JSON.stringify(boxes)}`).toBeLessThan(12)
    expect(box.width, `home feature card is too narrow: ${box.width}`).toBeGreaterThan(180)
  }

  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'homepage-desktop')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.locator('.VPFeatures a.VPFeature').first()).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'homepage-mobile')

  expect(errors, `unexpected browser errors:\n${errors.join('\n')}`).toEqual([])
})

test('graph dashboard rows and metadata stay readable', async ({ page }) => {
  const errors = collectPageErrors(page)

  await page.setViewportSize({ width: 1440, height: 1000 })
  await gotoExploreWithCy(page)

  const firstRow = page.locator('#graph-stat-top-nodes li[data-node-id]').first()
  await expect(firstRow).toBeVisible()
  await expect(firstRow.locator('.ge-top-rank')).toBeVisible()
  await expect(firstRow.locator('.gn-type')).toBeVisible()
  await expect(firstRow.locator('.gn-label')).toBeVisible()
  await expect(firstRow.locator('.ge-degree-badge')).toBeVisible()

  const rowText = await firstRow.innerText()
  expect(rowText, 'degree text should be separated from the node title').not.toMatch(/\S\(degree:/)
  expect(rowText).toMatch(/degree\s+\d+/)

  const firstId = await firstRow.getAttribute('data-node-id')
  expect(firstId).toBeTruthy()
  await firstRow.locator('button').click()
  await expect(page.locator('#graph-stat-selected')).toHaveAttribute('data-selected-id', firstId || '')

  await expect(page.locator('.ge-metadata-grid').first()).toBeVisible()
  const metadataKeyStyles = await page.locator('.ge-metadata-row dt').evaluateAll((keys) =>
    keys.map((key) => {
      const rect = key.getBoundingClientRect()
      const style = getComputedStyle(key)
      return {
        text: (key.textContent || '').trim(),
        width: rect.width,
        height: rect.height,
        whiteSpace: style.whiteSpace,
        wordBreak: style.wordBreak,
      }
    })
  )
  expect(metadataKeyStyles.length, 'expected selected graph metadata rows').toBeGreaterThan(0)
  for (const key of metadataKeyStyles) {
    expect(key.whiteSpace, `metadata key should not wrap: ${JSON.stringify(key)}`).toBe('nowrap')
    expect(key.wordBreak, `metadata key should keep normal word-break: ${JSON.stringify(key)}`).toBe('normal')
    expect(key.height, `metadata key looks letter-wrapped: ${JSON.stringify(key)}`).toBeLessThan(34)
  }

  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'graph-explore-dashboard-desktop')
  await captureScreenshot(page, 'graph-explore-metadata-desktop')

  await page.setViewportSize({ width: 390, height: 844 })
  await gotoExploreWithCy(page)
  await expect(page.locator('#graph-stat-top-nodes li[data-node-id]').first()).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'graph-explore-mobile')

  expect(errors, `unexpected browser errors:\n${errors.join('\n')}`).toEqual([])
})
