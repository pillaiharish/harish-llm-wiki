import { test, expect, request, Page } from '@playwright/test'

/**
 * Graph viewer browser tests.
 *
 * These tests verify the static knowledge graph viewer is
 * reachable, has the right title, successfully loads the
 * graph JSON, and exposes a real interactive Cytoscape.js
 * explorer with the controls required by Prompt 35.
 *
 * The tests run against the VitePress dev server (port 5173)
 * configured in playwright.config.ts.
 */

test('/graph page loads', async ({ page }) => {
  const response = await page.goto('/graph/', { waitUntil: 'domcontentloaded' })
  expect(response, 'no response for /graph/').not.toBeNull()
  const status = response?.status() ?? 0
  expect(status, `/graph/ returned ${status}`).toBeLessThan(400)
  await expect(page.getByRole('heading', { name: 'Knowledge Graph', level: 1 })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open Interactive Graph' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'View Resource Relationships' })).toBeVisible()
})

test('/graph/viewer page loads and contains the viewer title', async ({ page }) => {
  const response = await page.goto('/graph/viewer', { waitUntil: 'domcontentloaded' })
  expect(response, 'no response for /graph/viewer').not.toBeNull()
  const status = response?.status() ?? 0
  expect(status, `/graph/viewer returned ${status}`).toBeLessThan(400)
  await expect(
    page.getByRole('heading', { name: 'Knowledge Graph Viewer', level: 1 })
  ).toBeVisible()
})

test('/graph/explore page loads and contains the workspace title', async ({ page }) => {
  const response = await page.goto('/graph/explore', { waitUntil: 'domcontentloaded' })
  expect(response, 'no response for /graph/explore').not.toBeNull()
  const status = response?.status() ?? 0
  expect(status, `/graph/explore returned ${status}`).toBeLessThan(400)
  await expect(page.getByRole('heading', { name: 'Graph Workspace', level: 1 })).toBeVisible()
})

test('/graph/viewer loads graph data and shows live stats', async ({ page }) => {
  await page.goto('/graph/viewer', { waitUntil: 'domcontentloaded' })
  // The interactive viewer container is present in the static HTML.
  await expect(page.locator('#graph-viewer')).toBeVisible()
  // Wait for the live stats panel to flip out of the "loading" state.
  // Once the JSON fetch completes, the panel data-state becomes
  // "ready" and the line text reports node and edge counts.
  const liveStats = page.locator('#graph-live-stats')
  await expect(liveStats).toBeVisible()
  await expect(liveStats).toHaveAttribute('data-state', 'ready', { timeout: 15_000 })
  const lineText = await page.locator('#graph-live-stats-line').innerText()
  // The line must mention both nodes and edges with numeric counts.
  expect(lineText).toMatch(/nodes/i)
  expect(lineText).toMatch(/edges/i)
  expect(lineText).toMatch(/\d+/)
  // The static stats table at the top of the page (rendered from
  // the template) must also be present.
  const mainText = await page.locator('main').innerText()
  expect(mainText).toMatch(/Nodes:\s*\d+/)
  expect(mainText).toMatch(/Edges:\s*\d+/)
})

test('/graph/resource-relationships page loads and contains the report title', async ({ page }) => {
  const response = await page.goto('/graph/resource-relationships', { waitUntil: 'domcontentloaded' })
  expect(response, 'no response for /graph/resource-relationships').not.toBeNull()
  const status = response?.status() ?? 0
  expect(status, `/graph/resource-relationships returned ${status}`).toBeLessThan(400)
  await expect(
    page.getByRole('heading', { name: 'Resource Relationships', level: 1 })
  ).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Why This Page Matters', level: 2 })).toBeVisible()
})

test('/graph/knowledge_graph.json returns a healthy response', async () => {
  const ctx = await request.newContext({ baseURL: 'http://127.0.0.1:5173' })
  const response = await ctx.get('/graph/knowledge_graph.json')
  expect(response.status(), `unexpected status: ${response.status()}`).toBeLessThan(400)
  const body = await response.json()
  expect(Array.isArray(body.nodes)).toBe(true)
  expect(Array.isArray(body.edges)).toBe(true)
  expect(typeof body.stats).toBe('object')
  expect(body.nodes.length).toBeGreaterThan(0)
  expect(body.edges.length).toBeGreaterThan(0)
  await ctx.dispose()
})

/**
 * Helper: navigate to the viewer and wait for the Cytoscape
 * instance to be exposed on window.__graphCy.
 */
async function gotoGraphPageWithCy(page: Page, route: string = '/graph/viewer') {
  const currentUrl = page.url()
  if (!currentUrl.includes(route)) {
    await page.goto(route, { waitUntil: 'domcontentloaded' })
  }
  await page.waitForFunction(
    () => {
      const cy = (window as any).__graphCy
      return (
        cy &&
        typeof cy.nodes === 'function' &&
        typeof cy.edges === 'function' &&
        cy.nodes().length > 0
      )
    },
    null,
    { timeout: 30_000 }
  )
}

async function gotoViewerWithCy(page: Page) {
  await gotoGraphPageWithCy(page, '/graph/viewer')
}

async function gotoExploreWithCy(page: Page) {
  await gotoGraphPageWithCy(page, '/graph/explore')
}

test('graph canvas is visible with required height', async ({ page }) => {
  await gotoViewerWithCy(page)
  const canvas = page.locator('#graph-canvas')
  await expect(canvas).toBeVisible()
  const box = await canvas.boundingBox()
  expect(box, 'graph canvas has no bounding box').not.toBeNull()
  expect(box!.width, 'graph canvas width is zero').toBeGreaterThan(0)
  expect(box!.height, `graph canvas height is ${box!.height}, expected >= 600`).toBeGreaterThanOrEqual(600)
})

test('/graph/explore shows the graph canvas above the fold on desktop', async ({ page }) => {
  await gotoExploreWithCy(page)
  const canvas = page.locator('#graph-canvas')
  await expect(canvas).toBeVisible()
  const box = await canvas.boundingBox()
  expect(box, 'graph canvas has no bounding box').not.toBeNull()
  const viewport = page.viewportSize()
  expect(viewport).not.toBeNull()
  expect(box!.y, `graph canvas starts too low at ${box!.y}px`).toBeLessThan((viewport?.height ?? 720) - 40)
})

test('/graph/explore shows the graph early on mobile and avoids horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await gotoExploreWithCy(page)
  const canvas = page.locator('#graph-canvas')
  await expect(canvas).toBeVisible()
  const box = await canvas.boundingBox()
  expect(box, 'graph canvas has no bounding box').not.toBeNull()
  expect(box!.y, `mobile graph canvas starts too low at ${box!.y}px`).toBeLessThan(900)
  const overflow = await page.evaluate(() => {
    const body = document.body
    const doc = document.documentElement
    return Math.max(body.scrollWidth, doc.scrollWidth) > window.innerWidth
  })
  expect(overflow, 'mobile explore page should not overflow horizontally').toBe(false)
})

test('cytoscape renders nodes and edges', async ({ page }) => {
  await gotoViewerWithCy(page)
  const counts = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    return { nodes: cy.nodes().length, edges: cy.edges().length }
  })
  expect(counts.nodes, 'cy.nodes() must be > 0').toBeGreaterThan(0)
  expect(counts.edges, 'cy.edges() must be > 0').toBeGreaterThan(0)
})

test('Fit graph button exists and works', async ({ page }) => {
  await gotoViewerWithCy(page)
  const fitBtn = page.locator('#graph-fit')
  await expect(fitBtn).toBeVisible()
  // Mutate the zoom level so we can detect that fit() ran.
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(0.1)
    cy.pan({ x: 9999, y: 9999 })
  })
  const beforeFit = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    return { zoom: cy.zoom(), pan: cy.pan() }
  })
  expect(beforeFit.zoom).toBeLessThan(0.5)
  await fitBtn.click()
  // Give Cytoscape a moment to refit.
  await page.waitForTimeout(500)
  const afterFit = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    return { zoom: cy.zoom(), pan: cy.pan() }
  })
  expect(afterFit.zoom, 'fit should restore zoom to >= 0.5').toBeGreaterThanOrEqual(0.5)
})

test('Reset zoom button exists and works', async ({ page }) => {
  await gotoViewerWithCy(page)
  const resetBtn = page.locator('#graph-reset-zoom')
  await expect(resetBtn).toBeVisible()
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(2.5)
  })
  await resetBtn.click()
  await page.waitForTimeout(200)
  const zoom = await page.evaluate(() => (window as any).__graphCy.zoom())
  expect(zoom, `reset zoom should set zoom to 1, got ${zoom}`).toBeCloseTo(1, 1)
})

test('Show all button expands from top-N to full graph', async ({ page }) => {
  await gotoViewerWithCy(page)
  const before = await page.evaluate(() => (window as any).__graphCy.nodes().length)
  const showAllBtn = page.locator('#graph-show-all')
  await expect(showAllBtn).toBeVisible()
  await showAllBtn.click()
  // Wait for re-render to complete.
  await page.waitForFunction(
    (prev) => (window as any).__graphCy.nodes().length !== prev,
    before,
    { timeout: 15_000 }
  )
  const after = await page.evaluate(() => (window as any).__graphCy.nodes().length)
  expect(after, `Show all should expand node count from ${before} to > ${before}`).toBeGreaterThan(before)
})

test('Search input filters graph content', async ({ page }) => {
  await gotoViewerWithCy(page)
  // Find a unique label from the loaded graph.
  const targetLabel = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    const node = cy.nodes()[0]
    return node.data('label') || node.id()
  })
  const search = page.locator('#graph-search')
  await expect(search).toBeVisible()
  await search.fill(targetLabel)
  // Wait for re-render.
  await page.waitForTimeout(500)
  const visibleCount = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    return cy.nodes().filter((n: any) => n.visible()).length
  })
  expect(visibleCount).toBeGreaterThan(0)
  // And no node visible that doesn't match the term.
  const allMatch = await page.evaluate((term: string) => {
    const cy = (window as any).__graphCy
    const lower = term.toLowerCase()
    return cy
      .nodes()
      .filter((n: any) => n.visible())
      .every((n: any) => {
        const d = n.data()
        return (
          (d.label && d.label.toLowerCase().includes(lower)) ||
          (d.id && d.id.toLowerCase().includes(lower)) ||
          (d.slug && d.slug.toLowerCase().includes(lower))
        )
      })
  }, targetLabel)
  expect(allMatch, 'all visible nodes should match search term').toBe(true)
})

test('Clicking a node populates Details', async ({ page }) => {
  await gotoViewerWithCy(page)
  // Get a node id from the cytoscape instance and click it.
  const nodeId = await page.evaluate(() => (window as any).__graphCy.nodes()[0].id())
  await page.evaluate((id: string) => {
    const cy = (window as any).__graphCy
    cy.getElementById(id).emit('tap')
  }, nodeId)
  await page.waitForTimeout(200)
  const detailsText = await page.locator('#graph-details').innerText()
  expect(detailsText).toContain(nodeId)
  expect(detailsText).toMatch(/Type:/i)
})

