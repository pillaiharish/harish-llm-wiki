import { expect, Page, Route, test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const SCREENSHOT_DIR = path.resolve(
  process.cwd(),
  '..',
  '..',
  'agent-sessions',
  'harish-llm-wiki',
  'prompt52f_operations_dashboard',
  'screenshots'
)

function collectPageErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}

async function captureScreenshot(page: Page, name: string) {
  if (process.env.PROMPT52F_SCREENSHOTS !== '1') return
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

function headers() {
  return {
    'access-control-allow-origin': '*',
    'access-control-allow-methods': 'GET, OPTIONS',
    'access-control-allow-headers': 'Content-Type',
    'content-type': 'application/json',
  }
}

async function fulfillJson(route: Route, payload: unknown, status = 200) {
  await route.fulfill({
    status,
    headers: headers(),
    body: JSON.stringify(payload),
  })
}

async function mockReadOnlyControlPlane(page: Page) {
  await page.route('http://127.0.0.1:8765/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    expect(request.method(), `${url.pathname} must stay read-only`).toBe('GET')

    if (url.pathname === '/api/status') {
      await fulfillJson(route, {
        status: 'ok',
        version: 'prompt52e',
        host: '127.0.0.1',
        port: 8765,
        checkedAt: '2026-06-11T00:00:00Z',
      })
      return
    }
    if (url.pathname === '/api/runs') {
      await fulfillJson(route, {
        runs: [
          {
            run_id: 'run-success-1',
            resource_id: 'resource:attention',
            operation: 'note_generation',
            provider: 'mock',
            model: 'mock-model',
            status: 'success',
            started_at: '2026-06-11T00:00:00Z',
            completed_at: '2026-06-11T00:00:02Z',
            total_tokens: 321,
            usage_source: 'estimated',
            estimated_cost: 0,
          },
          {
            run_id: 'run-failed-1',
            resource_id: 'resource:failed',
            operation: 'note_generation',
            provider: 'mock',
            model: 'mock-model',
            status: 'failed',
            started_at: '2026-06-11T00:00:03Z',
            completed_at: '2026-06-11T00:00:04Z',
            total_tokens: 20,
            usage_source: 'estimated',
            estimated_cost: 0,
            error: 'redacted failure summary',
          },
        ],
        checkedAt: '2026-06-11T00:00:00Z',
      })
      return
    }
    if (url.pathname === '/api/token-ledger/summary') {
      await fulfillJson(route, {
        summary: {
          version: 'prompt52e',
          run_count: 2,
          ledger_entry_count: 2,
          success_count: 1,
          failed_count: 1,
          cache_hit_count: 0,
          total_tokens: 341,
          estimated_cost: 0,
          by_provider: {
            mock: { entries: 2, total_tokens: 341, estimated_cost: 0 },
          },
        },
        checkedAt: '2026-06-11T00:00:00Z',
      })
      return
    }
    await fulfillJson(route, { error: { type: 'not_found', message: 'not found' } }, 404)
  })
}

async function expectNoSecretInputs(page: Page) {
  await expect(page.locator('input[type="password"]')).toHaveCount(0)
  const suspicious = await page
    .locator('input, textarea, select')
    .evaluateAll((fields) =>
      fields
        .map((field) => {
          const element = field as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
          return `${element.name || ''} ${element.id || ''} ${element.getAttribute('aria-label') || ''}`.toLowerCase()
        })
        .filter((text) => /api.?key|token|password|secret|authorization/.test(text))
    )
  expect(suspicious).toEqual([])
}

test('operations dashboard loads static fallback without local control plane', async ({ page }) => {
  const errors = collectPageErrors(page)
  await page.route('http://127.0.0.1:8765/api/**', (route) => route.abort())

  await page.setViewportSize({ width: 1440, height: 1000 })
  const response = await page.goto('/operations/', { waitUntil: 'domcontentloaded' })
  expect(response?.status() ?? 0).toBeLessThan(400)
  await expect(page.getByTestId('operations-dashboard')).toBeVisible()
  await expect(page.getByTestId('operations-static-summary')).toBeVisible()
  await expect(page.getByTestId('operations-resource-explorer')).toBeVisible()
  await expect(page.getByTestId('operations-local-unavailable')).toContainText('Local control plane is not running')
  await expect(page.locator('main')).toContainText('no browser API-key fields')
  await expectNoSecretInputs(page)
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'operations-static-desktop')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.getByTestId('operations-dashboard')).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'operations-static-mobile')

  expect(errors, `unexpected browser errors:\n${errors.join('\n')}`).toEqual([])
})

test('operations resource search and filters are deterministic', async ({ page }) => {
  await page.route('http://127.0.0.1:8765/api/**', (route) => route.abort())
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/operations/', { waitUntil: 'domcontentloaded' })
  await expect(page.getByTestId('operations-resource-explorer')).toBeVisible()

  const cards = page.getByTestId('operations-resource-card')
  const initialCount = await cards.count()
  expect(initialCount).toBeGreaterThan(0)

  const firstText = (await cards.first().innerText()).split('\n')[0].trim()
  await page.getByTestId('operations-search').fill(firstText.slice(0, Math.min(firstText.length, 12)))
  await expect(cards.first()).toBeVisible()
  expect(await cards.count()).toBeGreaterThan(0)

  await page.getByTestId('operations-search').fill('zzzz-no-resource-should-match')
  await expect(page.locator('main')).toContainText('No resources match')

  await page.getByTestId('operations-search').fill('')
  const sourceOptions = await page.getByTestId('operations-source-filter').locator('option').count()
  if (sourceOptions > 1) {
    const value = await page.getByTestId('operations-source-filter').locator('option').nth(1).getAttribute('value')
    await page.getByTestId('operations-source-filter').selectOption(value || '')
    await expect(cards.first()).toBeVisible()
  }

  const hrefs = await page.locator('[data-testid="operations-resource-card"] a').evaluateAll((links) =>
    links.map((link) => (link as HTMLAnchorElement).getAttribute('href') || '')
  )
  expect(hrefs.length).toBeGreaterThan(0)
  for (const href of hrefs) {
    expect(href, `resource link should be internal: ${href}`).toMatch(/^\/|^http:\/\/127\.0\.0\.1:5173\//)
  }

  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'operations-resource-filter-desktop')
})

test('operations dashboard renders mocked local run and token data read-only', async ({ page }) => {
  const apiRequests: string[] = []
  page.on('request', (request) => {
    if (request.url().startsWith('http://127.0.0.1:8765/api/')) {
      apiRequests.push(`${request.method()} ${new URL(request.url()).pathname}`)
    }
  })
  await mockReadOnlyControlPlane(page)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/operations/', { waitUntil: 'domcontentloaded' })

  await expect(page.getByTestId('operations-local-ready')).toBeVisible()
  await expect(page.getByTestId('operations-local-summary')).toContainText('2')
  await expect(page.getByTestId('operations-provider-breakdown')).toContainText('mock')
  await expect(page.getByTestId('operations-recent-runs')).toContainText('run-success-1')
  await expect(page.getByTestId('operations-recent-runs')).toContainText('redacted failure summary')
  await expectNoSecretInputs(page)
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'operations-mocked-local-desktop')

  expect(apiRequests).toEqual([
    'GET /api/status',
    'GET /api/runs',
    'GET /api/token-ledger/summary',
  ])
})

