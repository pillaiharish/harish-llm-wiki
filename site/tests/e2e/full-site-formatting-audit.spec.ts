import { expect, Page, test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

test.setTimeout(240_000)

const SCREENSHOT_DIR = path.resolve(
  process.cwd(),
  '..',
  '..',
  'agent-sessions',
  'harish-llm-wiki',
  process.env.FULL_SITE_UX_AUDIT_ID || 'prompt49_workflow_ux_audit',
  'screenshots'
)

const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 1000 },
  { name: 'compact', width: 1100, height: 900 },
  { name: 'mobile', width: 390, height: 844 },
]

const ROUTES = [
  { name: 'home', path: '/' },
  { name: 'resources', path: '/resources/' },
  {
    name: 'resource-vllm',
    path: '/resources/webpage_df11644e8c0603551fc44887813019ce9cd423157c4e69666ccb5c48b0b11dd1',
  },
  { name: 'resource-rag', path: '/resources/youtube_r2m9DbEmeqI' },
  {
    name: 'resource-pdf',
    path: '/resources/pdf_bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697',
  },
  { name: 'topics', path: '/topics/' },
  { name: 'topic-rag', path: '/topics/rag-retrieval' },
  { name: 'topic-vllm', path: '/topics/vllm' },
  { name: 'topic-evals', path: '/topics/llm-evals' },
  { name: 'concepts', path: '/concepts/' },
  { name: 'concept-attention', path: '/concepts/attention' },
  { name: 'concept-chunking', path: '/concepts/chunking' },
  { name: 'concept-embeddings', path: '/concepts/embeddings' },
  { name: 'learn', path: '/learn/' },
  { name: 'learn-rag', path: '/learn/rag-retrieval' },
  { name: 'learn-inference', path: '/learn/llm-inference' },
  { name: 'explorer', path: '/explorer/' },
  { name: 'graph-index', path: '/graph/' },
  { name: 'graph-explore', path: '/graph/explore' },
  { name: 'graph-graphify', path: '/graph/graphify' },
  { name: 'graph-viewer', path: '/graph/viewer' },
  { name: 'resource-relationships', path: '/graph/resource-relationships' },
  { name: 'review', path: '/review/' },
  { name: 'review-priority', path: '/review/#priority-review-queue' },
  { name: 'review-weak', path: '/review/weak-notes' },
  { name: 'review-missing-citations', path: '/review/missing-citations' },
  { name: 'timeline', path: '/timeline' },
  { name: 'timeline-needs-classification', path: '/timeline#needs-classification' },
  { name: 'timeline-uncategorized', path: '/timeline#uncategorized' },
  { name: 'chunks', path: '/chunks/' },
  { name: 'ingest', path: '/ingest/' },
]

function collectPageErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}

async function captureScreenshot(page: Page, name: string) {
  if (process.env.FULL_SITE_UX_SCREENSHOTS !== '1') return
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true })
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, `${name}.png`),
    fullPage: true,
  })
}

async function waitForRouteReadiness(page: Page, routeName: string) {
  if (routeName === 'explorer') {
    await expect(page.locator('#explorer-q')).toBeVisible({ timeout: 20_000 })
    return
  }
  if (routeName === 'graph-explore' || routeName === 'graph-viewer') {
    await page.waitForFunction(
      () => {
        const cy = (window as any).__graphCy
        return cy && typeof cy.nodes === 'function' && cy.nodes().length > 0
      },
      null,
      { timeout: 30_000 }
    )
    return
  }
  if (routeName === 'graph-graphify') {
    await page.waitForFunction(
      () => {
        const state = (window as any).__graphifyExplorerState
        return (
          state &&
          state.ready === true &&
          state.stabilized === true &&
          state.fitComplete === true &&
          state.networkWidth > 0 &&
          state.networkHeight > 0
        )
      },
      null,
      { timeout: 30_000 }
    )
  }
}

async function expectMeaningfulHeading(page: Page, routeName: string) {
  if (routeName === 'home') {
    await expect(page.locator('.VPHero .name, .VPHero .text').first()).toBeVisible()
    return
  }
  await expect(page.locator('main h1').first()).toBeVisible()
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
    `body overflows horizontally: scrollWidth=${metrics.scrollWidth}, innerWidth=${metrics.innerWidth}`
  ).toBe(false)
}

async function expectNavVisibleAndContained(page: Page) {
  await page.waitForSelector('.VPNavBar, .VPNav', { timeout: 10_000 })
  const metrics = await page.evaluate(() => {
    const nav = document.querySelector('.VPNavBar, .VPNav')
    if (!nav) return null
    const rect = nav.getBoundingClientRect()
    return {
      width: rect.width,
      left: rect.left,
      right: rect.right,
      innerWidth: window.innerWidth,
    }
  })
  expect(metrics, 'VitePress nav should exist').not.toBeNull()
  expect(metrics!.width, 'VitePress nav should be visible').toBeGreaterThan(0)
  expect(metrics!.left, 'VitePress nav starts before viewport').toBeGreaterThanOrEqual(0)
  expect(metrics!.right, 'VitePress nav ends past viewport').toBeLessThanOrEqual(metrics!.innerWidth + 1)
}

async function expectNoVisibleRawMarkdownTables(page: Page) {
  const visibleText = await page.evaluate(() => document.querySelector('main')?.textContent ?? '')
  expect(visibleText, 'raw markdown table separator is visible').not.toContain('|---')
}

test('representative routes have stable formatting across viewports', async ({ page }) => {
  const errors = collectPageErrors(page)

  for (const viewport of VIEWPORTS) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })

    for (const route of ROUTES) {
      const response = await page.goto(route.path, { waitUntil: 'domcontentloaded' })
      expect(response?.status() ?? 0, `${route.path} returned a bad response`).toBeLessThan(400)
      await waitForRouteReadiness(page, route.name)
      await expectNavVisibleAndContained(page)
      await expectMeaningfulHeading(page, route.name)
      await expectNoVisibleRawMarkdownTables(page)
      await expectNoHorizontalOverflow(page)
      await captureScreenshot(page, `${viewport.name}-${route.name}`)
    }
  }

  expect(errors, `unexpected browser errors:\n${errors.join('\n')}`).toEqual([])
})