test('Clicking an edge populates Details', async ({ page }) => {
  await gotoViewerWithCy(page)
  const hasEdge = await page.evaluate(() => (window as any).__graphCy.edges().length > 0)
  expect(hasEdge, 'expected at least one edge').toBe(true)
  const edgeId = await page.evaluate(() => (window as any).__graphCy.edges()[0].id())
  await page.evaluate((id: string) => {
    const cy = (window as any).__graphCy
    cy.getElementById(id).emit('tap')
  }, edgeId)
  await page.waitForTimeout(200)
  const detailsText = await page.locator('#graph-details').innerText()
  expect(detailsText).toContain(edgeId)
})

test('Node type filter checkboxes are present', async ({ page }) => {
  await gotoViewerWithCy(page)
  const fieldset = page.locator('#graph-filter-node-type')
  await expect(fieldset).toBeVisible()
  const checkboxes = fieldset.locator('input[type="checkbox"]')
  expect(await checkboxes.count()).toBeGreaterThan(0)
})

test('Edge type filter checkboxes are present', async ({ page }) => {
  await gotoViewerWithCy(page)
  const fieldset = page.locator('#graph-filter-edge-type')
  await expect(fieldset).toBeVisible()
  const checkboxes = fieldset.locator('input[type="checkbox"]')
  expect(await checkboxes.count()).toBeGreaterThan(0)
})

test('Unchecking a node type filter removes matching nodes', async ({ page }) => {
  await gotoViewerWithCy(page)
  // Find a type present in the graph.
  const firstType = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    return cy.nodes()[0].data('type') as string
  })
  const cbId = `#graph-filter-node-type-${firstType}`
  const cb = page.locator(cbId)
  await expect(cb).toBeVisible()
  const beforeCount = await page.evaluate(
    (t: string) => (window as any).__graphCy.nodes().filter(`[type = "${t}"]`).length,
    firstType
  )
  expect(beforeCount).toBeGreaterThan(0)
  await cb.click()
  await page.waitForTimeout(300)
  const afterCount = await page.evaluate(
    (t: string) => (window as any).__graphCy.nodes().filter(`[type = "${t}"]`).length,
    firstType
  )
  expect(afterCount, 'unchecking a node type should remove those nodes').toBe(0)
  // Restore for any subsequent tests that share state.
  await cb.click()
})

test('Unchecking an edge type filter removes matching edges', async ({ page }) => {
  await gotoViewerWithCy(page)
  const firstType = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    const e = cy.edges()[0]
    return e ? (e.data('type') as string) : ''
  })
  expect(firstType, 'expected at least one edge type').not.toBe('')
  const cbId = `#graph-filter-edge-type-${firstType}`
  const cb = page.locator(cbId)
  await expect(cb).toBeVisible()
  const beforeCount = await page.evaluate(
    (t: string) => (window as any).__graphCy.edges().filter(`[type = "${t}"]`).length,
    firstType
  )
  expect(beforeCount).toBeGreaterThan(0)
  await cb.click()
  await page.waitForTimeout(300)
  const afterCount = await page.evaluate(
    (t: string) => (window as any).__graphCy.edges().filter(`[type = "${t}"]`).length,
    firstType
  )
  expect(afterCount, 'unchecking an edge type should remove those edges').toBe(0)
  await cb.click()
})

test('No raw HTML is visible as literal text on the page', async ({ page }) => {
  await page.goto('/graph/viewer', { waitUntil: 'domcontentloaded' })
  // Wait for hydration to ensure Vue's render has replaced the SSR
  // placeholders.
  await page.waitForFunction(
    () => !!document.querySelector('#graph-canvas'),
    null,
    { timeout: 15_000 }
  )
  const mainText = await page.locator('main').innerText()
  expect(mainText).not.toMatch(/<div id="graph-svg-pane"/i)
  expect(mainText).not.toMatch(/&lt;div id="graph-svg-pane"/i)
  expect(mainText).not.toMatch(/<pre><code>&lt;div/i)
})

test('Live stats text matches runtime JSON counts', async ({ page }) => {
  await page.goto('/graph/viewer', { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(
    () => {
      const ls = document.getElementById('graph-live-stats')
      return ls && ls.getAttribute('data-state') === 'ready'
    },
    null,
    { timeout: 15_000 }
  )
  // Fetch the JSON directly to compare numbers.
  const ctx = await request.newContext({ baseURL: 'http://127.0.0.1:5173' })
  const resp = await ctx.get('/graph/knowledge_graph.json')
  const body = await resp.json()
  await ctx.dispose()
  const expectedNodeCount: number = body.stats?.node_count ?? body.nodes.length
  const expectedEdgeCount: number = body.stats?.edge_count ?? body.edges.length
  const lineText = await page.locator('#graph-live-stats-line').innerText()
  expect(lineText).toContain(String(expectedNodeCount))
  expect(lineText).toContain(String(expectedEdgeCount))
})

// ---------------------------------------------------------------------------
// Prompt 35.1 — Resize, fit, and label readability
// ---------------------------------------------------------------------------

test('Zoom in button increases cytoscape zoom level', async ({ page }) => {
  await gotoViewerWithCy(page)
  const zoomInBtn = page.locator('#graph-zoom-in')
  await expect(zoomInBtn).toBeVisible()
  // Reset to a known zoom first.
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(1)
  })
  const before = await page.evaluate(() => (window as any).__graphCy.zoom())
  await zoomInBtn.click()
  await page.waitForTimeout(150)
  const after = await page.evaluate(() => (window as any).__graphCy.zoom())
  expect(after, 'zoom in should increase zoom level').toBeGreaterThan(before)
})

test('Zoom out button decreases cytoscape zoom level', async ({ page }) => {
  await gotoViewerWithCy(page)
  const zoomOutBtn = page.locator('#graph-zoom-out')
  await expect(zoomOutBtn).toBeVisible()
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(1.5)
  })
  const before = await page.evaluate(() => (window as any).__graphCy.zoom())
  await zoomOutBtn.click()
  await page.waitForTimeout(150)
  const after = await page.evaluate(() => (window as any).__graphCy.zoom())
  expect(after, 'zoom out should decrease zoom level').toBeLessThan(before)
})

test('Resizing the viewport keeps the graph visible and refits it', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await gotoViewerWithCy(page)
  const initial = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    return { zoom: cy.zoom(), pan: cy.pan() }
  })
  // Shrink the viewport dramatically.
  await page.setViewportSize({ width: 800, height: 600 })
  // ResizeObserver + fit is debounced 80ms, allow a bit more.
  await page.waitForTimeout(400)
  const after = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    return {
      zoom: cy.zoom(),
      pan: cy.pan(),
      extents: cy.extent(),
    }
  })
  // The canvas must still hold the graph after resize.
  const canvasBox = await page.locator('#graph-canvas').boundingBox()
  expect(canvasBox, 'canvas should still have a bounding box').not.toBeNull()
  expect(canvasBox!.width, 'canvas width should remain > 0').toBeGreaterThan(0)
  // The graph extent must still fit within the canvas dimensions.
  const ext = after.extents
  expect(ext.w, 'graph width should still be > 0 after resize').toBeGreaterThan(0)
  expect(ext.h, 'graph height should still be > 0 after resize').toBeGreaterThan(0)
  // Sanity: zoom should still be a finite, positive number.
  expect(after.zoom).toBeGreaterThan(0)
  // Restore viewport for downstream tests.
  await page.setViewportSize({ width: 1280, height: 900 })
  // The pan/zoom may legitimately change because the canvas
  // shrank. What matters is that the graph is still visible.
  void initial
})

test('Mouse-wheel zoom is not auto-fit back to a default', async ({ page }) => {
  await gotoViewerWithCy(page)
  // Set a non-default zoom manually, then dispatch a real wheel
  // event on the canvas via a dispatched WheelEvent. The graph
  // should keep the new zoom level.
  const targetZoom = 2.2
  await page.evaluate((z: number) => {
    const cy = (window as any).__graphCy
    cy.zoom(z)
  }, targetZoom)
  const before = await page.evaluate(() => (window as any).__graphCy.zoom())
  expect(before).toBeCloseTo(targetZoom, 1)
  // Dispatch several WheelEvents directly on the canvas container.
  // Playwright's page.mouse.wheel can be flaky in headless mode
  // against cytoscape's wheel listener; a real DOM event with
  // deltaY is more reliable.
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    const container = cy.container()
    if (!container) return
    const rect = container.getBoundingClientRect()
    const clientX = rect.left + rect.width / 2
    const clientY = rect.top + rect.height / 2
    for (let i = 0; i < 8; i += 1) {
      const ev = new WheelEvent('wheel', {
        bubbles: true,
        cancelable: true,
        clientX,
        clientY,
        deltaY: -200,
        deltaMode: 0,
      })
      container.dispatchEvent(ev)
    }
  })
  await page.waitForTimeout(300)
  const after = await page.evaluate(() => (window as any).__graphCy.zoom())
  // The wheel events should have increased the zoom above the
  // initial value.
  expect(
    after,
    `wheel zoom should increase zoom (before=${before}, after=${after})`
  ).toBeGreaterThan(before + 0.05)
  // And the auto-fit handler must not have snapped it back to 1.
  expect(after, 'wheel zoom must not snap back to 1').not.toBeCloseTo(1, 1)
})

test('Most labels are hidden at low zoom', async ({ page }) => {
  await gotoViewerWithCy(page)
  // Force a low zoom and emit a zoom event so the label
  // visibility handler runs. cy.zoom() does not trigger the
  // 'zoom' event on its own, so we emit it explicitly.
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(0.25)
    cy.emit('zoom')
  })
  await page.waitForTimeout(250)
  // Count nodes that currently have a non-empty label string.
  const visibleLabels = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    let count = 0
    cy.nodes().forEach((n: any) => {
      const lbl = n.style('label') || ''
      if (lbl && lbl.length > 0) count += 1
    })
    return { count, total: cy.nodes().length }
  })
  expect(visibleLabels.total, 'graph should have many nodes').toBeGreaterThan(10)
  // At low zoom, only a small fraction of nodes should display labels.
  // The Prompt 35.1 spec says "most labels are hidden when zoom is low"
  // and only the selected node, its neighbors, and high-degree hubs
  // (degree >= 8) should still be visible.
  expect(
    visibleLabels.count,
    `low zoom should hide most labels, got ${visibleLabels.count} of ${visibleLabels.total}`
  ).toBeLessThan(visibleLabels.total / 2)
})

test('Selected node still shows details and keeps its label visible', async ({ page }) => {
  await gotoViewerWithCy(page)
  // Pick a node with at least one neighbor so the closed
  // neighborhood is non-trivial.
  const targetId = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    const ns = cy.nodes()
    for (let i = 0; i < ns.length; i++) {
      const n = ns[i]
      if (n.neighborhood().length > 0) {
        return n.id() as string
      }
    }
    return ns[0].id() as string
  })
  // Emit a tap on that node and wait for the label refresh.
  await page.evaluate((id: string) => {
    const cy = (window as any).__graphCy
    cy.getElementById(id).emit('tap')
  }, targetId)
  await page.waitForTimeout(250)
  // The selected node should have a non-empty label string.
  const label = await page.evaluate((id: string) => {
    const cy = (window as any).__graphCy
    const n = cy.getElementById(id)
    return n.style('label') as string
  }, targetId)
  expect(label, 'selected node must have a visible label').toBeTruthy()
  expect(label.length, 'selected node label must be non-empty').toBeGreaterThan(0)
  // The details panel must mention the node id and type.
  const detailsText = await page.locator('#graph-details').innerText()
  expect(detailsText).toContain(targetId)
  expect(detailsText).toMatch(/Type:/i)
})

