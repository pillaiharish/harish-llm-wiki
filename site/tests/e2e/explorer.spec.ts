import { test, expect, request } from '@playwright/test'

/**
 * /explorer/ browser tests (Prompt 36).
 *
 * These tests verify the static Explorer page:
 *   - loads without a VitePress / Vite side-effect warning
 *     (no raw <script> or <style> in the Markdown template)
 *   - contains the expected title and content
 *   - mounts the <SearchExplorer /> Vue component, which
 *     fetches /search/all.json and renders the search UI
 *   - search input is present and accepts text
 *   - error state is deterministic when the search index
 *     is missing
 *   - /search/all.json returns 200 (the runtime path the
 *     Vue component reads from)
 *   - no raw <script> or <style> tag text is visible on the
 *     rendered page
 *
 * The tests run against the VitePress dev server (port 5173)
 * configured in playwright.config.ts.
 */

test('/explorer/ page loads and contains the Explorer title', async ({ page }) => {
  const response = await page.goto('/explorer/', { waitUntil: 'domcontentloaded' })
  expect(response, 'no response for /explorer/').not.toBeNull()
  const status = response?.status() ?? 0
  expect(status, `/explorer/ returned ${status}`).toBeLessThan(400)
  await expect(
    page.getByRole('heading', { name: 'Explorer', level: 1 })
  ).toBeVisible()
})

test('/explorer/ mounts the <SearchExplorer /> Vue component', async ({ page }) => {
  await page.goto('/explorer/', { waitUntil: 'domcontentloaded' })
  // The component renders into a container with the legacy
  // #wiki-explorer id. We wait for the search input to appear,
  // which only happens once the Vue component has mounted and
  // hydrated.
  const search = page.locator('#explorer-q')
  await expect(search).toBeVisible({ timeout: 15_000 })
  // And the live stats panel flips out of 'loading' state.
  const liveStats = page.locator('#explorer-live-stats')
  await expect(liveStats).not.toHaveAttribute('data-state', 'loading', {
    timeout: 15_000,
  })
})

test('/explorer/ search input is present and accepts text', async ({ page }) => {
  await page.goto('/explorer/', { waitUntil: 'domcontentloaded' })
  const search = page.locator('#explorer-q')
  await expect(search).toBeVisible({ timeout: 15_000 })
  // Type a query and confirm the input value is reflected.
  await search.fill('Missing')
  expect(await search.inputValue()).toBe('Missing')
})

test('/explorer/ /search/all.json returns a healthy response', async () => {
  const ctx = await request.newContext({ baseURL: 'http://127.0.0.1:5173' })
  const response = await ctx.get('/search/all.json')
  expect(response.status(), `unexpected status: ${response.status()}`).toBeLessThan(400)
  const body = await response.json()
  expect(Array.isArray(body.items)).toBe(true)
  await ctx.dispose()
})

test('/explorer/ no raw <script> or <style> text is visible on the page', async ({ page }) => {
  await page.goto('/explorer/', { waitUntil: 'domcontentloaded' })
  // Wait for the Vue component to render so we capture the
  // post-hydration DOM (the SSR pass would not include any
  // client-only content).
  const search = page.locator('#explorer-q')
  await expect(search).toBeVisible({ timeout: 15_000 })
  const mainText = await page.locator('main').innerText()
  // The Vue component is the only script source. We must not
  // see a raw <script>fetch('...')</script> string in the
  // page text.
  expect(mainText).not.toMatch(/<script>fetch\(/i)
  // And no <style> tag in the rendered text either.
  expect(mainText).not.toMatch(/<style[\s>]/i)
  // The Markdown also no longer contains the legacy
  // ``const items = [...]`` JS array. The component is what
  // holds the items at runtime.
  expect(mainText).not.toMatch(/const items = \[/i)
})

test('/explorer/ error state is deterministic when the index is missing', async ({ page }) => {
  // Block the search index from loading so the component
  // surfaces its error fallback.
  await page.route('**/search/all.json', (route) => route.abort())
  await page.goto('/explorer/', { waitUntil: 'domcontentloaded' })
  // The live stats panel must flip to the error state with
  // the canonical fallback message.
  const liveStats = page.locator('#explorer-live-stats')
  await expect(liveStats).toHaveAttribute('data-state', 'error', {
    timeout: 15_000,
  })
  const lineText = await page.locator('#explorer-live-stats-line').innerText()
  expect(lineText).toMatch(/Could not load search index/i)
  expect(lineText).toMatch(/\/search\/all\.json/)
})

test('/explorer/ no VitePress side-effect warning appears', async ({ page }) => {
  // The dev server logs side-effect warnings to the browser
  // console. Capture every console message and assert none of
  // them mention "Tags with side effect".
  const warnings: string[] = []
  page.on('console', (msg) => {
    const text = msg.text()
    if (
      msg.type() === 'warning' ||
      msg.type() === 'error' ||
      text.toLowerCase().includes('tags with side effect')
    ) {
      warnings.push(`[${msg.type()}] ${text}`)
    }
  })
  await page.goto('/explorer/', { waitUntil: 'domcontentloaded' })
  // Wait for hydration to ensure the warning, if any, would
  // have fired by now.
  const search = page.locator('#explorer-q')
  await expect(search).toBeVisible({ timeout: 15_000 })
  // The exact error string from the original bug report must
  // not appear in the console.
  const sideEffect = warnings.filter((w) =>
    /tags with side effect/i.test(w)
  )
  expect(sideEffect, `unexpected side-effect warnings: ${sideEffect.join('\n')}`).toEqual([])
})
