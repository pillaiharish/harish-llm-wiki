import { expect, Page, Route, test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const SCREENSHOT_DIR = path.resolve(
  process.cwd(),
  '..',
  '..',
  'agent-sessions',
  'harish-llm-wiki',
  'prompt52d_local_control_plane',
  'screenshots'
)

function collectPageErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}

async function captureScreenshot(page: Page, name: string) {
  if (process.env.PROMPT52D_SCREENSHOTS !== '1') return
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
    'access-control-allow-methods': 'GET, POST, OPTIONS',
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

async function mockControlPlane(page: Page, options: { withRuns?: boolean } = {}) {
  await page.route('http://127.0.0.1:8765/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const runSummary = options.withRuns
      ? {
          version: 'prompt52e',
          run_count: 2,
          ledger_entry_count: 1,
          success_count: 1,
          failed_count: 0,
          cache_hit_count: 1,
          total_tokens: 321,
          estimated_cost: 0,
          by_provider: {
            mock: { entries: 1, total_tokens: 321, estimated_cost: 0 },
          },
        }
      : {
          version: 'prompt52e',
          run_count: 0,
          ledger_entry_count: 0,
          success_count: 0,
          failed_count: 0,
          cache_hit_count: 0,
          total_tokens: 0,
          estimated_cost: 0,
          by_provider: {},
        }
    if (request.method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers: headers() })
      return
    }
    if (url.pathname === '/api/status') {
      await fulfillJson(route, {
        status: 'ok',
        version: 'prompt52e',
        host: '127.0.0.1',
        port: 8765,
        checkedAt: '2026-06-11T00:00:00Z',
        currentProvider: {
          provider: 'mock',
          configured: true,
          configuredModel: 'mock-model',
          modelConfigured: true,
        },
      })
      return
    }
    if (url.pathname === '/api/providers') {
      await fulfillJson(route, {
        providers: [
          {
            provider: 'mock',
            label: 'Mock provider',
            tokenKind: 'none',
            configured: true,
            keyPresent: false,
            modelConfigured: true,
            configuredModel: 'mock-model',
            metadataEndpoint: null,
          },
          {
            provider: 'openai_compatible',
            label: 'OpenAI-compatible',
            tokenKind: 'cloud',
            configured: true,
            keyPresent: true,
            modelConfigured: true,
            configuredModel: 'glm-4.5',
            metadataEndpoint: 'openai-compatible /models',
          },
        ],
        checkedAt: '2026-06-11T00:00:00Z',
      })
      return
    }
    if (url.pathname === '/api/models') {
      await fulfillJson(route, {
        models: [
          {
            provider: 'mock',
            configuredModel: 'mock-model',
            modelConfigured: true,
            availableModels: ['mock-model'],
            metadataAvailable: true,
          },
          {
            provider: 'openai_compatible',
            configuredModel: 'glm-4.5',
            modelConfigured: true,
            availableModels: [],
            metadataAvailable: true,
          },
        ],
        checkedAt: '2026-06-11T00:00:00Z',
      })
      return
    }
    if (url.pathname === '/api/runs') {
      await fulfillJson(route, {
        runs: options.withRuns
          ? [
              {
                run_id: 'run-success-1',
                resource_id: 'resource:attention',
                operation: 'note_generation',
                provider: 'mock',
                model: 'mock-model',
                status: 'success',
                completed_at: '2026-06-11T00:00:02Z',
                total_tokens: 321,
                usage_source: 'estimated',
                estimated_cost: 0,
              },
              {
                run_id: 'run-cache-1',
                resource_id: 'resource:cache',
                operation: 'note_generation_cache_hit',
                provider: 'mock',
                model: 'mock-model',
                status: 'cache_hit',
                completed_at: '2026-06-11T00:00:03Z',
                total_tokens: 0,
                usage_source: 'none',
                estimated_cost: 0,
              },
            ]
          : [],
        summary: runSummary,
        checkedAt: '2026-06-11T00:00:00Z',
      })
      return
    }
    if (url.pathname === '/api/token-ledger/summary') {
      await fulfillJson(route, {
        summary: runSummary,
        checkedAt: '2026-06-11T00:00:00Z',
      })
      return
    }
    if (url.pathname === '/api/providers/check') {
      const body = request.postDataJSON() as { provider?: string }
      await fulfillJson(route, {
        provider: body.provider || 'mock',
        checkedAt: '2026-06-11T00:00:01Z',
        configured: true,
        keyPresent: body.provider === 'openai_compatible',
        modelConfigured: true,
        configuredModel: body.provider === 'openai_compatible' ? 'glm-4.5' : 'mock-model',
        availableModels: body.provider === 'openai_compatible' ? ['glm-4.5'] : ['mock-model'],
        modelAvailable: true,
        connectivity: 'ok',
        ok: true,
        error: null,
        message: 'Metadata endpoint is reachable.',
      })
      return
    }
    await fulfillJson(route, { error: { type: 'not_found', message: 'not found' } }, 404)
  })
}

