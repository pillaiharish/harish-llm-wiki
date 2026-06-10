import { expect, Page, test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const PROMPT49_SCREENSHOT_DIR = path.resolve(
  process.cwd(),
  '..',
  '..',
  'agent-sessions',
  'harish-llm-wiki',
  'prompt49_workflow_ux_audit',
  'screenshots'
)

const PROMPT49_VERIFY_SCREENSHOT_DIR = path.resolve(
  process.cwd(),
  '..',
  '..',
  'agent-sessions',
  'harish-llm-wiki',
  'prompt49_verification_fix',
  'screenshots'
)

function collectPageErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (error) => {
    errors.push(error.message)
  })
  return errors
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

async function expectNoPageErrors(errors: string[]) {
  expect(errors, `unexpected browser errors:\n${errors.join('\n')}`).toEqual([])
}

async function captureScreenshot(page: Page, name: string) {
  const screenshotDir =
    process.env.PROMPT49_VERIFY_SCREENSHOTS === '1'
      ? PROMPT49_VERIFY_SCREENSHOT_DIR
      : process.env.PROMPT49_SCREENSHOTS === '1'
        ? PROMPT49_SCREENSHOT_DIR
        : null
  if (!screenshotDir) return
  fs.mkdirSync(screenshotDir, { recursive: true })
  await page.screenshot({
    path: path.join(screenshotDir, `${name}.png`),
    fullPage: true,
  })
}

async function expectPriorityQueueUsesCards(page: Page) {
  await expect(page.locator('.review-priority-grid')).toBeVisible()
  await expect(page.locator('.review-priority-grid .review-priority-card').first()).toBeVisible()
  await expect(page.locator('.review-priority-grid table')).toHaveCount(0)
  await expect(page.locator('main table').filter({ hasText: /Priority.*Resource.*Reason.*Status.*Link/i })).toHaveCount(0)
  await expect(page.locator('main')).not.toContainText('| Priority | Resource |')
}

async function expectCommandBlocksContained(page: Page) {
  const badBlocks = await page.locator('pre.ingest-command').evaluateAll((blocks) =>
    blocks
      .map((block, index) => {
        const rect = block.getBoundingClientRect()
        const style = getComputedStyle(block)
        return {
          index,
          left: rect.left,
          right: rect.right,
          width: rect.width,
          overflowX: style.overflowX,
          innerWidth: window.innerWidth,
        }
      })
      .filter((box) => box.width <= 0 || box.left < -1 || box.right > box.innerWidth + 1)
  )
  expect(badBlocks, `command blocks escape viewport: ${JSON.stringify(badBlocks)}`).toEqual([])
}

async function expectClassificationHeadingNearViewport(page: Page) {
  const metrics = await page
    .getByRole('heading', { name: 'Needs classification', level: 3 })
    .first()
    .evaluate((element) => {
      const rect = element.getBoundingClientRect()
      return {
        top: rect.top,
        bottom: rect.bottom,
        innerHeight: window.innerHeight,
      }
    })
  expect(metrics.top, `classification heading is too low: ${JSON.stringify(metrics)}`).toBeLessThan(
    metrics.innerHeight * 0.8
  )
  expect(metrics.bottom, `classification heading is above viewport: ${JSON.stringify(metrics)}`).toBeGreaterThan(0)
}

test('review priority queue renders as readable cards on desktop and mobile', async ({ page }) => {
  const errors = collectPageErrors(page)

  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/review/#priority-review-queue', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Priority review queue', level: 2 })).toBeVisible()
  await expectPriorityQueueUsesCards(page)
  await expect(page.locator('.review-priority-grid')).toBeVisible()
  await expect(page.locator('.review-priority-card').first()).toBeVisible()
  await expect(page.locator('.review-open-link').first()).toBeVisible()
  await expect(page.locator('.review-secondary-link').first()).toBeVisible()
  await expect(page.locator('.review-resource-id').first()).toBeVisible()
  const provenance = page.locator('details.review-provenance').first()
  await expect(provenance).toBeVisible()
  expect(await provenance.evaluate((element) => (element as HTMLDetailsElement).open)).toBe(false)
  await expect(page.locator('.review-provenance code').first()).not.toBeVisible()
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'desktop-review-priority-queue')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expectPriorityQueueUsesCards(page)
  await expect(page.locator('.review-priority-card').first()).toBeVisible()
  const cardBox = await page.locator('.review-priority-card').first().boundingBox()
  expect(cardBox, 'first review card should have a bounding box').not.toBeNull()
  expect(cardBox!.width, `review card is too narrow: ${cardBox!.width}`).toBeGreaterThan(300)
  const mobileProvenance = page.locator('details.review-provenance').first()
  expect(await mobileProvenance.evaluate((element) => (element as HTMLDetailsElement).open)).toBe(false)
  await expect(page.locator('.review-provenance code').first()).not.toBeVisible()
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'mobile-review-priority-queue')

  await expectNoPageErrors(errors)
})

