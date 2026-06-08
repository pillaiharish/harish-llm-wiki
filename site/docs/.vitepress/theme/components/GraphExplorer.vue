<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed, nextTick } from 'vue'
import type { Ref } from 'vue'

type GraphNode = {
  id: string
  type: string
  label?: string
  slug?: string
  metadata?: Record<string, unknown>
}

type GraphEdge = {
  id: string
  type: string
  source: string
  target: string
  metadata?: Record<string, unknown>
}

type GraphData = {
  schema_version?: string
  generated_at?: string
  nodes: GraphNode[]
  edges: GraphEdge[]
  stats?: {
    node_count?: number
    edge_count?: number
    node_type_counts?: Record<string, number>
    edge_type_counts?: Record<string, number>
  }
}

type NeighborItem = {
  edge: GraphEdge
  neighbor: GraphNode | null
  direction: 'out' | 'in'
}

const TOP_N_DEFAULT = 50

const FIT_PADDING = 40

const DEFAULT_ZOOM = 1

const LABEL_FULL_ZOOM = 1.2
const LABEL_HUB_ZOOM = 0.6
const HUB_DEGREE_THRESHOLD = 8

// Semantic-zoom tiers. Below the LOW threshold, nodes shrink to
// ~11px and almost all labels are hidden (only selected / hovered /
// closed-neighbourhood and very high-degree hubs stay readable).
// Above the HIGH threshold, all labels are shown and the node
// size is bumped to ~24px but font-size is capped so labels do
// not grow endlessly with zoom.
const ZOOM_TIER_LOW_MAX = 0.5
const ZOOM_TIER_HIGH_MIN = 1.2

const HUB_DEGREE_THRESHOLD_LOW_ZOOM = 25

type SemanticTier = 'low' | 'medium' | 'high'

interface SemanticTierSpec {
  nodeSize: number
  hubNodeSize: number
  fontSize: number
  hubFontSize: number
  selectedFontSize: number
}

const SEMANTIC_TIER_SPECS: Record<SemanticTier, SemanticTierSpec> = {
  low: {
    nodeSize: 11,
    hubNodeSize: 14,
    fontSize: 0,
    hubFontSize: 8,
    selectedFontSize: 9,
  },
  medium: {
    nodeSize: 18,
    hubNodeSize: 22,
    fontSize: 8,
    hubFontSize: 9,
    selectedFontSize: 10,
  },
  high: {
    nodeSize: 24,
    hubNodeSize: 28,
    fontSize: 9,
    hubFontSize: 10,
    selectedFontSize: 11,
  },
}

const dataState = ref<'loading' | 'ready' | 'error'>('loading')
const errorMessage = ref<string | null>(null)
const graph = ref<GraphData | null>(null)
const searchTerm = ref('')
const showAll = ref(false)
const selectedNodeId = ref<string | null>(null)
const selectedEdgeId = ref<string | null>(null)
const currentZoom = ref<number>(DEFAULT_ZOOM)
const currentHoverId = ref<string | null>(null)
const currentTier = ref<SemanticTier>('medium')

const nodeTypeFilter = ref<Set<string>>(new Set())
const edgeTypeFilter = ref<Set<string>>(new Set())

const canvasRef = ref<HTMLDivElement | null>(null)
let cy: any = null
let cytoscapeMod: any = null
let resizeObserver: ResizeObserver | null = null
let resizeDebounce: ReturnType<typeof setTimeout> | null = null
let lastNodeIdSet: string = ''

const allNodeTypes = computed<string[]>(() => {
  if (!graph.value) return []
  const set = new Set<string>()
  for (const n of graph.value.nodes) {
    if (n && n.type) set.add(n.type)
  }
  return Array.from(set).sort()
})

const allEdgeTypes = computed<string[]>(() => {
  if (!graph.value) return []
  const set = new Set<string>()
  for (const e of graph.value.edges) {
    if (e && e.type) set.add(e.type)
  }
  return Array.from(set).sort()
})

function updateLiveStatsLine() {
  if (typeof document === 'undefined') return
  const line = document.getElementById('graph-live-stats-line')
  const wrap = document.getElementById('graph-live-stats')
  if (!line || !wrap) return
  if (dataState.value === 'ready' && graph.value) {
    const stats = graph.value.stats || {}
    const nc =
      typeof stats.node_count === 'number' ? stats.node_count : graph.value.nodes.length
    const ec =
      typeof stats.edge_count === 'number' ? stats.edge_count : graph.value.edges.length
    line.textContent = `Loaded graph: ${nc} nodes, ${ec} edges.`
    wrap.setAttribute('data-state', 'ready')
  } else if (dataState.value === 'error') {
    line.textContent = `Error: failed to load graph (${errorMessage.value || 'unknown'}).`
    wrap.setAttribute('data-state', 'error')
  } else {
    line.textContent = 'Loading graph data…'
    wrap.setAttribute('data-state', 'loading')
  }
}