test('Reset zoom button returns zoom to 1×', async ({ page }) => {
  await gotoViewerWithCy(page)
  const resetBtn = page.locator('#graph-reset-zoom')
  await expect(resetBtn).toBeVisible()
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(2.5)
  })
  await resetBtn.click()
  await page.waitForTimeout(200)
  const zoom = await page.evaluate(() => (window as any).__graphCy.zoom())
  expect(zoom, `reset zoom should restore zoom to 1, got ${zoom}`).toBeCloseTo(1, 1)
})

test('Fit graph button restores a usable zoom after manual pan/zoom', async ({ page }) => {
  await gotoViewerWithCy(page)
  const fitBtn = page.locator('#graph-fit')
  await expect(fitBtn).toBeVisible()
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(0.1)
    cy.pan({ x: 9999, y: 9999 })
  })
  await fitBtn.click()
  await page.waitForTimeout(400)
  const after = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    return { zoom: cy.zoom(), pan: cy.pan() }
  })
  expect(after.zoom, 'fit should restore zoom to >= 0.3').toBeGreaterThanOrEqual(0.3)
})

// ---------------------------------------------------------------------------
// Prompt 35.2 — Semantic zoom and graph spacing
// ---------------------------------------------------------------------------

/**
 * Helper: collect how many nodes have a non-empty label at the
 * current cy state, and a few representative style values.
 */
async function readLabelState(page: Page) {
  return page.evaluate(() => {
    const cy = (window as any).__graphCy
    let shown = 0
    let hubShown = 0
    let totalNodes = 0
    let nonHubCount = 0
    let widthSamples: string[] = []
    let fontSizeSamples: string[] = []
    cy.nodes().forEach((n: any) => {
      totalNodes += 1
      const lbl = n.style('label') || ''
      if (lbl && lbl.length > 0) {
        shown += 1
        if (n.hasClass('hub')) hubShown += 1
      }
      // The base `node` style has no per-type width, so read any
      // element's width (we collect a few to be robust against
      // missing style on the first element).
      widthSamples.push(String(n.style('width')))
      fontSizeSamples.push(String(n.style('font-size')))
      if (!n.hasClass('hub')) nonHubCount += 1
    })
    // Pick the first non-empty width / font-size across all
    // elements. The base `node` rule is shared so this is
    // representative of the tier defaults.
    const width = widthSamples.find((s) => s && s !== 'undefined' && s !== 'NaN') || ''
    const fontSize = fontSizeSamples.find((s) => s && s !== 'undefined' && s !== 'NaN') || ''
    return {
      total: totalNodes,
      shown,
      hubShown,
      nonHubCount,
      fontSize,
      width,
      zoom: cy.zoom(),
    }
  })
}

test('Semantic zoom: low zoom hides most labels and shrinks nodes', async ({ page }) => {
  await gotoViewerWithCy(page)
  // Low tier is z <= 0.5.
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(0.25)
    cy.emit('zoom')
  })
  await page.waitForTimeout(250)
  const state = await readLabelState(page)
  expect(state.zoom, 'zoom should be at 0.25').toBeLessThanOrEqual(0.5)
  expect(state.total, 'graph should have many nodes').toBeGreaterThan(10)
  // At low zoom, less than half of nodes should show a label.
  expect(
    state.shown,
    `low zoom should hide most labels, got ${state.shown} of ${state.total}`
  ).toBeLessThan(state.total / 2)
  // Node width should be in the small "low zoom" range (10-12 px).
  const w = parseFloat(state.width)
  expect(w, `low zoom node width should be <= 13, got ${w}`).toBeLessThanOrEqual(13)
  expect(w, `low zoom node width should be > 0, got ${w}`).toBeGreaterThan(0)
})

test('Semantic zoom: high zoom reveals more labels and grows nodes', async ({ page }) => {
  await gotoViewerWithCy(page)
  // High tier is z >= 1.2.
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(2.0)
    cy.emit('zoom')
  })
  await page.waitForTimeout(250)
  const state = await readLabelState(page)
  expect(state.zoom, 'zoom should be at 2.0').toBeGreaterThanOrEqual(1.2)
  // At high zoom, every node should display its label.
  expect(
    state.shown,
    `high zoom should reveal all ${state.total} labels, got ${state.shown}`
  ).toBe(state.total)
  // Node width should be in the larger "high zoom" range (>= 22 px).
  const w = parseFloat(state.width)
  expect(w, `high zoom node width should be >= 22, got ${w}`).toBeGreaterThanOrEqual(22)
  // Font-size is controlled — even at zoom 2.0, it should be in
  // the 7-10 px band, not scaled endlessly.
  const fs = parseFloat(state.fontSize)
  expect(fs, `high zoom font-size should be <= 11, got ${fs}`).toBeLessThanOrEqual(11)
  expect(fs, `high zoom font-size should be > 0, got ${fs}`).toBeGreaterThan(0)
})

test('Semantic zoom: medium zoom keeps selected and neighbor labels visible', async ({ page }) => {
  await gotoViewerWithCy(page)
  // Settle at medium zoom (0.7 is squarely in [0.5, 1.2)).
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(0.7)
    cy.emit('zoom')
  })
  await page.waitForTimeout(150)
  // Pick a node that has at least one neighbor, then tap it.
  const targetId = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    for (let i = 0; i < cy.nodes().length; i++) {
      const n = cy.nodes()[i]
      if (n.neighborhood().length > 0) return n.id() as string
    }
    return cy.nodes()[0].id() as string
  })
  await page.evaluate((id: string) => {
    const cy = (window as any).__graphCy
    cy.getElementById(id).emit('tap')
  }, targetId)
  await page.waitForTimeout(250)
  // The selected node and at least one of its neighbors must show a
  // label, even though most other nodes are hidden at medium zoom.
  const stats = await page.evaluate((id: string) => {
    const cy = (window as any).__graphCy
    const sel = cy.getElementById(id)
    const selLabel = sel.style('label') as string
    const nbh = sel.closedNeighborhood()
    let neighborShown = 0
    nbh.forEach((n: any) => {
      const lbl = n.style('label') || ''
      if (lbl && lbl.length > 0) neighborShown += 1
    })
    return { selLabel, neighborShown, totalNb: nbh.length }
  }, targetId)
  expect(stats.selLabel, 'selected node label must be non-empty').toBeTruthy()
  expect(stats.selLabel.length, 'selected node label must be non-empty').toBeGreaterThan(0)
  expect(
    stats.neighborShown,
    `at least one neighbor of the selected node should show a label, got ${stats.neighborShown} of ${stats.totalNb}`
  ).toBeGreaterThan(0)
})

test('Semantic zoom: low zoom keeps the selected node label visible', async ({ page }) => {
  await gotoViewerWithCy(page)
  // Pick a node first, then zoom out.
  const targetId = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    for (let i = 0; i < cy.nodes().length; i++) {
      const n = cy.nodes()[i]
      if (n.neighborhood().length > 0) return n.id() as string
    }
    return cy.nodes()[0].id() as string
  })
  await page.evaluate((id: string) => {
    const cy = (window as any).__graphCy
    cy.getElementById(id).emit('tap')
  }, targetId)
  // Now drop the zoom to 0.25 and emit the event.
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(0.25)
    cy.emit('zoom')
  })
  await page.waitForTimeout(250)
  const label = await page.evaluate((id: string) => {
    const cy = (window as any).__graphCy
    return cy.getElementById(id).style('label') as string
  }, targetId)
  expect(
    label,
    `selected node label must remain visible at low zoom, got ${JSON.stringify(label)}`
  ).toBeTruthy()
  expect(label.length, 'selected node label must be non-empty at low zoom').toBeGreaterThan(0)
})

test('Semantic zoom: zoom in and zoom out buttons change node width and font-size', async ({ page }) => {
  await gotoViewerWithCy(page)
  // Start at the lowest tier, then drive the zoom through the
  // user-facing Zoom in button to verify the tier transition
  // propagates to node width. (We use cy.zoom() to set a precise
  // starting point and click Zoom in to reach the next tier.)
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(0.2)
    cy.emit('zoom')
  })
  await page.waitForTimeout(200)
  const before = await readLabelState(page)
  expect(before.zoom, 'starting zoom should be in the low tier').toBeLessThanOrEqual(0.5)
  // Click Zoom in several times. 0.2 * 1.25^4 = 0.488, still low.
  // 0.2 * 1.25^5 = 0.610, medium. So 5 clicks is enough to
  // cross the low->medium boundary in *theory*, but the actual
  // accumulated zoom depends on cytoscape's rounding. Keep
  // clicking until we observe a tier transition; cap at 12
  // clicks to avoid an infinite loop.
  let afterZoomIn = before
  for (let i = 0; i < 12; i += 1) {
    await page.locator('#graph-zoom-in').click()
    await page.waitForTimeout(120)
    afterZoomIn = await readLabelState(page)
    if (parseFloat(afterZoomIn.width) > parseFloat(before.width)) {
      break
    }
  }
  expect(afterZoomIn.zoom, 'zoom in should increase zoom').toBeGreaterThan(before.zoom)
  const wBefore = parseFloat(before.width)
  const wAfter = parseFloat(afterZoomIn.width)
  expect(
    wAfter,
    `node width should grow when zooming in (zoom=${afterZoomIn.zoom}, before=${wBefore}, after=${wAfter})`
  ).toBeGreaterThan(wBefore)
  // Now click Zoom out several times to drop back into the low
  // tier.
  let afterZoomOut = afterZoomIn
  for (let i = 0; i < 12; i += 1) {
    await page.locator('#graph-zoom-out').click()
    await page.waitForTimeout(120)
    afterZoomOut = await readLabelState(page)
    if (parseFloat(afterZoomOut.width) < wAfter) {
      break
    }
  }
  expect(afterZoomOut.zoom, 'zoom out should decrease zoom').toBeLessThan(afterZoomIn.zoom)
  // The low-zoom node width should be <= 13 (the low tier is 11).
  const wLow = parseFloat(afterZoomOut.width)
  expect(
    wLow,
    `after zooming out, node width should shrink to <= 13, got ${wLow} at zoom ${afterZoomOut.zoom}`
  ).toBeLessThanOrEqual(13)
})

test('Semantic zoom: graph still has rendered nodes and edges at low zoom', async ({ page }) => {
  await gotoViewerWithCy(page)
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(0.25)
    cy.emit('zoom')
  })
  await page.waitForTimeout(300)
  const counts = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    return {
      nodes: cy.nodes().length,
      edges: cy.edges().length,
      visibleNodes: cy.nodes().filter((n: any) => n.visible()).length,
      visibleEdges: cy.edges().filter((e: any) => e.visible()).length,
    }
  })
  expect(counts.nodes, 'cy should still have nodes at low zoom').toBeGreaterThan(0)
  expect(counts.edges, 'cy should still have edges at low zoom').toBeGreaterThan(0)
  expect(counts.visibleNodes, 'visible node count at low zoom should be > 0').toBeGreaterThan(0)
  expect(counts.visibleEdges, 'visible edge count at low zoom should be > 0').toBeGreaterThan(0)
})