test('timeline classification anchors explain metadata gaps', async ({ page }) => {
  const errors = collectPageErrors(page)

  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/timeline#needs-classification', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Needs classification', level: 3 }).first()).toBeVisible()
  await expectClassificationHeadingNearViewport(page)
  await expect(page.locator('.timeline-classification-note').first()).toContainText(
    /intake items missing topic or concept/i
  )
  await expect(page.locator('.timeline-classification-note').first().getByRole('link', { name: 'Review' })).toHaveAttribute(
    'href',
    '/review/'
  )
  await expect(page.locator('.timeline-classification-note').first().getByRole('link', { name: 'Resources' })).toHaveAttribute(
    'href',
    '/resources/'
  )
  await expect(
    page.locator('.timeline-classification-note').first().getByRole('link', { name: 'Ingest workflow' })
  ).toHaveAttribute('href', '/ingest/')
  await expect(
    page.locator('.timeline-classification-note').first().getByRole('link', { name: 'Fix classification metadata' })
  ).toHaveAttribute('href', '/ingest/#after-ingest')
  await expect(page.getByRole('heading', { name: 'Uncategorized' })).toHaveCount(0)
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'desktop-timeline-needs-classification')

  await page.goto('/timeline#uncategorized', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Needs classification', level: 3 }).first()).toBeVisible()
  await expectClassificationHeadingNearViewport(page)
  await captureScreenshot(page, 'desktop-timeline-uncategorized-compat')
  await expectNoHorizontalOverflow(page)

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Needs classification', level: 3 }).first()).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'mobile-timeline-needs-classification')

  await expectNoPageErrors(errors)
})

test('ingest onboarding explains CLI workflow and token safety', async ({ page }) => {
  const errors = collectPageErrors(page)

  await page.setViewportSize({ width: 1440, height: 1000 })
  const response = await page.goto('/ingest/', { waitUntil: 'domcontentloaded' })
  expect(response?.status() ?? 0).toBeLessThan(400)
  await expect(page.getByRole('heading', { name: 'Ingest & Processing', level: 1 })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Choose Your Processing Mode', level: 2 })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Where API Tokens Are Enabled Or Disabled', level: 2 })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Copyable Command Flow', level: 2 })).toBeVisible()
  await expect(page.locator('main')).toContainText('LLM_PROVIDER=mock')
  await expect(page.locator('main')).toContainText('--provider mock')
  await expect(page.locator('main')).toContainText('ollama_local')
  await expect(page.locator('main')).toContainText('ollama_cloud')
  await expect(page.locator('main')).toContainText('openai_compatible')
  await expect(page.locator('main')).toContainText('--dry-run')
  await expect(page.locator('main')).toContainText('--yes')
  await expect(page.locator('main')).toContainText('does not accept API keys in the browser')
  await expect(page.locator('main')).toContainText('does not trigger provider calls from a page button')
  const main = page.locator('main')
  await expect(main.getByRole('link', { name: 'Review queue' })).toHaveAttribute('href', '/review/')
  await expect(main.getByRole('link', { name: 'Resources', exact: true })).toHaveAttribute('href', '/resources/')
  await expect(main.getByRole('link', { name: 'Timeline classification' })).toHaveAttribute(
    'href',
    '/timeline#needs-classification'
  )
  await expectCommandBlocksContained(page)
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'desktop-ingest')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Where API Tokens Are Enabled Or Disabled', level: 2 })).toBeVisible()
  await expectCommandBlocksContained(page)
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'mobile-ingest')

  await expectNoPageErrors(errors)
})

for (const route of ['/resources/', '/chunks/', '/graph/resource-relationships']) {
  test(`${route} still avoids horizontal overflow`, async ({ page }) => {
    const errors = collectPageErrors(page)

    await page.setViewportSize({ width: 1440, height: 1000 })
    const response = await page.goto(route, { waitUntil: 'domcontentloaded' })
    expect(response?.status() ?? 0, `${route} returned a bad response`).toBeLessThan(400)
    await expectNoHorizontalOverflow(page)

    await page.setViewportSize({ width: 390, height: 844 })
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expectNoHorizontalOverflow(page)

    await expectNoPageErrors(errors)
  })
}
