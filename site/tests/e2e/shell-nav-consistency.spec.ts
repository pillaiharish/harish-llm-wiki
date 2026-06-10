import { expect, Page, test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const SCREENSHOT_DIR = path.resolve(
  process.cwd(),
  '..',
  '.agent-sessions',
  'prompt45_shell_nav_consistency',
  'screenshots'
)

const VIEWPORTS = [
  { name: 'desktop-1440', width: 1440, height: 900 },
  { name: 'desktop-1280', width: 1280, height: 900 },
  { name: 'compact-1024', width: 1024, height: 768 },
]

const ROUTES = [
  { name: 'resources', path: '/resources/' },
  { name: 'chunks', path: '/chunks/' },
  { name: 'review', path: '/review/' },
  { name: 'graph-explore', path: '/graph/explore' },
  { name: 'graphify', path: '/graph/graphify' },
  { name: 'explorer', path: '/explorer/' },
  { name: 'graph-index', path: '/graph/' },
  { name: 'resource-relationships', path: '/graph/resource-relationships' },
]

function collectPageErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (error) => {
    errors.push(error.message)
  })
  return errors
}

async function captureScreenshot(page: Page, name: string) {
  if (process.env.SHELL_UX_SCREENSHOTS !== '1') return
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true })
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, `${name}.png`),
    fullPage: true,
  })
}

async function expectNoBodyOverflow(page: Page) {
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

async function expectNavInsideViewport(page: Page) {
  const metrics = await page.evaluate(() => {
    const measure = (selector: string) => {
      const el = document.querySelector(selector)
      if (!el) return null
      const rect = el.getBoundingClientRect()
      const style = getComputedStyle(el)
      return {
        display: style.display,
        width: rect.width,
        left: rect.left,
        right: rect.right,
      }
    }
    return {
      innerWidth: window.innerWidth,
      nav: measure('.VPNavBar'),
      content: measure('.VPNavBar .content'),
      contentBody: measure('.VPNavBar .content-body'),
      menu: measure('.VPNavBarMenu'),
      appearance: measure('.VPNavBarAppearance'),
      search: measure('.VPNavBarSearch'),
    }
  })

  for (const [name, rect] of Object.entries(metrics)) {
    if (name === 'innerWidth' || rect === null) continue
    const box = rect as { display: string; width: number; left: number; right: number }
    if (box.display === 'none' || box.width === 0) continue
    expect(box.left, `${name} starts before viewport`).toBeGreaterThanOrEqual(0)
    expect(box.right, `${name} ends past viewport ${box.right} > ${metrics.innerWidth}`).toBeLessThanOrEqual(
      metrics.innerWidth + 1
    )
  }
}

test('top navigation is grouped into primary links and dropdowns', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/', { waitUntil: 'domcontentloaded' })

  for (const label of ['Home', 'Learn', 'Resources', 'Graph', 'Explorer']) {
    await expect(page.getByRole('link', { name: label, exact: true })).toBeVisible()
  }

  for (const label of ['Knowledge', 'Quality', 'Data']) {
    await expect(page.getByText(label, { exact: true }).first()).toBeVisible()
  }
})

for (const viewport of VIEWPORTS) {
  test(`shell navigation stays inside viewport at ${viewport.name}`, async ({ page }) => {
    const errors = collectPageErrors(page)
    await page.setViewportSize({ width: viewport.width, height: viewport.height })

    for (const route of ROUTES) {
      const response = await page.goto(route.path, { waitUntil: 'domcontentloaded' })
      expect(response?.status() ?? 0, `${route.path} returned a bad response`).toBeLessThan(400)
      await expectNavInsideViewport(page)
      await expectNoBodyOverflow(page)
      await captureScreenshot(page, `${viewport.name}-${route.name}`)
    }

    expect(errors, `unexpected browser errors:\n${errors.join('\n')}`).toEqual([])
  })
}
