import { test, expect } from '@playwright/test'

/**
 * V1 MVP closure browser tests.
 *
 * The tests verify the static VitePress site loads, that the
 * new Prompt 34 pages are reachable, and that the key
 * sections are present in the rendered HTML.
 *
 * The tests are intentionally lightweight: they hit the
 * static site, not the live VitePress dev server, so they
 * can run against ``vitepress preview`` (port 4173) without
 * any HMR overhead.
 */

const PAGES = [
  { name: 'home', path: '/' },
  { name: 'retrieval', path: '/search/retrieval' },
  { name: 'eval', path: '/search/eval' },
  { name: 'context', path: '/search/context' },
  { name: 'rag-report', path: '/search/rag-report' },
]

for (const { name, path } of PAGES) {
  test(`${name} page loads (${path})`, async ({ page }) => {
    const response = await page.goto(path, { waitUntil: 'domcontentloaded' })
    expect(response, `no response for ${path}`).not.toBeNull()
    const status = response?.status() ?? 0
    expect(status, `${path} returned ${status}`).toBeLessThan(400)
    const heading = page.locator('h1').first()
    await expect(heading).toBeVisible()
  })
}

test('context page contains Context Pack, Chunks, and Sources sections', async ({ page }) => {
  await page.goto('/search/context', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('h1#context-pack')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Chunks' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Sources' })).toBeVisible()
})

test('RAG report page contains mock / no-LLM wording', async ({ page }) => {
  await page.goto('/search/rag-report', { waitUntil: 'domcontentloaded' })
  const body = await page.locator('main').innerText()
  // The page must declare the answer is mock / no-LLM.
  expect(body).toMatch(/mock\s*\/\s*no-?llm/i)
  // The page must show the eval check table.
  await expect(page.getByRole('heading', { name: 'Checks' })).toBeVisible()
})

test('no broken route for the new pages', async ({ page }) => {
  // The /search/context and /search/rag-report routes must
  // not 4xx. We assert a 2xx or 3xx response (VitePress
  // serves clean URLs without redirects, so we expect 200).
  for (const path of ['/search/context', '/search/rag-report']) {
    const response = await page.goto(path, { waitUntil: 'domcontentloaded' })
    const status = response?.status() ?? 0
    expect(status, `${path} returned ${status}`).toBeLessThan(400)
  }
})
