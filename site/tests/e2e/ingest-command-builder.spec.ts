import { expect, Page, test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const SCREENSHOT_DIR = path.resolve(
  process.cwd(),
  '..',
  '..',
  'agent-sessions',
  'harish-llm-wiki',
  'prompt51_branding_ingest_builder',
  'screenshots'
)

function collectPageErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}

async function captureScreenshot(page: Page, name: string) {
  if (process.env.PROMPT51_SCREENSHOTS !== '1') return
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

async function gotoIngest(page: Page) {
  const response = await page.goto('/ingest/', { waitUntil: 'domcontentloaded' })
  expect(response?.status() ?? 0).toBeLessThan(400)
  await expect(page.getByTestId('ingest-command-builder')).toBeVisible()
}

test('ingest command builder loads on desktop and mobile without overflow', async ({ page }) => {
  const errors = collectPageErrors(page)

  await page.setViewportSize({ width: 1440, height: 1000 })
  await gotoIngest(page)
  await expect(page.getByRole('heading', { name: 'Build a local ingest command flow' })).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'desktop-ingest-command-builder')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.getByTestId('ingest-command-builder')).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'mobile-ingest-command-builder')

  expect(errors, `unexpected browser errors:\n${errors.join('\n')}`).toEqual([])
})

test('one URL mode generates add-resource without nonexistent dry-run', async ({ page }) => {
  await gotoIngest(page)

  await page.getByTestId('ingest-url-input').fill('https://example.com/llm-post')
  const addCommand = page.getByTestId('ingest-command-add-input')

  await expect(addCommand).toContainText('.venv/bin/python -m wiki add-resource --url')
  await expect(addCommand).toContainText('https://example.com/llm-post')
  await expect(addCommand).not.toContainText('add-resource --dry-run')
})

test('batch mode generates add-batch dry-run and add commands', async ({ page }) => {
  await gotoIngest(page)

  await page.getByLabel('Batch file').check()
  await page.getByTestId('ingest-batch-input').fill('inputs/my_urls.txt')
  const addCommand = page.getByTestId('ingest-command-add-input')

  await expect(addCommand).toContainText('.venv/bin/python -m wiki add-batch --file')
  await expect(addCommand).toContainText('inputs/my_urls.txt')
  await expect(addCommand).toContainText('--dry-run')
})

test('mock and local providers are shown as no cloud token flows', async ({ page }) => {
  await gotoIngest(page)

  await page.getByTestId('ingest-provider-select').selectOption('mock')
  await expect(page.getByTestId('ingest-token-note')).toContainText(/no cloud tokens/i)
  await expect(page.getByTestId('ingest-command-process')).toContainText('--provider mock')

  await page.getByTestId('ingest-provider-select').selectOption('ollama_local')
  await expect(page.getByTestId('ingest-token-note')).toContainText(/no cloud tokens/i)
  await expect(page.getByTestId('ingest-command-process')).toContainText('--provider ollama_local')
})

test('cloud provider stays dry-run until explicit confirmation adds yes', async ({ page }) => {
  await gotoIngest(page)

  await page.getByTestId('ingest-provider-select').selectOption('ollama_cloud')
  await expect(page.getByTestId('ingest-token-note')).toContainText('.env API keys')
  await expect(page.getByTestId('ingest-command-preview-processing')).toContainText('--dry-run')
  await expect(page.getByTestId('ingest-command-process')).toContainText('--dry-run')
  await expect(page.getByTestId('ingest-command-process')).not.toContainText('--yes')

  await page.getByTestId('ingest-cloud-confirm').check()
  await expect(page.getByTestId('ingest-command-process')).not.toContainText('--dry-run')
  await expect(page.getByTestId('ingest-command-process')).toContainText('--yes')
})

test('yaml manifest is guidance only and no fake import command appears', async ({ page }) => {
  await gotoIngest(page)

  await expect(page.getByTestId('ingest-yaml-reference')).toContainText('Reference only')
  await expect(page.locator('main')).toContainText('inputs/resources.example.yaml')
  for (const forbidden of ['add-yaml', 'import-resources', 'add-resources', 'add-resource --dry-run']) {
    await expect(page.locator('main')).not.toContainText(forbidden)
  }
})