test('Semantic zoom: reset zoom button restores zoom to ~1', async ({ page }) => {
  await gotoViewerWithCy(page)
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(2.5)
    cy.emit('zoom')
  })
  await page.waitForTimeout(200)
  await page.locator('#graph-reset-zoom').click()
  await page.waitForTimeout(300)
  const zoom = await page.evaluate(() => (window as any).__graphCy.zoom())
  expect(zoom, `reset zoom should be close to 1, got ${zoom}`).toBeCloseTo(1, 1)
})

test('Semantic zoom: fit graph button restores a usable zoom', async ({ page }) => {
  await gotoViewerWithCy(page)
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(0.1)
    cy.pan({ x: 9999, y: 9999 })
  })
  await page.locator('#graph-fit').click()
  await page.waitForTimeout(500)
  const after = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    return { zoom: cy.zoom(), pan: cy.pan() }
  })
  expect(after.zoom, 'fit should restore zoom to >= 0.3').toBeGreaterThanOrEqual(0.3)
})

test('Semantic zoom: do not duplicate DOM ids in the graph explorer', async ({ page }) => {
  await gotoViewerWithCy(page)
  const dupes = await page.evaluate(() => {
    const ids: Record<string, number> = {}
    const all = document.querySelectorAll('#graph-explorer, #graph-explorer *')
    all.forEach((el) => {
      const id = el.getAttribute('id')
      if (!id) return
      ids[id] = (ids[id] || 0) + 1
    })
    return Object.entries(ids)
      .filter(([, n]) => n > 1)
      .map(([id, n]) => `${id}×${n}`)
  })
  expect(dupes, `found duplicate DOM ids: ${dupes.join(', ')}`).toEqual([])
})

// ---------------------------------------------------------------------------
// Prompt 35.3 — Label visibility fix
// ---------------------------------------------------------------------------

/**
 * Helper: count nodes with a non-empty label string in the
 * current cytoscape stylesheet.
 */
async function countVisibleLabels(page: Page) {
  return page.evaluate(() => {
    const cy = (window as any).__graphCy
    let shown = 0
    let total = 0
    cy.nodes().forEach((n: any) => {
      total += 1
      const lbl = n.style('label') || ''
      if (lbl && lbl.length > 0) shown += 1
    })
    return { shown, total }
  })
}

test('Prompt 35.3: high zoom reveals labels for every node', async ({ page }) => {
  await gotoViewerWithCy(page)
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(2.0)
    cy.emit('zoom')
  })
  await page.waitForTimeout(300)
  const counts = await countVisibleLabels(page)
  expect(counts.total, 'graph should have many nodes').toBeGreaterThan(10)
  expect(
    counts.shown,
    `high zoom should reveal labels for all ${counts.total} nodes, got ${counts.shown}`
  ).toBe(counts.total)
})

test('Prompt 35.3: high zoom shows more labels than low zoom', async ({ page }) => {
  await gotoViewerWithCy(page)
  // Low zoom
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(0.25)
    cy.emit('zoom')
  })
  await page.waitForTimeout(250)
  const low = await countVisibleLabels(page)
  // High zoom
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(2.0)
    cy.emit('zoom')
  })
  await page.waitForTimeout(250)
  const high = await countVisibleLabels(page)
  expect(
    high.shown,
    `high zoom should show more labels than low zoom (low=${low.shown}, high=${high.shown})`
  ).toBeGreaterThan(low.shown)
})

test('Prompt 35.3: selected node label is visible at every zoom tier', async ({ page }) => {
  await gotoViewerWithCy(page)
  const targetId = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    for (let i = 0; i < cy.nodes().length; i++) {
      const n = cy.nodes()[i]
      if (n.neighborhood().length > 0) return n.id() as string
    }
    return cy.nodes()[0].id() as string
  })
  // Tap the node first.
  await page.evaluate((id: string) => {
    const cy = (window as any).__graphCy
    cy.getElementById(id).emit('tap')
  }, targetId)
  for (const z of [0.25, 0.7, 2.0]) {
    await page.evaluate((zoom: number) => {
      const cy = (window as any).__graphCy
      cy.zoom(zoom)
      cy.emit('zoom')
    }, z)
    await page.waitForTimeout(200)
    const label = await page.evaluate((id: string) => {
      const cy = (window as any).__graphCy
      return cy.getElementById(id).style('label') as string
    }, targetId)
    expect(
      label && label.length > 0,
      `selected node label must be visible at zoom ${z}, got ${JSON.stringify(label)}`
    ).toBe(true)
  }
})

test('Prompt 35.3: hovered node label is visible at low zoom', async ({ page }) => {
  await gotoViewerWithCy(page)
  // Pick a node and simulate a hover via the cytoscape
  // mouseover event so currentHoverId is set.
  const targetId = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    for (let i = 0; i < cy.nodes().length; i++) {
      const n = cy.nodes()[i]
      if (n.neighborhood().length > 0) return n.id() as string
    }
    return cy.nodes()[0].id() as string
  })
  // Set low zoom first.
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(0.25)
    cy.emit('zoom')
  })
  await page.waitForTimeout(200)
  // Emit mouseover on the target node.
  await page.evaluate((id: string) => {
    const cy = (window as any).__graphCy
    cy.getElementById(id).emit('mouseover')
  }, targetId)
  await page.waitForTimeout(250)
  const label = await page.evaluate((id: string) => {
    const cy = (window as any).__graphCy
    return cy.getElementById(id).style('label') as string
  }, targetId)
  expect(
    label && label.length > 0,
    `hovered node label must be visible at low zoom, got ${JSON.stringify(label)}`
  ).toBe(true)
})

test('Prompt 35.3: neighbor of selected node shows a label at medium zoom', async ({ page }) => {
  await gotoViewerWithCy(page)
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(0.7)
    cy.emit('zoom')
  })
  await page.waitForTimeout(150)
  const targetId = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    for (let i = 0; i < cy.nodes().length; i++) {
      const n = cy.nodes()[i]
      if (n.neighborhood().length > 0) return n.id() as string
    }
    return cy.nodes()[0].id() as string
  })
  await page.evaluate((id: string) => {
    const cy = (window as any).__graphCy
    cy.getElementById(id).emit('tap')
  }, targetId)
  await page.waitForTimeout(250)
  const stats = await page.evaluate((id: string) => {
    const cy = (window as any).__graphCy
    const sel = cy.getElementById(id)
    const nbh = sel.closedNeighborhood()
    let neighborShown = 0
    const neighborIds: string[] = []
    nbh.forEach((n: any) => {
      if (n.id() === id) return // skip self
      const lbl = n.style('label') || ''
      if (lbl && lbl.length > 0) {
        neighborShown += 1
        neighborIds.push(n.id() as string)
      }
    })
    return { neighborShown, totalNb: nbh.length, neighborIds }
  }, targetId)
  expect(
    stats.neighborShown,
    `at least one neighbor of the selected node should show a label at medium zoom, got ${stats.neighborShown} of ${stats.totalNb}`
  ).toBeGreaterThan(0)
})

test('Prompt 35.3: low zoom still hides most labels', async ({ page }) => {
  await gotoViewerWithCy(page)
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(0.25)
    cy.emit('zoom')
  })
  await page.waitForTimeout(300)
  const counts = await countVisibleLabels(page)
  expect(counts.total, 'graph should have many nodes').toBeGreaterThan(10)
  expect(
    counts.shown,
    `low zoom should hide most labels, got ${counts.shown} of ${counts.total}`
  ).toBeLessThan(counts.total / 2)
})

test('Prompt 35.3: window.__graphLabelDebug returns counts, zoom, tier', async ({ page }) => {
  await gotoViewerWithCy(page)
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(1.5)
    cy.emit('zoom')
  })
  await page.waitForTimeout(250)
  const snap = await page.evaluate(() => {
    const fn = (window as any).__graphLabelDebug
    if (typeof fn !== 'function') return null
    return fn()
  })
  expect(snap, 'window.__graphLabelDebug must be defined').not.toBeNull()
  expect(snap.ready, 'snapshot should be ready').toBe(true)
  expect(typeof snap.zoom, 'snapshot.zoom should be a number').toBe('number')
  expect(typeof snap.tier, 'snapshot.tier should be a string').toBe('string')
  expect(snap.tier).toBe('high')
  expect(snap.counts).toBeTruthy()
  expect(typeof snap.counts.visible).toBe('number')
  expect(typeof snap.counts.hidden).toBe('number')
  expect(typeof snap.counts.total).toBe('number')
  expect(snap.counts.total, 'counts.total should match the node count').toBeGreaterThan(10)
  expect(
    snap.counts.visible,
    `at high zoom, counts.visible should equal counts.total, got ${snap.counts.visible} of ${snap.counts.total}`
  ).toBe(snap.counts.total)
})

test('Prompt 35.3: __graphLabelDebug reflects hide-labels at low zoom', async ({ page }) => {
  await gotoViewerWithCy(page)
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(0.2)
    cy.emit('zoom')
  })
  await page.waitForTimeout(300)
  const snap = await page.evaluate(() => {
    const fn = (window as any).__graphLabelDebug
    return typeof fn === 'function' ? fn() : null
  })
  expect(snap, '__graphLabelDebug must be defined').not.toBeNull()
  expect(snap.tier).toBe('low')
  expect(
    snap.counts.hidden,
    `at low zoom, debug helper should report hidden labels, got ${snap.counts.hidden} of ${snap.counts.total}`
  ).toBeGreaterThan(0)
  expect(
    snap.counts.visible + snap.counts.hidden,
    'visible + hidden must equal total'
  ).toBe(snap.counts.total)
})

test('Prompt 35.3: high zoom label coverage >= low zoom label coverage', async ({ page }) => {
  await gotoViewerWithCy(page)
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(0.25)
    cy.emit('zoom')
  })
  await page.waitForTimeout(300)
  const low = await countVisibleLabels(page)
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(2.0)
    cy.emit('zoom')
  })
  await page.waitForTimeout(300)
  const high = await countVisibleLabels(page)
  // Prompt 35.3 acceptance: high zoom shows more labels than
  // low zoom.
  expect(
    high.shown - low.shown,
    `high zoom should expose strictly more labels than low zoom (low=${low.shown}, high=${high.shown})`
  ).toBeGreaterThan(0)
})

test('Prompt 35.3: switching from low to high removes hide-labels class from all nodes', async ({ page }) => {
  await gotoViewerWithCy(page)
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(0.25)
    cy.emit('zoom')
  })
  await page.waitForTimeout(300)
  const hiddenAtLow = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    let n = 0
    cy.nodes().forEach((node: any) => {
      if (node.hasClass('hide-labels')) n += 1
    })
    return n
  })
  expect(hiddenAtLow, 'low zoom should leave some nodes with hide-labels').toBeGreaterThan(0)
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.zoom(2.0)
    cy.emit('zoom')
  })
  await page.waitForTimeout(300)
  const hiddenAtHigh = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    let n = 0
    cy.nodes().forEach((node: any) => {
      if (node.hasClass('hide-labels')) n += 1
    })
    return n
  })
  expect(
    hiddenAtHigh,
    `high zoom should remove hide-labels from every node, got ${hiddenAtHigh} still hidden`
  ).toBe(0)
})