test('control page shows unavailable state and launch guidance without overflow', async ({ page }) => {
  const errors = collectPageErrors(page)
  await page.route('http://127.0.0.1:8765/api/**', (route) => route.abort())

  await page.setViewportSize({ width: 1440, height: 1000 })
  const response = await page.goto('/control/', { waitUntil: 'domcontentloaded' })
  expect(response?.status() ?? 0).toBeLessThan(400)
  await expect(page.getByTestId('control-plane')).toBeVisible()
  await expect(page.getByTestId('control-plane-unavailable')).toBeVisible()
  await expect(page.locator('main')).toContainText('.venv/bin/python -m wiki control-plane')
  await expect(page.locator('main')).toContainText('127.0.0.1')
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'desktop-control-unavailable')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.getByTestId('control-plane-unavailable')).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'mobile-control-unavailable')

  expect(errors, `unexpected browser errors:\n${errors.join('\n')}`).toEqual([])
})

test('mocked local control plane renders provider/model cards and checks metadata', async ({ page }) => {
  await mockControlPlane(page, { withRuns: true })

  const response = await page.goto('/control/', { waitUntil: 'domcontentloaded' })
  expect(response?.status() ?? 0).toBeLessThan(400)
  await expect(page.getByTestId('control-plane-ready')).toBeVisible()
  await expect(page.getByTestId('control-provider-mock')).toContainText('Mock provider')
  await expect(page.getByTestId('control-provider-openai_compatible')).toContainText('OpenAI-compatible')
  await expect(page.getByTestId('control-provider-openai_compatible')).toContainText('Key present')
  await expect(page.locator('main')).not.toContainText('sk-')

  await page.getByTestId('control-check-mock').click()
  await expect(page.getByTestId('control-result-mock')).toContainText('Metadata endpoint is reachable.')
  await expect(page.getByTestId('control-result-mock')).toContainText('Model available: yes')
  await expect(page.getByTestId('control-runs-summary')).toContainText('321')
  await expect(page.getByTestId('control-run-list')).toContainText('resource:attention')
  await expectNoHorizontalOverflow(page)
  await captureScreenshot(page, 'desktop-control-ready')
})

test('mocked local control plane renders no-runs empty state', async ({ page }) => {
  await mockControlPlane(page, { withRuns: false })

  await page.goto('/control/', { waitUntil: 'domcontentloaded' })
  await expect(page.getByTestId('control-plane-ready')).toBeVisible()
  await expect(page.getByTestId('control-runs-empty')).toContainText('No processing runs recorded yet')
  await expectNoHorizontalOverflow(page)
})

test('control page exposes no browser-side token inputs', async ({ page }) => {
  await mockControlPlane(page)
  await page.goto('/control/', { waitUntil: 'domcontentloaded' })
  await expect(page.getByTestId('control-plane-ready')).toBeVisible()

  await expect(page.locator('input[type="password"]')).toHaveCount(0)
  await expect(page.locator('input[name*="token" i], input[name*="api" i]')).toHaveCount(0)
  await expect(page.locator('main')).toContainText('never asks the browser for API keys')
  await expect(page.locator('main')).toContainText('metadata-only checks')
})