function nodeById(id: string | null): GraphNode | null {
  if (!id || !graph.value) return null
  return graph.value.nodes.find((n) => n.id === id) || null
}

function edgeById(id: string | null): GraphEdge | null {
  if (!id || !graph.value) return null
  return graph.value.edges.find((e) => e.id === id) || null
}

function nodeRoute(n: GraphNode | null): string | null {
  if (!n) return null
  if (n.type === 'resource') {
    const safe = String(n.slug || '').replace(/[^a-zA-Z0-9_-]/g, '_')
    return `/resources/${safe}`
  }
  if (n.type === 'topic') return `/topics/${n.slug}`
  if (n.type === 'concept') return `/concepts/${n.slug}`
  if (n.type === 'tag') return `/tags/#${n.slug}`
  if (n.type === 'learn_chapter') return `/learn/${n.slug}`
  if (n.type === 'review_page') return `/review/`
  return null
}

function degree(nodeId: string): number {
  if (!graph.value) return 0
  let d = 0
  for (const e of graph.value.edges) {
    if (!edgeTypeFilter.value.has(e.type)) continue
    if (e.source === nodeId || e.target === nodeId) d += 1
  }
  return d
}

function topNodeIds(n: number): string[] {
  if (!graph.value) return []
  const arr = graph.value.nodes.map((nd) => ({ id: nd.id, d: degree(nd.id) }))
  arr.sort((a, b) => b.d - a.d || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
  return arr.slice(0, n).map((x) => x.id)
}

function visibleNodeIds(): string[] {
  if (!graph.value) return []
  const base = showAll.value
    ? graph.value.nodes.map((n) => n.id)
    : topNodeIds(TOP_N_DEFAULT)
  const q = searchTerm.value.trim().toLowerCase()
  return base.filter((id) => {
    const n = nodeById(id)
    if (!n) return false
    if (!nodeTypeFilter.value.has(n.type)) return false
    if (!q) return true
    const hay = `${n.label || ''} ${n.slug || ''} ${n.id || ''}`.toLowerCase()
    return hay.indexOf(q) !== -1
  })
}

function neighborsOf(nodeId: string | null): NeighborItem[] {
  if (!nodeId || !graph.value) return []
  const out: NeighborItem[] = []
  for (const e of graph.value.edges) {
    if (!edgeTypeFilter.value.has(e.type)) continue
    if (e.source === nodeId) {
      out.push({ edge: e, neighbor: nodeById(e.target), direction: 'out' })
    } else if (e.target === nodeId) {
      out.push({ edge: e, neighbor: nodeById(e.source), direction: 'in' })
    }
  }
  return out
}

function cyElements() {
  if (!graph.value) return []
  const visibleIds = new Set(visibleNodeIds())
  const visibleEdges: GraphEdge[] = graph.value.edges.filter(
    (e) =>
      edgeTypeFilter.value.has(e.type) &&
      visibleIds.has(e.source) &&
      visibleIds.has(e.target)
  )
  const visibleEdgeIds = new Set(visibleEdges.map((e) => e.id))
  const elements: any[] = []
  for (const n of graph.value.nodes) {
    if (!visibleIds.has(n.id)) continue
    const deg = degree(n.id)
    elements.push({
      group: 'nodes',
      data: {
        id: n.id,
        label: n.label || n.id,
        type: n.type,
        slug: n.slug || '',
        degree: deg,
        metadata: n.metadata || {},
      },
    })
  }
  for (const e of graph.value.edges) {
    if (!visibleEdgeIds.has(e.id)) continue
    elements.push({
      group: 'edges',
      data: {
        id: e.id,
        source: e.source,
        target: e.target,
        type: e.type,
        metadata: e.metadata || {},
      },
    })
  }
  return elements
}

function makeStyle() {
  const tier = currentTier.value
  const spec = SEMANTIC_TIER_SPECS[tier]
  return [
    {
      selector: 'node',
      style: {
        'background-color': '#888',
        // Show the data(label) by default at the node level so
        // that the base stylesheet actually renders labels. The
        // hide-labels / hide-on-low-tier behaviour is driven by
        // a class toggled in applyNodeRoleClasses() instead of
        // by an empty literal in the base style — this avoids
        // the "selected node loses its label because the base
        // rule wipes it" failure mode.
        label: 'data(label)',
        color: '#222',
        'font-size': spec.fontSize,
        'text-valign': 'bottom',
        'text-halign': 'center',
        'text-wrap': 'wrap',
        'text-max-width': 80,
        'text-margin-y': 4,
        'border-width': 1,
        'border-color': '#222',
        width: spec.nodeSize,
        height: spec.nodeSize,
        'min-zoomed-font-size': 100,
      },
    },
    {
      selector: 'node[type = "resource"]',
      style: {
        'background-color': '#e74c3c',
        shape: 'round-rectangle',
      },
    },
    {
      selector: 'node[type = "topic"]',
      style: {
        'background-color': '#3498db',
        shape: 'ellipse',
      },
    },
    {
      selector: 'node[type = "concept"]',
      style: {
        'background-color': '#9b59b6',
        shape: 'triangle',
      },
    },
    {
      selector: 'node[type = "tag"]',
      style: {
        'background-color': '#f1c40f',
        shape: 'round-pentagon',
      },
    },
    {
      selector: 'node[type = "learn_chapter"]',
      style: {
        'background-color': '#2ecc71',
        shape: 'round-octagon',
      },
    },
    {
      selector: 'node[type = "review_page"]',
      style: {
        'background-color': '#1abc9c',
        shape: 'round-hexagon',
      },
    },
    {
      selector: 'edge',
      style: {
        width: 1,
        'line-color': '#bbb',
        'curve-style': 'bezier',
        'target-arrow-shape': 'triangle',
        'target-arrow-color': '#bbb',
        opacity: 0.6,
      },
    },
    {
      selector: 'edge[type = "topic_related_to_topic"]',
      style: { 'line-style': 'dashed' },
    },
    {
      // Hub-sized nodes keep their label visible regardless of
      // the per-tier font-size. The [degree >= ...] attribute
      // selector complements the .hub class so nodes that cross
      // the hub threshold at the new tier also pick up the
      // hub-sized label.
      selector: 'node[degree >= 8]',
      style: {
        'font-size': spec.hubFontSize,
        'text-outline-width': 2,
        'text-outline-color': '#fcfcfc',
        'text-outline-opacity': 0.85,
      },
    },
    {
      selector: 'node.hub',
      style: {
        width: spec.hubNodeSize,
        height: spec.hubNodeSize,
        'font-size': spec.hubFontSize,
        'text-outline-width': 2,
        'text-outline-color': '#fcfcfc',
        'text-outline-opacity': 0.9,
      },
    },
    {
      selector: 'edge:selected',
      style: {
        'line-color': '#f1c40f',
        'target-arrow-color': '#f1c40f',
        width: 2.5,
        opacity: 1,
      },
    },
    {
      selector: '.faded',
      style: { opacity: 0.15 },
    },
    {
      // The hide-labels class is the *only* rule that turns a
      // label off. It is intentionally placed BEFORE the
      // :selected / .highlighted / .hovered rules below so that
      // those rules (which appear later in the array) win over
      // hide-labels and the selected/hovered node always shows
      // its label.
      selector: 'node.hide-labels',
      style: { label: '' },
    },
    {
      selector: 'node:selected',
      style: {
        'border-color': '#f1c40f',
        'border-width': 4,
        label: 'data(label)',
        'font-size': spec.selectedFontSize,
        'text-outline-width': 2,
        'text-outline-color': '#fcfcfc',
        'text-outline-opacity': 0.9,
        'z-index': 10,
      },
    },
    {
      selector: '.highlighted',
      style: {
        'border-color': '#e22',
        'border-width': 3,
        'line-color': '#e22',
        'target-arrow-color': '#e22',
        opacity: 1,
        label: 'data(label)',
        'font-size': spec.hubFontSize,
        'text-outline-width': 2,
        'text-outline-color': '#fcfcfc',
        'text-outline-opacity': 0.9,
        'z-index': 9,
      },
    },
    {
      selector: 'node.hovered, .hovered',
      style: {
        'border-color': '#09c',
        'border-width': 3,
        label: 'data(label)',
        'font-size': spec.selectedFontSize,
        'text-outline-width': 2,
        'text-outline-color': '#fcfcfc',
        'text-outline-opacity': 0.9,
        'z-index': 11,
      },
    },
  ]
}

function coseLayoutOptions() {
  // Tuned for ~65 nodes / ~1069 edges (the default knowledge
  // graph). The previous values (nodeRepulsion=12000,
  // idealEdgeLength=80) still produced a visibly busy centre
  // because the average degree is ~16. We bump both knobs and
  // raise the iteration count so the dense centre has more
  // breathing room. Determinism is preserved via randomize:
  // false and fixed numIter / coolingFactor so re-runs produce
  // the same positions for the same element set.
  return {
    name: 'cose',
    randomize: false,
    fit: false,
    animate: false,
    padding: FIT_PADDING,
    nodeRepulsion: () => 80000,
    idealEdgeLength: () => 140,
    edgeElasticity: () => 100,
    nodeOverlap: 24,
    componentSpacing: 120,
    gravity: 0.25,
    numIter: 2500,
    initialTemp: 2000,
    coolingFactor: 0.97,
    minTemp: 1.0,
  }
}

function pickSemanticTier(z: number): SemanticTier {
  if (z <= ZOOM_TIER_LOW_MAX) return 'low'
  if (z >= ZOOM_TIER_HIGH_MIN) return 'high'
  return 'medium'
}

function hubDegreeThreshold(tier: SemanticTier): number {
  if (tier === 'low') return HUB_DEGREE_THRESHOLD_LOW_ZOOM
  return HUB_DEGREE_THRESHOLD
}

function applyNodeRoleClasses() {
  if (!cy) return
  const tier = currentTier.value
  const selectedId = selectedNodeId.value
  const hoverId = currentHoverId.value
  const hubThresh = hubDegreeThreshold(tier)
  let neighborhood: any = null
  if (selectedId) {
    const sel = cy.getElementById(selectedId)
    if (sel && sel.length) {
      neighborhood = sel.closedNeighborhood()
    }
  }
  cy.nodes().forEach((n: any) => {
    const id = n.id() as string
    const isSelected = id === selectedId
    const inNeighborhood = !!neighborhood && neighborhood.contains(n)
    const isHover = id === hoverId
    const isHub = (n.data('degree') || 0) >= hubThresh
    if (isHub) n.addClass('hub')
    else n.removeClass('hub')
    // Always track the "hovered" class so the matching style
    // rule (which is intentionally placed AFTER the
    // hide-labels rule) wins and the hovered node's label
    // stays visible.
    if (isHover) n.addClass('hovered')
    else n.removeClass('hovered')
    // Label visibility:
    //   high tier: every node shows its label
    //   medium tier: selected / hovered / closed-neighbourhood / hub
    //   low tier: selected / hovered / closed-neighbourhood / very-high-degree hub
    //
    // The selected, hovered, and closed-neighbourhood checks
    // are deliberately performed *first* and unconditionally
    // across all tiers so that selected/hover/neighbour nodes
    // are guaranteed to lose the hide-labels class on every
    // semantic-zoom update — the previous version had a tier
    // branch ordering bug that could leave the class on a
    // newly-selected node.
    if (isSelected || inNeighborhood || isHover) {
      n.removeClass('hide-labels')
    } else if (tier === 'high') {
      n.removeClass('hide-labels')
    } else if (tier === 'medium' && isHub) {
      n.removeClass('hide-labels')
    } else {
      n.addClass('hide-labels')
    }
  })
  // Maintain a legacy alias class for back-compat with the
  // Prompt 35.1 LABEL_FULL_ZOOM path inside
  // applyLabelVisibility(). The class is purely cosmetic — the
  // stylesheet only references .hide-labels.
  if (tier === 'high') {
    cy.elements().removeClass('hide-labels').addClass('show-labels')
  } else {
    cy.elements().removeClass('show-labels')
  }
}

function updateLabelDebug() {
  if (typeof window === 'undefined' || !cy) return
  // The real debug helper lives on window.__graphLabelDebug and
  // computes its snapshot lazily when called. We just touch
  // window.__graphLabelDebugLastSnapshot here so the snapshot
  // is also available to background tooling without invoking
  // the helper.
  const fn = (window as any).__graphLabelDebug
  if (typeof fn !== 'function') return
  try {
    const snap = fn()
    ;(window as any).__graphLabelDebugLastSnapshot = snap
  } catch {
    // Swallow — the debug helper is best-effort.
  }
}

function applySemanticZoom() {
  if (!cy) return
  // Re-read the source-of-truth zoom directly from cytoscape so we
  // can never drift from a stale ref. We deliberately do NOT call
  // cy.fit() here — that would steal user-controlled wheel zoom.
  const z = cy.zoom()
  currentZoom.value = z
  const tier = pickSemanticTier(z)
  currentTier.value = tier
  // Push the tier-derived sizes/fonts to the stylesheet so font-size
  // and node size stay controlled as the user zooms in and out.
  // We rebuild the stylesheet from JSON via the live Style
  // instance's fromJson() method, which is supported by every
  // cytoscape 3.x version we target.
  try {
    const style = cy.style()
    if (style && typeof (style as any).fromJson === 'function') {
      ;(style as any).fromJson(makeStyle())
      if (typeof (style as any).update === 'function') {
        ;(style as any).update()
      }
    } else {
      cy.style(makeStyle() as any)
    }
  } catch {
    // Last-resort fallback: rebuild via the cy.style() setter.
    try {
      cy.style(makeStyle() as any)
    } catch {
      // Ignore — the renderer is in an inconsistent state but
      // we still want the role-class pass to run below.
    }
  }
  applyNodeRoleClasses()
  updateLabelDebug()
}

// Backwards-compatible alias for callers that previously updated
// only label visibility. Now a thin wrapper that also re-applies
// the hub class so nodes that newly cross the hub threshold are
// picked up.
function applyLabelVisibility() {
  if (!cy) return
  // Keep the LABEL_FULL_ZOOM legacy semantics: at the top tier we
  // reveal every label. This is a strict subset of
  // applyNodeRoleClasses()'s high-tier branch, but kept here for
  // existing tests / readability.
  const z = currentZoom.value
  if (z >= LABEL_FULL_ZOOM) {
    cy.elements().removeClass('hide-labels').addClass('show-labels')
  } else {
    cy.elements().removeClass('show-labels')
  }
  applyNodeRoleClasses()
}

function buildCy() {
  if (!canvasRef.value || !cytoscapeMod) return
  cy = cytoscapeMod({
    container: canvasRef.value,
    elements: cyElements(),
    style: makeStyle(),
    layout: coseLayoutOptions(),
    wheelSensitivity: 0.2,
    minZoom: 0.1,
    maxZoom: 4,
  })
  cy.on('tap', 'node', (evt: any) => {
    const n = evt.target
    const id = n.id() as string
    selectedNodeId.value = id
    selectedEdgeId.value = null
    highlightSelection()
    applySemanticZoom()
  })
  cy.on('tap', 'edge', (evt: any) => {
    const e = evt.target
    const id = e.id() as string
    selectedEdgeId.value = id
    selectedNodeId.value = null
    highlightSelection()
    applySemanticZoom()
  })
  cy.on('tap', (evt: any) => {
    if (evt.target === cy) {
      selectedNodeId.value = null
      selectedEdgeId.value = null
      highlightSelection()
      applySemanticZoom()
    }
  })
  cy.on('mouseover', 'node', (evt: any) => {
    currentHoverId.value = evt.target.id() as string
    applySemanticZoom()
  })
  cy.on('mouseout', 'node', () => {
    currentHoverId.value = null
    applySemanticZoom()
  })
  cy.on('zoom', () => {
    if (cy) {
      applySemanticZoom()
    }
  })
  if (typeof window !== 'undefined') {
    ;(window as any).__graphCy = cy
    // Prompt 35.3: expose a small debug helper on the window so
    // an operator can inspect label visibility without having to
    // re-run the test suite. The helper returns a snapshot of
    // {zoom, tier, counts: {visible, hidden, total}} based on
    // the live stylesheet and node states.
    ;(window as any).__graphLabelDebug = function () {
      if (!cy) {
        return { ready: false }
      }
      const visible: string[] = []
      const hidden: string[] = []
      cy.nodes().forEach((n: any) => {
        const lbl = n.style('label') || ''
        if (lbl && lbl.length > 0) visible.push(n.id() as string)
        else hidden.push(n.id() as string)
      })
      return {
        ready: true,
        zoom: currentZoom.value,
        tier: currentTier.value,
        counts: {
          visible: visible.length,
          hidden: hidden.length,
          total: visible.length + hidden.length,
        },
        visibleIds: visible.slice(0, 50),
        hiddenSample: hidden.slice(0, 50),
        selectedNodeId: selectedNodeId.value,
        hoverId: currentHoverId.value,
      }
    }
  }
  lastNodeIdSet = visibleNodeIds().sort().join('|')
  currentZoom.value = cy.zoom()
  cy.fit(undefined, FIT_PADDING)
  applySemanticZoom()
  setupResizeObserver()
}

function highlightSelection() {
  if (!cy) return
  cy.elements().removeClass('faded highlighted')
  const nodeId = selectedNodeId.value
  const edgeId = selectedEdgeId.value
  if (nodeId) {
    const n = cy.getElementById(nodeId)
    if (n && n.length) {
      const neighborhood = n.closedNeighborhood()
      cy.elements().addClass('faded')
      neighborhood.removeClass('faded').addClass('highlighted')
    }
  } else if (edgeId) {
    const e = cy.getElementById(edgeId)
    if (e && e.length) {
      cy.elements().addClass('faded')
      e.removeClass('faded').addClass('highlighted')
      e.source().removeClass('faded').addClass('highlighted')
      e.target().removeClass('faded').addClass('highlighted')
    }
  }
}

function nodeSetChanged(): boolean {
  const cur = visibleNodeIds().sort().join('|')
  return cur !== lastNodeIdSet
}

function reRenderCy() {
  if (!cy) return
  const els = cyElements()
  const changed = nodeSetChanged()
  cy.elements().remove()
  cy.add(els)
  if (changed) {
    cy.layout(coseLayoutOptions()).run()
    lastNodeIdSet = visibleNodeIds().sort().join('|')
  }
  cy.fit(undefined, FIT_PADDING)
  currentZoom.value = cy.zoom()
  highlightSelection()
  applySemanticZoom()
}

function fitGraph() {
  if (!cy) return
  cy.fit(undefined, FIT_PADDING)
  currentZoom.value = cy.zoom()
  applySemanticZoom()
}

function resetZoom() {
  if (!cy) return
  cy.zoom(DEFAULT_ZOOM)
  cy.center()
  currentZoom.value = cy.zoom()
  applySemanticZoom()
}

function zoomIn() {
  if (!cy) return
  const z = cy.zoom()
  const next = Math.min(cy.maxZoom(), z * 1.25)
  cy.zoom(next)
  currentZoom.value = cy.zoom()
  applySemanticZoom()
}

function zoomOut() {
  if (!cy) return
  const z = cy.zoom()
  const next = Math.max(cy.minZoom(), z * 0.8)
  cy.zoom(next)
  currentZoom.value = cy.zoom()
  applySemanticZoom()
}

function toggleShowAll() {
  showAll.value = !showAll.value
  reRenderCy()
}

function onSearchInput(ev: Event) {
  const target = ev.target as HTMLInputElement
  searchTerm.value = target.value
  reRenderCy()
}

function onNodeTypeCheckbox(ev: Event) {
  const target = ev.target as HTMLInputElement
  const t = target.value
  if (target.checked) nodeTypeFilter.value.add(t)
  else nodeTypeFilter.value.delete(t)
  reRenderCy()
}

function onEdgeTypeCheckbox(ev: Event) {
  const target = ev.target as HTMLInputElement
  const t = target.value
  if (target.checked) edgeTypeFilter.value.add(t)
  else edgeTypeFilter.value.delete(t)
  reRenderCy()
}

function pickNeighbor(id: string) {
  selectedNodeId.value = id
  selectedEdgeId.value = null
  highlightSelection()
  applySemanticZoom()
}

function setupResizeObserver() {
  if (typeof ResizeObserver === 'undefined') return
  if (!canvasRef.value) return
  if (resizeObserver) {
    try {
      resizeObserver.disconnect()
    } catch {
      // ignore
    }
    resizeObserver = null
  }
  let lastW = canvasRef.value.clientWidth
  let lastH = canvasRef.value.clientHeight
  resizeObserver = new ResizeObserver((entries: ResizeObserverEntry[]) => {
    const e = entries && entries[0]
    if (!e) return
    const cr = e.contentRect
    const w = Math.round(cr.width)
    const h = Math.round(cr.height)
    // Only react to real size changes (>= 4px delta). Cytoscape's
    // internal layout recomputes can fire spurious ResizeObserver
    // ticks with sub-pixel deltas; ignore those.
    if (Math.abs(w - lastW) < 4 && Math.abs(h - lastH) < 4) return
    lastW = w
    lastH = h
    if (resizeDebounce) clearTimeout(resizeDebounce)
    resizeDebounce = setTimeout(() => {
      if (!cy) return
      cy.resize()
      cy.fit(undefined, FIT_PADDING)
      currentZoom.value = cy.zoom()
      applySemanticZoom()
    }, 80)
  })
  resizeObserver.observe(canvasRef.value)
}

function teardownResizeObserver() {
  if (resizeObserver) {
    try {
      resizeObserver.disconnect()
    } catch {
      // ignore
    }
    resizeObserver = null
  }
  if (resizeDebounce) {
    clearTimeout(resizeDebounce)
    resizeDebounce = null
  }
}

async function loadGraph() {
  try {
    const base = (import.meta.env.BASE_URL as string) || '/'
    const url = base.replace(/\/$/, '/') + 'graph/knowledge_graph.json'
    const resp = await fetch(url)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = (await resp.json()) as GraphData
    if (!Array.isArray(data.nodes) || !Array.isArray(data.edges)) {
      throw new Error('Malformed graph JSON: nodes/edges missing')
    }
    graph.value = data
    const nodeTypes = new Set<string>()
    for (const n of data.nodes) if (n && n.type) nodeTypes.add(n.type)
    const edgeTypes = new Set<string>()
    for (const e of data.edges) if (e && e.type) edgeTypes.add(e.type)
    nodeTypeFilter.value = nodeTypes
    edgeTypeFilter.value = edgeTypes
    dataState.value = 'ready'
    errorMessage.value = null
    updateLiveStatsLine()
    await nextTick()
    buildCy()
  } catch (e: any) {
    dataState.value = 'error'
    errorMessage.value = (e && e.message) || String(e)
    updateLiveStatsLine()
  }
}

onMounted(async () => {
  if (typeof window === 'undefined') return
  if (import.meta.env.SSR) return
  if (!cytoscapeMod) {
    cytoscapeMod = (await import('cytoscape')).default || (await import('cytoscape'))
  }
  await loadGraph()
})

onBeforeUnmount(() => {
  teardownResizeObserver()
  if (cy) {
    cy.destroy()
    cy = null
  }
  if (typeof window !== 'undefined') {
    delete (window as any).__graphCy
    delete (window as any).__graphLabelDebug
  }
})

const visibleNodeList = computed<GraphNode[]>(() => {
  return visibleNodeIds()
    .map((id) => nodeById(id))
    .filter((n): n is GraphNode => !!n)
})

const selectedNode = computed<GraphNode | null>(() => nodeById(selectedNodeId.value))
const selectedEdge = computed<GraphEdge | null>(() => edgeById(selectedEdgeId.value))
const neighborList = computed<NeighborItem[]>(() => neighborsOf(selectedNodeId.value))
</script>

<template>
  <div class="graph-explorer">
    <div id="graph-controls" class="ge-controls">
      <label for="graph-search" class="ge-label">Search nodes:</label>
      <input
        id="graph-search"
        type="search"
        placeholder="label, slug, or id"
        :value="searchTerm"
        @input="onSearchInput"
      />
      <button id="graph-zoom-in" type="button" title="Zoom in" @click="zoomIn">+ Zoom in</button>
      <button id="graph-zoom-out" type="button" title="Zoom out" @click="zoomOut">− Zoom out</button>
      <button id="graph-fit" type="button" title="Fit graph to viewport" @click="fitGraph">Fit graph</button>
      <button id="graph-reset-zoom" type="button" title="Reset zoom to 1×" @click="resetZoom">Reset zoom</button>
      <button
        id="graph-show-all"
        type="button"
        :data-state="showAll ? 'all' : 'top'"
        @click="toggleShowAll"
      >{{ showAll ? 'Show top' : 'Show all' }}</button>
      <fieldset id="graph-filter-node-type">
        <legend>Node types</legend>
        <label v-for="t in allNodeTypes" :key="t" class="ge-checkbox">
          <input
            type="checkbox"
            :id="`graph-filter-node-type-${t}`"
            :value="t"
            :checked="nodeTypeFilter.has(t)"
            @change="onNodeTypeCheckbox"
          />
          {{ t }}
        </label>
      </fieldset>
      <fieldset id="graph-filter-edge-type">
        <legend>Edge types</legend>
        <label v-for="t in allEdgeTypes" :key="t" class="ge-checkbox">
          <input
            type="checkbox"
            :id="`graph-filter-edge-type-${t}`"
            :value="t"
            :checked="edgeTypeFilter.has(t)"
            @change="onEdgeTypeCheckbox"
          />
          {{ t }}
        </label>
      </fieldset>
    </div>

    <div id="graph-canvas" ref="canvasRef" class="ge-canvas"></div>

    <div id="graph-list-pane" class="ge-list-pane">
      <h3>Nodes</h3>
      <div id="graph-node-list" :data-count="visibleNodeList.length">
        <p v-if="!visibleNodeList.length"><em>No matching nodes.</em></p>
        <div
          v-for="n in visibleNodeList.slice(0, 200)"
          :key="n.id"
          class="gn-row"
          :class="{ 'gn-row-selected': selectedNodeId === n.id }"
          :data-node-id="n.id"
        >
          <button
            type="button"
            class="gn-pick"
            :data-node-id="n.id"
            @click="pickNeighbor(n.id)"
          >
            <span class="gn-type">{{ n.type }}</span>
            <span class="gn-label">{{ n.label || n.id }}</span>
          </button>
        </div>
      </div>
    </div>

    <div id="graph-details-pane" class="ge-details-pane">
      <h3>Details</h3>
      <div id="graph-details">
        <p v-if="!selectedNode && !selectedEdge"><em>Select a node or edge to see its details.</em></p>
        <div v-else-if="selectedNode">
          <h4>{{ selectedNode.label || selectedNode.id }}</h4>
          <p>
            <strong>ID:</strong> <code>{{ selectedNode.id }}</code><br />
            <strong>Type:</strong> {{ selectedNode.type }}<br />
            <strong>Slug:</strong> {{ selectedNode.slug || '' }}
          </p>
          <p v-if="nodeRoute(selectedNode)">
            Open in wiki:
            <a :href="nodeRoute(selectedNode) || '#'">{{ nodeRoute(selectedNode) }}</a>
          </p>
          <h5>Metadata</h5>
          <table v-if="Object.keys(selectedNode.metadata || {}).length">
            <tr v-for="(v, k) in (selectedNode.metadata || {})" :key="String(k)">
              <td>{{ String(k) }}</td>
              <td>{{ String(v) }}</td>
            </tr>
          </table>
          <p v-else><em>No metadata.</em></p>
        </div>
        <div v-else-if="selectedEdge">
          <h4>Edge</h4>
          <p>
            <strong>ID:</strong> <code>{{ selectedEdge.id }}</code><br />
            <strong>Type:</strong> {{ selectedEdge.type }}<br />
            <strong>From:</strong> {{ selectedEdge.source }}<br />
            <strong>To:</strong> {{ selectedEdge.target }}
          </p>
          <h5>Metadata</h5>
          <table v-if="Object.keys(selectedEdge.metadata || {}).length">
            <tr v-for="(v, k) in (selectedEdge.metadata || {})" :key="String(k)">
              <td>{{ String(k) }}</td>
              <td>{{ String(v) }}</td>
            </tr>
          </table>
          <p v-else><em>No metadata.</em></p>
        </div>
      </div>

      <h3>Neighbors</h3>
      <div id="graph-neighbors">
        <p v-if="!selectedNode"><em>No node selected.</em></p>
        <p v-else-if="!neighborList.length"><em>No neighbors.</em></p>
        <ul v-else>
          <li v-for="(item, i) in neighborList.slice(0, 200)" :key="i">
            {{ item.direction }}:
            <button
              type="button"
              class="gn-pick"
              :data-node-id="item.neighbor ? item.neighbor.id : ''"
              @click="item.neighbor && pickNeighbor(item.neighbor.id)"
            >{{ item.neighbor ? (item.neighbor.label || item.neighbor.id) : '?' }}</button>
            <small>({{ item.edge.type }})</small>
          </li>
        </ul>
      </div>

      <h3>Edges</h3>
      <div id="graph-edges">
        <p v-if="!selectedNode"><em>No node selected.</em></p>
        <p v-else-if="!neighborList.length"><em>No edges.</em></p>
        <ul v-else>
          <li v-for="(item, i) in neighborList.slice(0, 200)" :key="`e-${i}`">
            <code>{{ item.edge.id }}</code>
            <small v-if="Object.keys(item.edge.metadata || {}).length">
              <span v-for="(v, k) in (item.edge.metadata || {})" :key="String(k)">
                {{ String(k) }}={{ String(v) }}&nbsp;
              </span>
            </small>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<style scoped>
.graph-explorer {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
}
.ge-controls {
  flex: 1 1 100%;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  padding: 0.5rem;
  border: 1px solid var(--vp-c-divider, #ddd);
  border-radius: 6px;
  background: var(--vp-c-bg-soft, #fafafa);
}
.ge-label {
  font-weight: 600;
}
.ge-controls input[type='search'] {
  padding: 0.25rem 0.5rem;
  border: 1px solid var(--vp-c-divider, #ccc);
  border-radius: 4px;
  min-width: 240px;
}
.ge-controls button {
  padding: 0.3rem 0.7rem;
  border: 1px solid var(--vp-c-divider, #ccc);
  border-radius: 4px;
  background: var(--vp-c-bg, #fff);
  cursor: pointer;
}
.ge-controls fieldset {
  border: 1px solid var(--vp-c-divider, #ccc);
  border-radius: 4px;
  padding: 0.25rem 0.5rem;
  margin: 0;
}
.ge-controls legend {
  font-weight: 600;
  padding: 0 0.25rem;
}
.ge-checkbox {
  margin-right: 0.75rem;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}
.ge-canvas {
  flex: 1 1 100%;
  height: 640px;
  min-height: 600px;
  border: 2px solid var(--vp-c-divider, #ccc);
  background: #fcfcfc;
  border-radius: 6px;
  position: relative;
  overflow: hidden;
}
.ge-list-pane,
.ge-details-pane {
  flex: 1 1 320px;
  border: 1px solid var(--vp-c-divider, #ddd);
  border-radius: 6px;
  padding: 0.5rem 0.75rem;
  background: var(--vp-c-bg-soft, #fafafa);
}
.gn-row {
  margin-bottom: 0.15rem;
}
.gn-row-selected button {
  font-weight: 700;
}
.gn-pick {
  background: transparent;
  border: 0;
  cursor: pointer;
  text-align: left;
  padding: 0.15rem 0.25rem;
  width: 100%;
  font: inherit;
}
.gn-pick:hover {
  background: var(--vp-c-bg, #fff);
  border-radius: 3px;
}
.gn-type {
  font-size: 0.7rem;
  padding: 0 0.3rem;
  border-radius: 3px;
  background: var(--vp-c-default-soft, #eef);
  margin-right: 0.3rem;
}
</style>