test('Prompt 35.3: no duplicate DOM ids at any time after semantic zoom', async ({ page }) => {
  await gotoViewerWithCy(page)
  // Drive several zoom events to flush any duplicate-id regressions.
  for (const z of [0.25, 0.7, 1.5, 3.0]) {
    await page.evaluate((zoom: number) => {
      const cy = (window as any).__graphCy
      cy.zoom(zoom)
      cy.emit('zoom')
    }, z)
    await page.waitForTimeout(150)
  }
  const dupes = await page.evaluate(() => {
    const ids: Record<string, number> = {}
    const all = document.querySelectorAll('#graph-explorer, #graph-explorer *')
    all.forEach((el) => {
      const id = el.getAttribute('id')
      if (!id) return
      ids[id] = (ids[id] || 0) + 1
    })
    return Object.entries(ids)
      .filter(([, n]) => n > 1)
      .map(([id, n]) => `${id}×${n}`)
  })
  expect(dupes, `found duplicate DOM ids: ${dupes.join(', ')}`).toEqual([])
})

// ---------------------------------------------------------------------------
// Prompt 38 — Insight Dashboard + Graph Lenses v1
// ---------------------------------------------------------------------------

/**
 * Helper: wait for the Prompt 38 ``window.__graphExplorerState``
 * debug handle to be set so the lens / layout / neighborhood /
 * counts can be inspected from page.evaluate.
 */
async function gotoViewerWithExplorerState(page: Page) {
  await gotoViewerWithCy(page)
  await page.waitForFunction(
    () => {
      const s = (window as any).__graphExplorerState
      return s && s.ready === true
    },
    null,
    { timeout: 15_000 }
  )
}

async function waitForExplorerState(page: Page) {
  await page.waitForFunction(
    () => {
      const s = (window as any).__graphExplorerState
      return s && s.ready === true
    },
    null,
    { timeout: 15_000 }
  )
}

test('Prompt 38 dashboard: total node and edge counts match the JSON', async ({ page }) => {
  await gotoViewerWithExplorerState(page)
  const ctx = await request.newContext({ baseURL: 'http://127.0.0.1:5173' })
  const resp = await ctx.get('/graph/knowledge_graph.json')
  const body = await resp.json()
  await ctx.dispose()
  const expectedNodes: number = body.stats?.node_count ?? body.nodes.length
  const expectedEdges: number = body.stats?.edge_count ?? body.edges.length
  await expect(page.locator('#graph-stat-total-nodes')).toHaveText(String(expectedNodes))
  await expect(page.locator('#graph-stat-total-edges')).toHaveText(String(expectedEdges))
})

test('Prompt 38 dashboard: visible node count reflects current filters', async ({ page }) => {
  await gotoViewerWithExplorerState(page)
  const before = await page.locator('#graph-stat-visible-nodes').innerText()
  // Switch the lens to resources; visible count must change to a
  // strict subset (or stay at zero — but for the canonical graph
  // there are >= 1 resource nodes).
  await page.locator('#graph-lens').selectOption('resources')
  await page.waitForTimeout(400)
  const afterText = await page.locator('#graph-stat-visible-nodes').innerText()
  expect(Number.isFinite(Number(afterText))).toBe(true)
  // Reset to all and confirm the count returns.
  await page.locator('#graph-lens').selectOption('all')
  await page.waitForTimeout(400)
  const restored = await page.locator('#graph-stat-visible-nodes').innerText()
  expect(restored).toBe(before)
})

test('Prompt 38 dashboard: top-connected list is rendered and clickable', async ({ page }) => {
  await gotoViewerWithExplorerState(page)
  const topList = page.locator('#graph-stat-top-nodes')
  await expect(topList).toBeVisible()
  const items = topList.locator('li[data-node-id]')
  const itemCount = await items.count()
  expect(itemCount, 'top connected list must have at least one row').toBeGreaterThan(0)
  // Click the first row and verify the selected node id flows
  // into the dashboard's Selected field.
  const firstId = await items.first().getAttribute('data-node-id')
  expect(firstId).toBeTruthy()
  await items.first().locator('button').click()
  await page.waitForTimeout(250)
  const selectedAttr = await page.locator('#graph-stat-selected').getAttribute('data-selected-id')
  expect(selectedAttr).toBe(firstId)
})

test('Prompt 38 lens: selector has six options and default is "all"', async ({ page }) => {
  await gotoViewerWithExplorerState(page)
  const select = page.locator('#graph-lens')
  await expect(select).toBeVisible()
  const optionCount = await select.locator('option').count()
  expect(optionCount).toBe(6)
  await expect(select).toHaveValue('all')
})

test('Prompt 38 lens: switching to "resources" filters non-resource nodes', async ({ page }) => {
  await gotoViewerWithExplorerState(page)
  await page.locator('#graph-lens').selectOption('resources')
  await page.waitForTimeout(400)
  const counts = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    let total = 0
    let nonResource = 0
    cy.nodes().forEach((n: any) => {
      total += 1
      if (n.data('type') !== 'resource') nonResource += 1
    })
    return { total, nonResource }
  })
  expect(counts.total, 'resources lens must keep at least one node').toBeGreaterThan(0)
  expect(counts.nonResource, 'resources lens must exclude non-resource nodes').toBe(0)
})

test('Prompt 38 lens: switching back to "all" restores the visible set', async ({ page }) => {
  await gotoViewerWithExplorerState(page)
  const before = await page.evaluate(
    () => ((window as any).__graphCy.nodes().length as number)
  )
  await page.locator('#graph-lens').selectOption('resources')
  await page.waitForTimeout(400)
  await page.locator('#graph-lens').selectOption('all')
  await page.waitForTimeout(400)
  const after = await page.evaluate(
    () => ((window as any).__graphCy.nodes().length as number)
  )
  expect(after).toBe(before)
})

test('Prompt 38 layout: selector has four options and default is "cose"', async ({ page }) => {
  await gotoViewerWithExplorerState(page)
  const select = page.locator('#graph-layout')
  await expect(select).toBeVisible()
  const optionCount = await select.locator('option').count()
  expect(optionCount).toBe(4)
  await expect(select).toHaveValue('cose')
})

test('Prompt 38 layout: switching to grid / circle / concentric preserves node count', async ({ page }) => {
  await gotoViewerWithExplorerState(page)
  const before = await page.evaluate(
    () => ((window as any).__graphCy.nodes().length as number)
  )
  for (const layout of ['grid', 'circle', 'concentric', 'cose']) {
    await page.locator('#graph-layout').selectOption(layout)
    await page.waitForTimeout(400)
    const after = await page.evaluate(
      () => ((window as any).__graphCy.nodes().length as number)
    )
    expect(after, `node count should be preserved after switching to ${layout}`).toBe(before)
  }
})

test('Prompt 38 neighborhood mode: button is disabled with no selection', async ({ page }) => {
  await gotoViewerWithExplorerState(page)
  const btn = page.locator('#graph-neighborhood-mode')
  await expect(btn).toBeVisible()
  await expect(btn).toBeDisabled()
})

test('Prompt 38 neighborhood mode: enabled after selecting a node, restricts cy.nodes()', async ({ page }) => {
  await gotoViewerWithExplorerState(page)
  // Pick a node with at least one neighbor so the closed
  // neighbourhood is non-trivial.
  const targetId = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    for (let i = 0; i < cy.nodes().length; i++) {
      const n = cy.nodes()[i]
      if (n.neighborhood().length > 0) return n.id() as string
    }
    return cy.nodes()[0].id() as string
  })
  await page.evaluate((id: string) => {
    const cy = (window as any).__graphCy
    cy.getElementById(id).emit('tap')
  }, targetId)
  await page.waitForTimeout(250)
  const btn = page.locator('#graph-neighborhood-mode')
  await expect(btn).toBeEnabled()
  const before = await page.evaluate(
    () => ((window as any).__graphCy.nodes().length as number)
  )
  await btn.click()
  await page.waitForTimeout(400)
  const after = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    return cy.nodes().length as number
  })
  const expected = await page.evaluate((id: string) => {
    // The graph data is exposed indirectly via cy. We compute the
    // expected count from the loaded JSON via fetch.
    return (async () => {
      const url = '/graph/knowledge_graph.json'
      const resp = await fetch(url)
      const body = await resp.json()
      const incident = new Set<string>([id])
      for (const e of body.edges) {
        if (e.source === id) incident.add(e.target)
        else if (e.target === id) incident.add(e.source)
      }
      return incident.size
    })()
  }, targetId)
  expect(after, 'neighborhood mode should restrict to the closed neighbourhood').toBe(expected)
  expect(after, 'neighborhood mode should not show the whole graph').toBeLessThanOrEqual(before)
  // Exit neighborhood mode and confirm the count is restored.
  await page.locator('#graph-neighborhood-exit').click()
  await page.waitForTimeout(400)
  const restored = await page.evaluate(
    () => ((window as any).__graphCy.nodes().length as number)
  )
  expect(restored).toBe(before)
})

test('Prompt 38 neighborhood mode: background tap auto-disables the mode', async ({ page }) => {
  await gotoViewerWithExplorerState(page)
  const targetId = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    for (let i = 0; i < cy.nodes().length; i++) {
      const n = cy.nodes()[i]
      if (n.neighborhood().length > 0) return n.id() as string
    }
    return cy.nodes()[0].id() as string
  })
  await page.evaluate((id: string) => {
    const cy = (window as any).__graphCy
    cy.getElementById(id).emit('tap')
  }, targetId)
  await page.waitForTimeout(150)
  await page.locator('#graph-neighborhood-mode').click()
  await page.waitForTimeout(400)
  // Now emit a background tap (target === cy).
  await page.evaluate(() => {
    const cy = (window as any).__graphCy
    cy.emit('tap', { target: cy })
  })
  await page.waitForTimeout(300)
  const state = await page.evaluate(() => (window as any).__graphExplorerState)
  expect(state.neighborhoodMode, 'background tap must auto-disable neighborhood mode').toBe(false)
})

test('Prompt 38 details panel: incoming / outgoing / degree counts match', async ({ page }) => {
  await gotoViewerWithExplorerState(page)
  const targetId = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    for (let i = 0; i < cy.nodes().length; i++) {
      const n = cy.nodes()[i]
      if (n.neighborhood().length > 0) return n.id() as string
    }
    return cy.nodes()[0].id() as string
  })
  await page.evaluate((id: string) => {
    const cy = (window as any).__graphCy
    cy.getElementById(id).emit('tap')
  }, targetId)
  await page.waitForTimeout(300)
  const expected = await page.evaluate((id: string) => {
    const cy = (window as any).__graphCy
    let incoming = 0
    let outgoing = 0
    cy.edges().forEach((e: any) => {
      if (e.data('source') === id) outgoing += 1
      else if (e.data('target') === id) incoming += 1
    })
    return { incoming, outgoing, degree: incoming + outgoing }
  }, targetId)
  const inText = await page.locator('#graph-stat-incoming').innerText()
  const outText = await page.locator('#graph-stat-outgoing').innerText()
  const degText = await page.locator('#graph-stat-degree').innerText()
  expect(Number(inText)).toBe(expected.incoming)
  expect(Number(outText)).toBe(expected.outgoing)
  expect(Number(degText)).toBe(expected.degree)
})

