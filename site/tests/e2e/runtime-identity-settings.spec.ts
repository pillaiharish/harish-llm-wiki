import { expect, Page, test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const STORAGE_KEY = 'llmWiki.runtimeIdentity.v1'

const SCREENSHOT_DIR = path.resolve(
  process.cwd(),
  '..',
  '..',
  'agent-sessions',
  'harish-llm-wiki',
  'prompt52c_runtime_identity_settings',
  'screenshots'
)

function collectPageErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}

async function captureScreenshot(page: Page, name: string) {
  if (process.env.PROMPT52C_SCREENSHOTS !== '1') return
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
    `body overflows horizontally: scrollWidth=${metrics.scrollWidth}, innerWidth=${metrics.innerWidth}`
  ).toBe(false)
}

async function gotoSettings(page: Page) {
  const response = await page.goto('/settings/', { waitUntil: 'domcontentloaded' })
  expect(response?.status() ?? 0).toBeLessThan(400)
  await expect(page.getByTestId('runtime-identity-settings')).toBeVisible()
}

async function clearOverride(page: Page) {
  await gotoSettings(page)
  await page.evaluate((key) => window.localStorage.removeItem(key), STORAGE_KEY)
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.getByTestId('runtime-identity-settings')).toBeVisible()
}

async function saveIdentity(page: Page, ownerName: string, siteTitle: string) {
  await page.getByTestId('runtime-owner-input').fill(ownerName)
  await page.getByTestId('runtime-title-input').fill(siteTitle)
  await page.getByTestId('runtime-save').click()
  await expect(page.getByTestId('runtime-status')).toContainText('saved')
}

async function expectNavTitle(page: Page, title: string) {
  await expect(page.locator('.VPNavBarTitle .title span')).toContainText(title)
}

test('settings loads on desktop and mobile without horizontal overflow', async ({ page }) => {
  const errors = collectPageErrors(page)

  await page.setViewportSize({ width: 1440, height: 1000 })
  await clearOverride(page)
  await expect(page.getByRole('heading', { name: 'Runtime identity' })).toBeVisible()
  await expect(page.getByText('never store API keys')).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'desktop-settings')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.getByTestId('runtime-identity-settings')).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'mobile-settings')

  expect(errors, `unexpected browser errors:\n${errors.join('\n')}`).toEqual([])
})

test('browser override updates nav title and document title', async ({ page }) => {
  await clearOverride(page)

  await saveIdentity(page, 'Maya', 'Maya Knowledge Lab')

  await expectNavTitle(page, 'Maya Knowledge Lab')
  await expect.poll(() => page.title()).toContain('Maya Knowledge Lab')
  await expect
    .poll(() => page.evaluate((key) => window.localStorage.getItem(key), STORAGE_KEY))
    .toContain('Maya Knowledge Lab')
})

test('browser override persists across home resources and ingest routes', async ({ page }) => {
  await clearOverride(page)
  await saveIdentity(page, 'Maya', 'Maya Knowledge Lab')

  for (const route of ['/', '/resources/', '/ingest/']) {
    await page.goto(route, { waitUntil: 'domcontentloaded' })
    if (route === '/ingest/') {
      await expect(page.getByTestId('ingest-command-builder')).toBeVisible()
    }
    await expectNavTitle(page, 'Maya Knowledge Lab')
    await expect.poll(() => page.title()).toContain('Maya Knowledge Lab')
  }

  await captureScreenshot(page, 'ingest-after-browser-override')
})

test('reset and clear remove the browser override', async ({ page }) => {
  await clearOverride(page)
  await saveIdentity(page, 'Maya', 'Maya Knowledge Lab')

  await page.getByTestId('runtime-reset').click()
  await expect(page.getByTestId('runtime-status')).toContainText('defaults')
  await expectNavTitle(page, 'Harish LLM Wiki')
  await expect
    .poll(() => page.evaluate((key) => window.localStorage.getItem(key), STORAGE_KEY))
    .toBeNull()

  await saveIdentity(page, 'Ada', 'Ada Knowledge Lab')
  await page.getByTestId('runtime-clear').click()
  await expect(page.getByTestId('runtime-status')).toContainText('cleared')
  await expectNavTitle(page, 'Harish LLM Wiki')
  await expect
    .poll(() => page.evaluate((key) => window.localStorage.getItem(key), STORAGE_KEY))
    .toBeNull()
})

test('public branding json and settings UI do not expose token inputs', async ({ page }) => {
  const response = await page.goto('/site-branding.json', { waitUntil: 'domcontentloaded' })
  expect(response?.status() ?? 0).toBeLessThan(400)
  const jsonText = await page.locator('body').textContent()
  expect(jsonText).toContain('defaultOwnerName')
  expect(jsonText?.toLowerCase()).not.toContain('api_key')
  expect(jsonText?.toLowerCase()).not.toContain('provider')
  expect(jsonText?.toLowerCase()).not.toContain('token')

  await gotoSettings(page)
  await expect(page.locator('input[type="password"]')).toHaveCount(0)
  await expect(page.locator('input[name*="token" i], input[name*="api" i]')).toHaveCount(0)
  await expect(page.getByTestId('runtime-identity-settings')).toContainText('never store API keys')
})
