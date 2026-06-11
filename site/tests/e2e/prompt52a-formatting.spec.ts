import { expect, Page, test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const SCREENSHOT_DIR = path.resolve(
  process.cwd(),
  '..',
  '..',
  'agent-sessions',
  'harish-llm-wiki',
  'prompt52a_formatting_ingest_clarity',
  'screenshots'
)

function collectPageErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}

async function captureScreenshot(page: Page, name: string) {
  if (process.env.PROMPT52A_SCREENSHOTS !== '1') return
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

async function expectGeneratedChipsReadable(page: Page) {
  const badChips = await page
    .locator('.wiki-status-chip, .wiki-type-chip, .wiki-provider-chip, .wiki-model-chip, .wiki-date-cell')
    .evaluateAll((chips) =>
      chips
        .map((chip, index) => {
          const rect = chip.getBoundingClientRect()
          const text = (chip.textContent || '').trim()
          return { index, text, width: rect.width, height: rect.height }
        })
        .filter((chip) => chip.text.length > 3 && (chip.width < 44 || chip.height > 34))
    )
  expect(badChips, `chips look letter-wrapped: ${JSON.stringify(badChips)}`).toEqual([])
}

test('resources index uses readable generated cards on desktop and mobile', async ({ page }) => {
  const errors = collectPageErrors(page)

  await page.setViewportSize({ width: 1440, height: 1000 })
  const response = await page.goto('/resources/', { waitUntil: 'domcontentloaded' })
  expect(response?.status() ?? 0).toBeLessThan(400)
  await expect(page.getByRole('heading', { name: 'Resources', level: 1 })).toBeVisible()
  await expect(page.locator('.wiki-resource-grid')).toBeVisible()
  await expect(page.locator('.wiki-resource-card').first()).toBeVisible()
  await expect(page.locator('main table')).toHaveCount(0)
  await expectGeneratedChipsReadable(page)
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'desktop-resources')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.locator('.wiki-resource-card').first()).toBeVisible()
  await expectGeneratedChipsReadable(page)
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'mobile-resources')

  expect(errors, `unexpected browser errors:\n${errors.join('\n')}`).toEqual([])
})

test('sources index keeps URLs and provider metadata readable', async ({ page }) => {
  const errors = collectPageErrors(page)

  await page.setViewportSize({ width: 1440, height: 1000 })
  const response = await page.goto('/sources/', { waitUntil: 'domcontentloaded' })
  expect(response?.status() ?? 0).toBeLessThan(400)
  await expect(page.getByRole('heading', { name: 'Sources', level: 1 })).toBeVisible()
  await expect(page.locator('.wiki-source-grid')).toBeVisible()
  await expect(page.locator('.wiki-source-card').first()).toBeVisible()
  await expect(page.locator('main table')).toHaveCount(0)
  await expectGeneratedChipsReadable(page)
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'desktop-sources')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.locator('.wiki-source-card').first()).toBeVisible()
  await expectGeneratedChipsReadable(page)
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'mobile-sources')

  expect(errors, `unexpected browser errors:\n${errors.join('\n')}`).toEqual([])
})

test('ingest page puts command builder first and states execution boundary', async ({ page }) => {
  const errors = collectPageErrors(page)

  await page.setViewportSize({ width: 1440, height: 1000 })
  const response = await page.goto('/ingest/', { waitUntil: 'domcontentloaded' })
  expect(response?.status() ?? 0).toBeLessThan(400)
  const builder = page.getByTestId('ingest-command-builder')
  await expect(builder).toBeVisible()
  await expect(page.locator('main')).toContainText('This page builds commands only.')
  await expect(page.locator('main')).toContainText('Use the local control plane prompt next')
  await expect(page.locator('main')).toContainText('These cards are secondary reference.')
  const builderBox = await builder.boundingBox()
  expect(builderBox, 'command builder should have a visible bounding box').not.toBeNull()
  expect(builderBox!.y, `command builder starts too low: ${builderBox!.y}`).toBeLessThan(420)
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'desktop-ingest')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(builder).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'mobile-ingest')

  expect(errors, `unexpected browser errors:\n${errors.join('\n')}`).toEqual([])
})