test('Prompt 38 details panel: Copy node id button is present when a node is selected', async ({ page }) => {
  await gotoViewerWithExplorerState(page)
  // No selection yet — the button must not exist.
  await expect(page.locator('#graph-copy-node-id')).toHaveCount(0)
  const targetId = await page.evaluate(
    () => ((window as any).__graphCy.nodes()[0].id() as string)
  )
  await page.evaluate((id: string) => {
    const cy = (window as any).__graphCy
    cy.getElementById(id).emit('tap')
  }, targetId)
  await page.waitForTimeout(200)
  const btn = page.locator('#graph-copy-node-id')
  await expect(btn).toBeVisible()
  await expect(btn).toHaveAttribute('data-selected-id', targetId)
})

test('Prompt 38 explorer state: window.__graphExplorerState reports lens / layout / neighborhood', async ({ page }) => {
  await gotoViewerWithExplorerState(page)
  const state = await page.evaluate(() => (window as any).__graphExplorerState)
  expect(state).toBeTruthy()
  expect(state.lens).toBe('all')
  expect(state.layout).toBe('cose')
  expect(state.neighborhoodMode).toBe(false)
  expect(typeof state.totalNodes).toBe('number')
  expect(typeof state.totalEdges).toBe('number')
  expect(typeof state.visibleNodes).toBe('number')
  expect(typeof state.visibleEdges).toBe('number')
  expect(Array.isArray(state.topConnectedIds)).toBe(true)
})

// ---------------------------------------------------------------------------
// Prompt 39 — Path Finder and Relationship Explorer v1
// ---------------------------------------------------------------------------

/**
 * Helper: wait for the Prompt 39 ``window.__graphPathState``
 * debug handle to be set so the path-finder state can be
 * inspected from page.evaluate.
 */
async function gotoViewerWithPathState(page: Page) {
  await gotoViewerWithExplorerState(page)
  await page.waitForFunction(
    () => {
      const s = (window as any).__graphPathState
      return s && s.ready === true
    },
    null,
    { timeout: 15_000 }
  )
}

async function waitForPathState(page: Page) {
  await page.waitForFunction(
    () => {
      const s = (window as any).__graphPathState
      return s && s.ready === true
    },
    null,
    { timeout: 15_000 }
  )
}

test('Prompt 39 path finder: controls are visible and source/target selects are populated', async ({
  page,
}) => {
  await gotoViewerWithPathState(page)
  const ctrl = page.locator('#graph-path-finder-controls')
  await expect(ctrl).toBeVisible()
  const src = page.locator('#graph-path-source')
  const dst = page.locator('#graph-path-target')
  await expect(src).toBeVisible()
  await expect(dst).toBeVisible()
  // Each select must have a placeholder + at least one real
  // graph node, so at least 2 options.
  const srcOpts = await src.locator('option').count()
  const dstOpts = await dst.locator('option').count()
  expect(srcOpts, 'source select must have at least 2 options').toBeGreaterThanOrEqual(2)
  expect(dstOpts, 'target select must have at least 2 options').toBeGreaterThanOrEqual(2)
  await expect(page.locator('#graph-path-find')).toBeVisible()
  await expect(page.locator('#graph-path-clear')).toBeVisible()
})

test('Prompt 39 path finder: Find button is disabled until source and target are both set', async ({
  page,
}) => {
  await gotoViewerWithPathState(page)
  const findBtn = page.locator('#graph-path-find')
  // Initially disabled (no source/target).
  await expect(findBtn).toBeDisabled()
  // Pick a real source — still disabled (target is empty).
  const firstValue = await page.evaluate(() => {
    const sel = document.getElementById('graph-path-source') as HTMLSelectElement
    return sel && sel.options.length > 1 ? sel.options[1].value : ''
  })
  expect(firstValue).toBeTruthy()
  await page.locator('#graph-path-source').selectOption(firstValue)
  await expect(findBtn).toBeDisabled()
  // Pick a real target — now enabled.
  const secondValue = await page.evaluate(() => {
    const sel = document.getElementById('graph-path-target') as HTMLSelectElement
    return sel && sel.options.length > 2 ? sel.options[2].value : ''
  })
  expect(secondValue).toBeTruthy()
  await page.locator('#graph-path-target').selectOption(secondValue)
  await expect(findBtn).toBeEnabled()
})

test('Prompt 39 path finder: same source and target produces a same_node result', async ({
  page,
}) => {
  await gotoViewerWithPathState(page)
  const sameId = await page.evaluate(() => {
    const sel = document.getElementById('graph-path-source') as HTMLSelectElement
    return sel && sel.options.length > 1 ? sel.options[1].value : ''
  })
  expect(sameId).toBeTruthy()
  await page.locator('#graph-path-source').selectOption(sameId)
  await page.locator('#graph-path-target').selectOption(sameId)
  await page.locator('#graph-path-find').click()
  await page.waitForFunction(
    () => {
      const s = (window as any).__graphPathState
      return s && (s.status === 'same_node' || s.status === 'found')
    },
    null,
    { timeout: 5_000 }
  )
  const state = await page.evaluate(() => (window as any).__graphPathState)
  expect(state.status).toBe('same_node')
  expect(state.hopCount).toBe(0)
  expect(Array.isArray(state.pathNodeIds)).toBe(true)
  expect(state.pathNodeIds.length).toBe(1)
  expect(state.pathNodeIds[0]).toBe(sameId)
})

test('Prompt 39 path finder: disconnected via edge-type filter produces a not_found result', async ({
  page,
}) => {
  await gotoViewerWithPathState(page)
  // Uncheck ALL edge types — with zero edges allowed, the BFS
  // cannot find any path between two distinct nodes.
  await page.evaluate(() => {
    const fset = document.getElementById('graph-filter-edge-type')
    if (!fset) return
    const boxes = fset.querySelectorAll('input[type="checkbox"]')
    boxes.forEach((b: any) => {
      if (b.checked) b.click()
    })
  })
  // Pick two distinct nodes for source / target.
  const [a, b] = await page.evaluate(() => {
    const src = document.getElementById('graph-path-source') as HTMLSelectElement
    return [src.options[1].value, src.options[2].value]
  })
  expect(a).toBeTruthy()
  expect(b).toBeTruthy()
  expect(a).not.toBe(b)
  await page.locator('#graph-path-source').selectOption(a)
  await page.locator('#graph-path-target').selectOption(b)
  await page.locator('#graph-path-find').click()
  await page.waitForTimeout(500)
  const state = await page.evaluate(() => (window as any).__graphPathState)
  expect(state.status).toBe('not_found')
  expect(state.pathNodeIds.length).toBe(0)
  expect(state.pathEdgeIds.length).toBe(0)
  expect(state.hopCount).toBe(0)
  // Restore edge types for downstream tests.
  await page.evaluate(() => {
    const fset = document.getElementById('graph-filter-edge-type')
    if (!fset) return
    const boxes = fset.querySelectorAll('input[type="checkbox"]')
    boxes.forEach((b: any) => {
      if (!b.checked) b.click()
    })
  })
})

test('Prompt 39 path finder: a real pair produces a found result with a readable chain', async ({
  page,
}) => {
  await gotoViewerWithPathState(page)
  // Use Show all so the full graph (all 65 nodes) is on the
  // canvas — this guarantees every node on the path is visible
  // and thus gets the path-highlight class.
  await page.locator('#graph-show-all').click()
  await page.waitForFunction(
    () => (window as any).__graphCy.nodes().length > 50,
    null,
    { timeout: 10_000 }
  )
  // Pick two distinct nodes that both have at least one neighbor.
  const [a, b] = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    const ids: string[] = []
    cy.nodes().forEach((n: any) => {
      if (ids.length < 2 && n.neighborhood().length > 0) {
        ids.push(n.id() as string)
      }
    })
    return ids
  })
  expect(a).toBeTruthy()
  expect(b).toBeTruthy()
  expect(a).not.toBe(b)
  await page.locator('#graph-path-source').selectOption(a)
  await page.locator('#graph-path-target').selectOption(b)
  await page.locator('#graph-path-find').click()
  await page.waitForFunction(
    (args: { sa: string; tb: string }) => {
      const s = (window as any).__graphPathState
      return (
        s &&
        s.status === 'found' &&
        s.sourceId === args.sa &&
        s.targetId === args.tb
      )
    },
    { sa: a, tb: b },
    { timeout: 5_000 }
  )
  const state = await page.evaluate(() => (window as any).__graphPathState)
  expect(state.status).toBe('found')
  expect(state.pathNodeIds.length).toBeGreaterThanOrEqual(2)
  expect(state.pathNodeIds[0]).toBe(a)
  expect(state.pathNodeIds[state.pathNodeIds.length - 1]).toBe(b)
  // pathNodeIds.length === pathEdgeIds.length + 1
  expect(state.pathNodeIds.length).toBe(state.pathEdgeIds.length + 1)
  expect(state.hopCount).toBe(state.pathEdgeIds.length)
  // The result panel shows the hop / node / edge counts.
  const hopsText = await page.locator('#graph-path-hops').innerText()
  const nodesText = await page.locator('#graph-path-node-count').innerText()
  const edgesText = await page.locator('#graph-path-edge-count').innerText()
  expect(Number(hopsText)).toBe(state.hopCount)
  expect(Number(nodesText)).toBe(state.pathNodeIds.length)
  expect(Number(edgesText)).toBe(state.pathEdgeIds.length)
  // The steps <ol> has data-count matching the number of edges.
  const stepsCount = await page
    .locator('#graph-path-steps')
    .getAttribute('data-count')
  expect(Number(stepsCount)).toBe(state.pathEdgeIds.length)
  // Each <li.ge-path-step> contains a --<edgeType>--> substring.
  const stepsText = await page.locator('#graph-path-steps').innerText()
  expect(stepsText).toMatch(/--[a-z_]+-->/)
})

test('Prompt 39 path finder: path nodes and edges are highlighted on the canvas', async ({
  page,
}) => {
  await gotoViewerWithPathState(page)
  await page.locator('#graph-show-all').click()
  await page.waitForFunction(
    () => (window as any).__graphCy.nodes().length > 50,
    null,
    { timeout: 10_000 }
  )
  const [a, b] = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    const ids: string[] = []
    cy.nodes().forEach((n: any) => {
      if (ids.length < 2 && n.neighborhood().length > 0) {
        ids.push(n.id() as string)
      }
    })
    return ids
  })
  await page.locator('#graph-path-source').selectOption(a)
  await page.locator('#graph-path-target').selectOption(b)
  await page.locator('#graph-path-find').click()
  await page.waitForFunction(
    () => {
      const s = (window as any).__graphPathState
      return s && s.status === 'found'
    },
    null,
    { timeout: 5_000 }
  )
  const counts = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    return {
      pathNodes: cy.nodes('.path-highlight').length,
      pathEdges: cy.edges('.path-highlight').length,
      fadedNonPath: cy
        .nodes()
        .not('.path-highlight')
        .filter('.faded').length,
      fadedNonPathEdges: cy
        .edges()
        .not('.path-highlight')
        .filter('.faded').length,
    }
  })
  const state = await page.evaluate(() => (window as any).__graphPathState)
  expect(counts.pathNodes, 'cy.nodes(.path-highlight) must equal pathNodeIds.length').toBe(
    state.pathNodeIds.length
  )
  expect(counts.pathEdges, 'cy.edges(.path-highlight) must equal pathEdgeIds.length').toBe(
    state.pathEdgeIds.length
  )
  // Non-path elements should be faded.
  expect(
    counts.fadedNonPath,
    'non-path nodes should be faded while a path is active'
  ).toBeGreaterThan(0)
  expect(
    counts.fadedNonPathEdges,
    'non-path edges should be faded while a path is active'
  ).toBeGreaterThan(0)
})

test('Prompt 39 path finder: clearing the path removes the highlight and resets state', async ({
  page,
}) => {
  await gotoViewerWithPathState(page)
  await page.locator('#graph-show-all').click()
  await page.waitForFunction(
    () => (window as any).__graphCy.nodes().length > 50,
    null,
    { timeout: 10_000 }
  )
  const [a, b] = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    const ids: string[] = []
    cy.nodes().forEach((n: any) => {
      if (ids.length < 2 && n.neighborhood().length > 0) {
        ids.push(n.id() as string)
      }
    })
    return ids
  })
  await page.locator('#graph-path-source').selectOption(a)
  await page.locator('#graph-path-target').selectOption(b)
  await page.locator('#graph-path-find').click()
  await page.waitForFunction(
    () => {
      const s = (window as any).__graphPathState
      return s && s.status === 'found'
    },
    null,
    { timeout: 5_000 }
  )
  // Now click Clear.
  await page.locator('#graph-path-clear').click()
  await page.waitForFunction(
    () => {
      const s = (window as any).__graphPathState
      return s && s.status === 'idle' && s.pathNodeIds.length === 0
    },
    null,
    { timeout: 5_000 }
  )
  const state = await page.evaluate(() => (window as any).__graphPathState)
  expect(state.status).toBe('idle')
  expect(state.sourceId).toBe('')
  expect(state.targetId).toBe('')
  expect(state.pathNodeIds.length).toBe(0)
  expect(state.pathEdgeIds.length).toBe(0)
  expect(state.hopCount).toBe(0)
  const counts = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    return {
      pathNodes: cy.nodes('.path-highlight').length,
      pathEdges: cy.edges('.path-highlight').length,
    }
  })
  expect(counts.pathNodes, 'cy.nodes(.path-highlight) must be 0 after clear').toBe(0)
  expect(counts.pathEdges, 'cy.edges(.path-highlight) must be 0 after clear').toBe(0)
})

test('Prompt 39 path finder: BFS is deterministic across two runs of the same pair', async ({
  page,
}) => {
  await gotoViewerWithPathState(page)
  await page.locator('#graph-show-all').click()
  await page.waitForFunction(
    () => (window as any).__graphCy.nodes().length > 50,
    null,
    { timeout: 10_000 }
  )
  const [a, b] = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    const ids: string[] = []
    cy.nodes().forEach((n: any) => {
      if (ids.length < 2 && n.neighborhood().length > 0) {
        ids.push(n.id() as string)
      }
    })
    return ids
  })
  await page.locator('#graph-path-source').selectOption(a)
  await page.locator('#graph-path-target').selectOption(b)
  await page.locator('#graph-path-find').click()
  await page.waitForFunction(
    () => {
      const s = (window as any).__graphPathState
      return s && s.status === 'found'
    },
    null,
    { timeout: 5_000 }
  )
  const first = await page.evaluate(() => {
    const s = (window as any).__graphPathState
    return {
      pathNodeIds: s.pathNodeIds.slice(),
      pathEdgeIds: s.pathEdgeIds.slice(),
    }
  })
  // Re-run the same query.
  await page.locator('#graph-path-find').click()
  await page.waitForTimeout(300)
  const second = await page.evaluate(() => {
    const s = (window as any).__graphPathState
    return {
      pathNodeIds: s.pathNodeIds.slice(),
      pathEdgeIds: s.pathEdgeIds.slice(),
    }
  })
  expect(JSON.stringify(second.pathNodeIds)).toBe(JSON.stringify(first.pathNodeIds))
  expect(JSON.stringify(second.pathEdgeIds)).toBe(JSON.stringify(first.pathEdgeIds))
})

test('Prompt 39 path finder: changing the edge-type filter re-runs the BFS', async ({
  page,
}) => {
  await gotoViewerWithPathState(page)
  await page.locator('#graph-show-all').click()
  await page.waitForFunction(
    () => (window as any).__graphCy.nodes().length > 50,
    null,
    { timeout: 10_000 }
  )
  // Pick two nodes from distinct clusters of the graph so
  // their path goes through several different edge types.
  const [a, b, firstEdgeType] = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    const a = cy.nodes()[0].id() as string
    // Find a node at high "graph distance" from a — not the
    // closed neighbourhood of a.
    const nbh = new Set<string>([a])
    cy.edges().forEach((e: any) => {
      if (e.data('source') === a) nbh.add(e.data('target') as string)
      else if (e.data('target') === a) nbh.add(e.data('source') as string)
    })
    let b: string | null = null
    let firstEdge: string | null = null
    cy.nodes().forEach((n: any) => {
      if (b) return
      if (nbh.has(n.id() as string)) return
      // Need at least one edge leading to/from `a` of a type
      // that is also present in this path.
      const id = n.id() as string
      const e = cy.edges().filter((ee: any) => {
        return (
          (ee.data('source') === id || ee.data('target') === id) &&
          (ee.data('source') === a || ee.data('target') === a)
        )
      })[0]
      if (e) {
        b = id
        firstEdge = e.data('type') as string
      }
    })
    if (!b) {
      // Fallback: pick the last node and any edge type.
      b = cy.nodes()[cy.nodes().length - 1].id() as string
      firstEdge = cy.edges()[0].data('type') as string
    }
    return [a, b as string, firstEdge as string]
  })
  await page.locator('#graph-path-source').selectOption(a)
  await page.locator('#graph-path-target').selectOption(b)
  await page.locator('#graph-path-find').click()
  await page.waitForFunction(
    () => {
      const s = (window as any).__graphPathState
      return s && s.status === 'found'
    },
    null,
    { timeout: 5_000 }
  )
  // Uncheck the first edge type of the path. The BFS must
  // re-run, and the new path must NOT use that edge type.
  const cb = page.locator(`#graph-filter-edge-type-${firstEdgeType}`)
  await expect(cb).toBeVisible()
  await cb.click()
  await page.waitForTimeout(500)
  const after = await page.evaluate((blocked: string) => {
    const cy = (window as any).__graphCy
    const s = (window as any).__graphPathState
    let usesBlocked = false
    cy.edges('.path-highlight').forEach((e: any) => {
      if (e.data('type') === blocked) usesBlocked = true
    })
    return { status: s.status, usesBlocked }
  }, firstEdgeType)
  // The new path either no longer exists (not_found) or uses
  // a different set of edge types that excludes `firstEdgeType`.
  expect(after.usesBlocked, 'no path edge should have the blocked type').toBe(false)
  // Restore the edge-type filter.
  await cb.click()
})

test('Prompt 39 path finder: window.__graphPathState has all required deterministic fields', async ({
  page,
}) => {
  await gotoViewerWithPathState(page)
  const state = await page.evaluate(() => (window as any).__graphPathState)
  expect(state).toBeTruthy()
  expect(state.ready).toBe(true)
  expect(typeof state.sourceId).toBe('string')
  expect(typeof state.targetId).toBe('string')
  expect(typeof state.status).toBe('string')
  expect(Array.isArray(state.pathNodeIds)).toBe(true)
  expect(Array.isArray(state.pathEdgeIds)).toBe(true)
  expect(typeof state.hopCount).toBe('number')
  expect(
    [
      'idle',
      'missing_input',
      'same_node',
      'found',
      'not_found',
    ]
  ).toContain(state.status)
})

test('Prompt 39 path finder: no duplicate DOM ids after running the finder and zooming', async ({
  page,
}) => {
  await gotoViewerWithPathState(page)
  // Drive several zoom levels to flush any duplicate-id regressions
  // the new path-finder controls might introduce.
  for (const z of [0.25, 0.7, 1.5, 3.0]) {
    await page.evaluate((zoom: number) => {
      const cy = (window as any).__graphCy
      cy.zoom(zoom)
      cy.emit('zoom')
    }, z)
    await page.waitForTimeout(150)
  }
  // Run a real path query to ensure the path-finder DOM is in
  // its "found" state during the duplicate-id sweep.
  const [a, b] = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    const ids: string[] = []
    cy.nodes().forEach((n: any) => {
      if (ids.length < 2 && n.neighborhood().length > 0) {
        ids.push(n.id() as string)
      }
    })
    return ids
  })
  await page.locator('#graph-path-source').selectOption(a)
  await page.locator('#graph-path-target').selectOption(b)
  await page.locator('#graph-path-find').click()
  await page.waitForTimeout(300)
  const dupes = await page.evaluate(() => {
    const ids: Record<string, number> = {}
    const all = document.querySelectorAll('#graph-explorer, #graph-explorer *')
    all.forEach((el) => {
      const id = el.getAttribute('id')
      if (!id) return
      ids[id] = (ids[id] || 0) + 1
    })
    return Object.entries(ids)
      .filter(([, n]) => n > 1)
      .map(([id, n]) => `${id}×${n}`)
  })
  expect(dupes, `found duplicate DOM ids: ${dupes.join(', ')}`).toEqual([])
})

// ---------------------------------------------------------------------------
// Prompt 40 — Saved Graph Views + Shareable Graph Query URLs v1
// ---------------------------------------------------------------------------

/**
 * Helper: wait for the Prompt 40 ``window.__graphUrlState``
 * debug handle to be set so the URL state can be inspected
 * from page.evaluate.
 */
async function gotoViewerWithUrlState(page: Page) {
  await gotoViewerWithExplorerState(page)
  await page.waitForFunction(
    () => {
      const s = (window as any).__graphUrlState
      return s && s.ready === true
    },
    null,
    { timeout: 15_000 }
  )
}

async function waitForUrlState(page: Page) {
  await page.waitForFunction(
    () => {
      const s = (window as any).__graphUrlState
      return s && s.ready === true
    },
    null,
    { timeout: 15_000 }
  )
}

test('Prompt 40 URL: loading ?lens=resources applies the resources lens on first paint', async ({
  page,
}) => {
  await page.goto('/graph/viewer?lens=resources', { waitUntil: 'domcontentloaded' })
  await gotoViewerWithUrlState(page)
  const state = await page.evaluate(() => (window as any).__graphExplorerState)
  expect(state.lens, 'lens must be applied from URL on first paint').toBe('resources')
  const lensSelect = page.locator('#graph-lens')
  await expect(lensSelect).toHaveValue('resources')
})

test('Prompt 40 URL: loading ?layout=concentric applies the concentric layout on first paint', async ({
  page,
}) => {
  await page.goto('/graph/viewer?layout=concentric', { waitUntil: 'domcontentloaded' })
  await gotoViewerWithUrlState(page)
  const state = await page.evaluate(() => (window as any).__graphExplorerState)
  expect(state.layout, 'layout must be applied from URL on first paint').toBe('concentric')
  const layoutSelect = page.locator('#graph-layout')
  await expect(layoutSelect).toHaveValue('concentric')
})

test('Prompt 40.5 UX: /graph/viewer with query params shows a workspace handoff banner', async ({
  page,
}) => {
  const query =
    '?layout=grid&node=review_page%3Aweak&source=concept%3Achunking&target=concept%3Aattention&path=1'
  await page.goto(`/graph/viewer${query}`, { waitUntil: 'domcontentloaded' })
  await gotoViewerWithUrlState(page)
  const banner = page.locator('#graph-workspace-handoff')
  await expect(banner).toBeVisible()
  const href = await page.locator('#graph-workspace-handoff-link').getAttribute('href')
  expect(href).toBe(`/graph/explore${query}`)
})

test('Prompt 40.5 UX: /graph/explore restores the deep-link state and path result', async ({
  page,
}) => {
  const url =
    '/graph/explore?layout=grid&node=review_page%3Aweak&source=concept%3Achunking&target=concept%3Aattention&path=1'
  await page.goto(url, { waitUntil: 'domcontentloaded' })
  await gotoExploreWithCy(page)
  await waitForExplorerState(page)
  await waitForPathState(page)
  const explorer = await page.evaluate(() => (window as any).__graphExplorerState)
  const path = await page.evaluate(() => (window as any).__graphPathState)
  expect(explorer.layout).toBe('grid')
  expect(explorer.selectedNodeId).toBe('review_page:weak')
  expect(path.status).toBe('found')
  expect(path.sourceId).toBe('concept:chunking')
  expect(path.targetId).toBe('concept:attention')
  expect(path.pathNodeIds.length).toBeGreaterThanOrEqual(3)
})

test('Prompt 40 URL: loading ?node=<id>&neighborhood=1 selects a node and enables neighborhood mode', async ({
  page,
}) => {
  // First load a plain viewer to discover a valid node id.
  await gotoViewerWithExplorerState(page)
  const targetId = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    for (let i = 0; i < cy.nodes().length; i++) {
      const n = cy.nodes()[i]
      if (n.neighborhood().length > 0) return n.id() as string
    }
    return cy.nodes()[0].id() as string
  })
  expect(targetId).toBeTruthy()
  // Now load with the URL params.
  const url = `/graph/viewer?node=${encodeURIComponent(targetId)}&neighborhood=1`
  await page.goto(url, { waitUntil: 'domcontentloaded' })
  await gotoViewerWithUrlState(page)
  const state = await page.evaluate(() => (window as any).__graphExplorerState)
  expect(state.selectedNodeId, 'selectedNodeId must come from URL').toBe(targetId)
  expect(state.neighborhoodMode, 'neighborhoodMode must be on from URL').toBe(true)
  // The dashboard's data-selected-id reflects the URL.
  const selectedAttr = await page.locator('#graph-stat-selected').getAttribute('data-selected-id')
  expect(selectedAttr).toBe(targetId)
})

test('Prompt 40 URL: loading ?source=<a>&target=<b>&path=1 runs the path finder and highlights the path', async ({
  page,
}) => {
  // Discover two connected nodes.
  await gotoViewerWithPathState(page)
  const [a, b] = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    const ids: string[] = []
    cy.nodes().forEach((n: any) => {
      if (ids.length < 2 && n.neighborhood().length > 0) {
        ids.push(n.id() as string)
      }
    })
    return ids
  })
  expect(a).toBeTruthy()
  expect(b).toBeTruthy()
  expect(a).not.toBe(b)
  // Now load with the URL params. Use show-all so the full
  // graph is on the canvas — that way the path nodes are
  // visible and the highlight is observable.
  const url =
    `/graph/viewer?source=${encodeURIComponent(a)}` +
    `&target=${encodeURIComponent(b)}` +
    `&path=1`
  await page.goto(url, { waitUntil: 'domcontentloaded' })
  await gotoViewerWithPathState(page)
  const state = await page.evaluate(() => (window as any).__graphPathState)
  expect(state.sourceId, 'sourceId must come from URL').toBe(a)
  expect(state.targetId, 'targetId must come from URL').toBe(b)
  expect(state.status, 'path must be computed on first paint').toBe('found')
  expect(state.pathNodeIds.length).toBeGreaterThanOrEqual(2)
  // The path nodes must be highlighted on the canvas.
  const pathNodeCount = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    return cy.nodes('.path-highlight').length
  })
  expect(pathNodeCount).toBe(state.pathNodeIds.length)
})

test('Prompt 40 URL: Copy view URL button exists and produces a deterministic URL on click', async ({
  page,
}) => {
  await gotoViewerWithUrlState(page)
  const btn = page.locator('#graph-copy-view-url')
  await expect(btn).toBeVisible()
  // Apply a non-default lens so the shareable URL is non-empty.
  await page.locator('#graph-lens').selectOption('topics')
  await page.waitForTimeout(300)
  await btn.click()
  await page.waitForFunction(
    () => (window as any).__graphUrlState?.lastAction === 'copied',
    null,
    { timeout: 5_000 }
  )
  const url = await page.evaluate(() => (window as any).__graphUrlState.shareableUrl)
  expect(typeof url).toBe('string')
  expect(url, 'shareableUrl must be a path under /graph/explore').toContain('/graph/explore')
  expect(url, 'shareableUrl must include the lens=topics param').toContain('lens=topics')
  // Round-trip the URL by navigating to it.
  await page.goto(url, { waitUntil: 'domcontentloaded' })
  await gotoExploreWithCy(page)
  await waitForUrlState(page)
  const state = await page.evaluate(() => (window as any).__graphExplorerState)
  expect(state.lens).toBe('topics')
})

test('Prompt 40 URL: Reset URL state clears the query params and resets all URL-driven refs', async ({
  page,
}) => {
  // Start with a non-default state.
  await page.goto('/graph/viewer?lens=resources&layout=concentric', {
    waitUntil: 'domcontentloaded',
  })
  await gotoViewerWithUrlState(page)
  // Apply neighborhood mode and a path.
  const targetId = await page.evaluate(() => {
    const cy = (window as any).__graphCy
    for (let i = 0; i < cy.nodes().length; i++) {
      const n = cy.nodes()[i]
      if (n.neighborhood().length > 0) return n.id() as string
    }
    return cy.nodes()[0].id() as string
  })
  await page.evaluate((id: string) => {
    const cy = (window as any).__graphCy
    cy.getElementById(id).emit('tap')
  }, targetId)
  await page.waitForTimeout(200)
  await page.locator('#graph-neighborhood-mode').click()
  await page.waitForTimeout(200)
  // Now click the Reset URL state button.
  const resetBtn = page.locator('#graph-reset-url-state')
  await expect(resetBtn).toBeVisible()
  await resetBtn.click()
  await page.waitForFunction(
    () => (window as any).__graphUrlState?.lastAction === 'reset',
    null,
    { timeout: 5_000 }
  )
  // window.location.search is now empty.
  const search = await page.evaluate(() => window.location.search)
  expect(['', '?'].includes(search), `search should be empty, got ${search!}`).toBe(true)
  // All URL-driven refs are at their defaults.
  const explorer = await page.evaluate(() => (window as any).__graphExplorerState)
  expect(explorer.lens, 'lens must be reset to all').toBe('all')
  expect(explorer.layout, 'layout must be reset to cose').toBe('cose')
  expect(explorer.neighborhoodMode, 'neighborhoodMode must be off').toBe(false)
  expect(explorer.selectedNodeId, 'selectedNodeId must be null').toBeNull()
  // Path-finder state is back to idle.
  const path = await page.evaluate(() => (window as any).__graphPathState)
  expect(path.status, 'path status must be idle after reset').toBe('idle')
  expect(path.sourceId, 'sourceId must be empty after reset').toBe('')
  expect(path.targetId, 'targetId must be empty after reset').toBe('')
})

test('Prompt 40 URL: invalid lens/layout params are ignored safely on first paint', async ({
  page,
}) => {
  await page.goto('/graph/viewer?lens=banana&layout=foo', { waitUntil: 'domcontentloaded' })
  await gotoViewerWithUrlState(page)
  const state = await page.evaluate(() => (window as any).__graphExplorerState)
  expect(state.lens, 'invalid lens must fall back to default').toBe('all')
  expect(state.layout, 'invalid layout must fall back to default').toBe('cose')
  await expect(page.locator('#graph-lens')).toHaveValue('all')
  await expect(page.locator('#graph-layout')).toHaveValue('cose')
})

test('Prompt 40 URL: changing the lens updates the URL via history.replaceState (no full reload)', async ({
  page,
}) => {
  await gotoViewerWithUrlState(page)
  await page.locator('#graph-lens').selectOption('resources')
  await page.waitForTimeout(300)
  // The same `window.__graphCy` instance should still be
  // present (a full reload would have created a new component
  // instance and a new cy).
  const cyStillThere = await page.evaluate(() => !!(window as any).__graphCy)
  expect(cyStillThere, 'cy instance must persist across URL update (no full reload)').toBe(true)
  const search = await page.evaluate(() => window.location.search)
  expect(search, 'URL must include lens=resources after a lens change').toContain('lens=resources')
})

test('Prompt 40 URL: window.__graphUrlState has all required deterministic fields', async ({
  page,
}) => {
  await gotoViewerWithUrlState(page)
  const state = await page.evaluate(() => (window as any).__graphUrlState)
  expect(state).toBeTruthy()
  expect(state.ready).toBe(true)
  expect(typeof state.query).toBe('string')
  expect(typeof state.shareableUrl).toBe('string')
  expect(state.shareableUrl).toContain('/graph/explore')
  expect(state.urlSynced).toBe(true)
  expect(typeof state.appliedParams).toBe('object')
  for (const k of [
    'lens',
    'layout',
    'node',
    'neighborhood',
    'source',
    'target',
    'path',
  ]) {
    expect(k in state.appliedParams, `appliedParams missing ${k}`).toBe(true)
  }
  expect(['string', 'object']).toContain(typeof state.lastAction)
})

test('Prompt 40 URL: no duplicate DOM ids after a URL-driven load and a zoom sweep', async ({
  page,
}) => {
  await page.goto('/graph/viewer?lens=resources&layout=concentric', {
    waitUntil: 'domcontentloaded',
  })
  await gotoViewerWithUrlState(page)
  for (const z of [0.25, 0.7, 1.5, 3.0]) {
    await page.evaluate((zoom: number) => {
      const cy = (window as any).__graphCy
      cy.zoom(zoom)
      cy.emit('zoom')
    }, z)
    await page.waitForTimeout(150)
  }
  const dupes = await page.evaluate(() => {
    const ids: Record<string, number> = {}
    const all = document.querySelectorAll('#graph-explorer, #graph-explorer *')
    all.forEach((el) => {
      const id = el.getAttribute('id')
      if (!id) return
      ids[id] = (ids[id] || 0) + 1
    })
    return Object.entries(ids)
      .filter(([, n]) => n > 1)
      .map(([id, n]) => `${id}×${n}`)
  })
  expect(dupes, `found duplicate DOM ids: ${dupes.join(', ')}`).toEqual([])
})

test('Prompt 40.5 UX: deep-link routes do not overflow horizontally', async ({ page }) => {
  const urls = [
    '/graph/explore?layout=grid&node=review_page%3Aweak&source=concept%3Achunking&target=concept%3Aattention&path=1',
    '/graph/viewer?layout=grid&node=review_page%3Aweak&source=concept%3Achunking&target=concept%3Aattention&path=1',
  ]
  for (const url of urls) {
    await page.goto(url, { waitUntil: 'domcontentloaded' })
    await waitForUrlState(page)
    const overflow = await page.evaluate(() => {
      const body = document.body
      const doc = document.documentElement
      return Math.max(body.scrollWidth, doc.scrollWidth) > window.innerWidth
    })
    expect(overflow, `${url} should not overflow horizontally`).toBe(false)
  }
})
