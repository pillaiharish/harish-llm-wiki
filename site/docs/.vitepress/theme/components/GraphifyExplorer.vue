<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { withBase } from 'vitepress'
import 'vis-network/styles/vis-network.css'

type RawNode = {
  id: string
  type?: string
  label?: string
  title?: string
  slug?: string
  path?: string
  community?: string
  metadata?: Record<string, unknown>
}

type RawEdge = {
  id?: string
  type?: string
  relationship?: string
  source?: string
  target?: string
  from?: string
  to?: string
  score?: number
  weight?: number
  metadata?: Record<string, unknown>
}

type NormalizedNode = {
  id: string
  label: string
  type: string
  slug: string
  path: string
  degree: number
  community: string
  metadata: Record<string, unknown>
  raw: RawNode
}

type NormalizedEdge = {
  id: string
  from: string
  to: string
  type: string
  value: number
  raw: RawEdge
}

type NeighborItem = {
  id: string
  label: string
  type: string
}

type GraphifyState = 'loading' | 'ready' | 'error'

const rootRef = ref<HTMLElement | null>(null)
const networkRef = ref<HTMLElement | null>(null)
const state = ref<GraphifyState>('loading')
const errorMessage = ref('')
const searchQuery = ref('')
const noSearchResult = ref(false)
const selectedNodeId = ref('')
const searchMatchIds = ref<string[]>([])
const typeFilters = ref<string[]>([])
const communityFilters = ref<string[]>([])
const isFullscreen = ref(false)

const rawNodes = ref<RawNode[]>([])
const rawEdges = ref<RawEdge[]>([])
const normalizedNodes = ref<NormalizedNode[]>([])
const normalizedEdges = ref<NormalizedEdge[]>([])

let NetworkCtor: any = null
let DataSetCtor: any = null
let DataViewCtor: any = null
let network: any = null
let nodeDataSet: any = null
let edgeDataSet: any = null
let nodeView: any = null
let edgeView: any = null

const GROUP_STYLES: Record<string, any> = {
  resource: {
    shape: 'dot',
    color: { background: '#4a90d9', border: '#93c5fd' },
  },
  concept: {
    shape: 'diamond',
    color: { background: '#e67e22', border: '#fdba74' },
  },
  topic: {
    shape: 'hexagon',
    color: { background: '#27ae60', border: '#86efac' },
  },
  review_page: {
    shape: 'triangle',
    color: { background: '#e74c3c', border: '#fca5a5' },
  },
  learn_chapter: {
    shape: 'star',
    color: { background: '#9b59b6', border: '#d8b4fe' },
  },
  unknown: {
    shape: 'dot',
    color: { background: '#64748b', border: '#cbd5e1' },
  },
}

const REVIEW_ROUTES: Record<string, string> = {
  weak: '/review/weak-notes',
  fallback: '/review/fallback-notes',
  failed: '/review/failed-notes',
  missing_citations: '/review/missing-citations',
  stale: '/review/stale-notes',
}

const nodeById = computed<Record<string, NormalizedNode>>(() => {
  const out: Record<string, NormalizedNode> = {}
  for (const node of normalizedNodes.value) out[node.id] = node
  return out
})

const selectedNode = computed<NormalizedNode | null>(() => {
  return nodeById.value[selectedNodeId.value] || null
})

const selectedNeighbors = computed<NeighborItem[]>(() => {
  if (!selectedNode.value || !network) return []
  const ids = network.getConnectedNodes(selectedNode.value.id) || []
  return ids
    .map((id: string) => nodeById.value[id])
    .filter((node: NormalizedNode | undefined): node is NormalizedNode => !!node)
    .map((node: NormalizedNode) => ({
      id: node.id,
      label: node.label,
      type: node.type,
    }))
    .sort((a: NeighborItem, b: NeighborItem) => a.label.localeCompare(b.label))
})

const nodeTypes = computed<string[]>(() => {
  return Array.from(new Set(normalizedNodes.value.map((node) => node.type))).sort()
})

const communities = computed<string[]>(() => {
  return Array.from(
    new Set(normalizedNodes.value.map((node) => node.community).filter(Boolean))
  ).sort()
})

const hasCommunityFilters = computed<boolean>(() => communities.value.length > 0)

const visibleNodeIds = computed<Set<string>>(() => {
  const types = new Set(typeFilters.value)
  const communitiesSet = new Set(communityFilters.value)
  const hasCommunities = communities.value.length > 0
  return new Set(
    normalizedNodes.value
      .filter((node) => types.has(node.type))
      .filter((node) => !hasCommunities || communitiesSet.has(node.community))
      .map((node) => node.id)
  )
})

function degreeMapFromEdges(edges: RawEdge[]): Record<string, number> {
  const degree: Record<string, number> = {}
  for (const edge of edges) {
    const from = String(edge.source || edge.from || '')
    const to = String(edge.target || edge.to || '')
    if (from) degree[from] = (degree[from] || 0) + 1
    if (to) degree[to] = (degree[to] || 0) + 1
  }
  return degree
}

function metadataString(value: unknown): string {
  if (value === null || typeof value === 'undefined') return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function slugFromNode(node: NormalizedNode): string {
  const rawSlug = node.slug || metadataString(node.metadata.slug)
  if (rawSlug) return rawSlug
  const parts = node.id.split(':')
  return parts.length > 1 ? parts.slice(1).join(':') : node.id
}

function routeForNode(node: NormalizedNode | null): string | null {
  if (!node) return null
  if (node.path && node.path.startsWith('/')) return node.path
  const slug = slugFromNode(node)
  if (!slug) return null
  switch (node.type) {
    case 'resource':
      return `/resources/${slug}`
    case 'concept':
      return `/concepts/${slug}`
    case 'topic':
      return `/topics/${slug}`
    case 'learn_chapter':
      return `/learn/${slug}`
    case 'review_page':
      return REVIEW_ROUTES[slug] || '/review/'
    default:
      return null
  }
}

function ctaLabelForNode(node: NormalizedNode | null): string {
  if (!node) return 'Open page'
  if (node.type === 'resource') return 'Open resource'
  if (node.type === 'concept') return 'Open concept'
  if (node.type === 'topic') return 'Start learning'
  if (node.type === 'learn_chapter') return 'Continue learning'
  if (node.type === 'review_page') return 'Open review page'
  return 'Open page'
}

const selectedRoute = computed<string | null>(() => routeForNode(selectedNode.value))
const selectedCtaLabel = computed<string>(() => ctaLabelForNode(selectedNode.value))

function normalizeNodes(nodes: RawNode[], degree: Record<string, number>): NormalizedNode[] {
  return nodes
    .filter((node) => node && node.id)
    .map((node) => {
      const metadata = node.metadata || {}
      const type = String(node.type || 'unknown')
      const community = String(node.community || metadataString(metadata.community) || '')
      const slug = String(node.slug || metadataString(metadata.slug) || '')
      const path = String(node.path || metadataString(metadata.path) || '')
      return {
        id: node.id,
        label: String(node.label || node.title || slug || node.id),
        type,
        slug,
        path,
        degree: Math.max(1, degree[node.id] || 0),
        community,
        metadata,
        raw: node,
      }
    })
}

function normalizeEdges(edges: RawEdge[]): NormalizedEdge[] {
  return edges
    .map((edge, index) => {
      const from = String(edge.source || edge.from || '')
      const to = String(edge.target || edge.to || '')
      const type = String(edge.type || edge.relationship || 'related')
      const meta = edge.metadata || {}
      const score = Number(edge.score ?? edge.weight ?? meta.score ?? meta.weight ?? 1)
      return {
        id: String(edge.id || `${type}:${from}:${to}:${index}`),
        from,
        to,
        type,
        value: Number.isFinite(score) && score > 0 ? score : 1,
        raw: edge,
      }
    })
    .filter((edge) => edge.from && edge.to)
}

function nodeColorForType(type: string, opacity = 1, highlighted = false) {
  const color = GROUP_STYLES[type]?.color || GROUP_STYLES.unknown.color
  const border = highlighted ? '#facc15' : color.border
  return {
    background: color.background,
    border,
    highlight: {
      background: color.background,
      border,
    },
    opacity,
  }
}

function visNodeFrom(node: NormalizedNode) {
  const style = GROUP_STYLES[node.type] || GROUP_STYLES.unknown
  return {
    id: node.id,
    label: node.label,
    group: node.type,
    shape: style.shape,
    value: node.degree,
    title: `${node.label}\n${node.type}\nDegree: ${node.degree}`,
    slug: node.slug,
    metadata: node.metadata,
    raw: node.raw,
    degree: node.degree,
    community: node.community,
    color: nodeColorForType(node.type),
    borderWidth: 1,
  }
}

function visEdgeFrom(edge: NormalizedEdge) {
  return {
    id: edge.id,
    from: edge.from,
    to: edge.to,
    title: edge.type,
    value: edge.value,
    raw: edge.raw,
    color: { color: 'rgba(148, 163, 184, 0.32)', opacity: 0.32 },
    smooth: { enabled: true, type: 'dynamic' },
    arrows: { to: { enabled: true, scaleFactor: 0.45 } },
  }
}

function isNodeVisible(nodeId: string): boolean {
  return visibleNodeIds.value.has(nodeId)
}

function isEdgeVisible(edge: NormalizedEdge): boolean {
  return visibleNodeIds.value.has(edge.from) && visibleNodeIds.value.has(edge.to)
}

function refreshViews() {
  if (nodeView && typeof nodeView.refresh === 'function') nodeView.refresh()
  if (edgeView && typeof edgeView.refresh === 'function') edgeView.refresh()
}

function resetVisualState() {
  if (!nodeDataSet || !edgeDataSet) return
  const matchSet = new Set(searchMatchIds.value)
  nodeDataSet.update(
    normalizedNodes.value.map((node) => ({
      id: node.id,
      color: nodeColorForType(node.type, 1, matchSet.has(node.id)),
      borderWidth: matchSet.has(node.id) ? 3 : 1,
      opacity: 1,
    }))
  )
  edgeDataSet.update(
    normalizedEdges.value.map((edge) => ({
      id: edge.id,
      color: { color: 'rgba(148, 163, 184, 0.32)', opacity: 0.32 },
      width: 1,
    }))
  )
}

function applyFocusFade(nodeId: string) {
  if (!network || !nodeDataSet || !edgeDataSet) return
  const connectedNodes = new Set<string>(network.getConnectedNodes(nodeId) || [])
  const connectedEdges = new Set<string>(network.getConnectedEdges(nodeId) || [])
  connectedNodes.add(nodeId)
  const matchSet = new Set(searchMatchIds.value)

  nodeDataSet.update(
    normalizedNodes.value.map((node) => {
      const inFocus = connectedNodes.has(node.id)
      const highlighted = node.id === nodeId || matchSet.has(node.id)
      return {
        id: node.id,
        color: nodeColorForType(node.type, inFocus ? 1 : 0.18, highlighted),
        borderWidth: node.id === nodeId ? 4 : highlighted ? 3 : 1,
        opacity: inFocus ? 1 : 0.18,
      }
    })
  )

  edgeDataSet.update(
    normalizedEdges.value.map((edge) => {
      const connected = connectedEdges.has(edge.id)
      return {
        id: edge.id,
        color: {
          color: connected ? 'rgba(96, 165, 250, 0.82)' : 'rgba(148, 163, 184, 0.08)',
          opacity: connected ? 0.82 : 0.08,
        },
        width: connected ? 2.5 : 0.6,
      }
    })
  )
}

function focusNode(nodeId: string) {
  if (!network || !nodeById.value[nodeId]) return
  selectedNodeId.value = nodeId
  noSearchResult.value = false
  network.selectNodes([nodeId])
  network.focus(nodeId, {
    scale: 1.25,
    animation: { duration: 450, easingFunction: 'easeInOutQuad' },
  })
  applyFocusFade(nodeId)
  updateDebugState()
}

function clearFocus() {
  selectedNodeId.value = ''
  if (network) network.unselectAll()
  resetVisualState()
  updateDebugState()
}

function resetFocus() {
  searchMatchIds.value = []
  noSearchResult.value = false
  clearFocus()
}

function performSearch() {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) {
    searchMatchIds.value = []
    noSearchResult.value = false
    resetVisualState()
    updateDebugState()
    return
  }
  const matches = normalizedNodes.value
    .filter((node) => isNodeVisible(node.id))
    .filter((node) => {
      const haystack = `${node.label} ${node.slug} ${node.id}`.toLowerCase()
      return haystack.includes(query)
    })
  searchMatchIds.value = matches.map((node) => node.id)
  noSearchResult.value = matches.length === 0
  resetVisualState()
  if (matches.length > 0) {
    focusNode(matches[0].id)
  } else {
    updateDebugState()
  }
}

function selectAllTypes() {
  typeFilters.value = nodeTypes.value.slice()
  refreshViews()
  clearFocus()
}

function clearTypeFilters() {
  typeFilters.value = []
  refreshViews()
  clearFocus()
}

function onFiltersChanged() {
  refreshViews()
  if (selectedNodeId.value && !isNodeVisible(selectedNodeId.value)) {
    selectedNodeId.value = ''
  }
  resetVisualState()
  updateDebugState()
}

function fitGraph() {
  if (!network) return
  network.fit({ animation: { duration: 350, easingFunction: 'easeInOutQuad' } })
}

function resetGraphView() {
  clearFocus()
  if (network) {
    network.fit({ animation: { duration: 350, easingFunction: 'easeInOutQuad' } })
  }
}

async function toggleFullscreen() {
  const root = rootRef.value
  if (!root || typeof document === 'undefined') return
  try {
    if (!document.fullscreenElement && root.requestFullscreen) {
      await root.requestFullscreen()
    } else if (document.exitFullscreen) {
      await document.exitFullscreen()
    }
  } catch {
    // Fullscreen may be blocked by browser policy; keep the UI safe.
  }
  window.setTimeout(() => {
    if (network) {
      network.redraw()
      network.fit({ animation: false })
    }
  }, 180)
}

function openSelectedRoute() {
  const route = selectedRoute.value
  if (!route || typeof window === 'undefined') return
  window.location.href = withBase(route)
}

function onNodeDoubleClick(nodeId: string) {
  const route = routeForNode(nodeById.value[nodeId])
  if (!route || typeof window === 'undefined') return
  window.location.href = withBase(route)
}

function formatMetadataEntries(metadata: Record<string, unknown>) {
  return Object.entries(metadata || {})
    .filter(([key]) => key !== 'slug' && key !== 'path' && key !== 'community')
    .map(([key, value]) => ({ key, value: metadataString(value) }))
}

function updateDebugState() {
  if (typeof window === 'undefined') return
  ;(window as any).__graphifyExplorerState = {
    ready: state.value === 'ready',
    selectedNodeId: selectedNodeId.value,
    searchQuery: searchQuery.value,
    searchMatchIds: searchMatchIds.value.slice(),
    typeFilters: typeFilters.value.slice(),
    communityFilters: communityFilters.value.slice(),
    visibleNodes: visibleNodeIds.value.size,
    totalNodes: normalizedNodes.value.length,
    totalEdges: normalizedEdges.value.length,
    inspectorOpen: !!selectedNodeId.value,
  }
}

function setupNetwork() {
  if (!networkRef.value || !NetworkCtor || !DataSetCtor || !DataViewCtor) return
  const nodes = normalizedNodes.value.map(visNodeFrom)
  const edges = normalizedEdges.value.map(visEdgeFrom)
  nodeDataSet = new DataSetCtor(nodes)
  edgeDataSet = new DataSetCtor(edges)
  nodeView = new DataViewCtor(nodeDataSet, {
    filter: (node: any) => isNodeVisible(node.id),
  })
  edgeView = new DataViewCtor(edgeDataSet, {
    filter: (edge: any) => {
      const raw = normalizedEdges.value.find((item) => item.id === edge.id)
      return raw ? isEdgeVisible(raw) : false
    },
  })
  network = new NetworkCtor(
    networkRef.value,
    { nodes: nodeView, edges: edgeView },
    {
      autoResize: true,
      groups: GROUP_STYLES,
      interaction: {
        hover: true,
        multiselect: false,
        navigationButtons: false,
        keyboard: false,
      },
      physics: {
        enabled: true,
        solver: 'forceAtlas2Based',
        forceAtlas2Based: {
          gravitationalConstant: -48,
          centralGravity: 0.01,
          springLength: 120,
          springConstant: 0.08,
          avoidOverlap: 0.45,
        },
        stabilization: {
          enabled: true,
          iterations: 180,
          updateInterval: 25,
        },
      },
      nodes: {
        borderWidth: 1,
        font: {
          color: '#e5e7eb',
          face: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
          size: 14,
          strokeWidth: 3,
          strokeColor: '#020617',
        },
        scaling: {
          min: 10,
          max: 34,
        },
      },
      edges: {
        width: 1,
        selectionWidth: 2,
        hoverWidth: 1.4,
        font: { color: '#cbd5e1', strokeWidth: 0 },
      },
    }
  )

  network.on('click', (params: any) => {
    const nodeId = params.nodes && params.nodes[0]
    if (nodeId) focusNode(String(nodeId))
    else clearFocus()
  })
  network.on('doubleClick', (params: any) => {
    const nodeId = params.nodes && params.nodes[0]
    if (nodeId) onNodeDoubleClick(String(nodeId))
  })
  network.once('stabilizationIterationsDone', () => {
    fitGraph()
  })
}

async function loadGraphData() {
  state.value = 'loading'
  errorMessage.value = ''
  try {
    const [nodesResp, edgesResp] = await Promise.all([
      fetch(withBase('/graph/nodes.json')),
      fetch(withBase('/graph/edges.json')),
    ])
    if (!nodesResp.ok) throw new Error(`nodes.json returned HTTP ${nodesResp.status}`)
    if (!edgesResp.ok) throw new Error(`edges.json returned HTTP ${edgesResp.status}`)
    const nodes = (await nodesResp.json()) as RawNode[]
    const edges = (await edgesResp.json()) as RawEdge[]
    if (!Array.isArray(nodes) || !Array.isArray(edges)) {
      throw new Error('Graph JSON must contain node and edge arrays.')
    }
    rawNodes.value = nodes
    rawEdges.value = edges
    const degrees = degreeMapFromEdges(edges)
    normalizedNodes.value = normalizeNodes(nodes, degrees)
    normalizedEdges.value = normalizeEdges(edges)
    typeFilters.value = nodeTypes.value.slice()
    communityFilters.value = communities.value.slice()
    state.value = 'ready'
    await nextTick()
    setupNetwork()
    updateDebugState()
  } catch (error: any) {
    state.value = 'error'
    errorMessage.value = error?.message || String(error)
    updateDebugState()
  }
}

async function loadVisRuntime() {
  const [visData, visNetwork] = await Promise.all([
    import('vis-data/peer'),
    import('vis-network/peer'),
  ])
  DataSetCtor = visData.DataSet
  DataViewCtor = visData.DataView
  NetworkCtor = visNetwork.Network
}

function onFullscreenChange() {
  if (typeof document === 'undefined') return
  isFullscreen.value = document.fullscreenElement === rootRef.value
  window.setTimeout(() => {
    if (network) {
      network.redraw()
      network.fit({ animation: false })
    }
  }, 120)
}

onMounted(async () => {
  if (typeof window === 'undefined') return
  document.addEventListener('fullscreenchange', onFullscreenChange)
  await loadVisRuntime()
  await loadGraphData()
})

onBeforeUnmount(() => {
  if (typeof document !== 'undefined') {
    document.removeEventListener('fullscreenchange', onFullscreenChange)
  }
  if (network) {
    network.destroy()
    network = null
  }
  if (typeof window !== 'undefined') {
    delete (window as any).__graphifyExplorerState
  }
})
</script>

<template>
  <section
    ref="rootRef"
    class="graphify-explorer"
    data-testid="graphify-explorer"
  >
    <header class="graphify-topbar">
      <div>
        <p class="graphify-kicker">Graphify-style explorer</p>
        <h2>Enhanced Knowledge Graph</h2>
      </div>
      <div class="graphify-controls">
        <button type="button" data-testid="graphify-fit" @click="fitGraph">
          Fit
        </button>
        <button type="button" data-testid="graphify-reset" @click="resetGraphView">
          Reset focus
        </button>
        <button
          type="button"
          data-testid="graphify-fullscreen"
          @click="toggleFullscreen"
        >
          {{ isFullscreen ? 'Exit fullscreen' : 'Fullscreen' }}
        </button>
      </div>
    </header>

    <div v-if="state === 'loading'" class="graphify-state" data-testid="graphify-loading">
      Loading graph data...
    </div>
    <div v-else-if="state === 'error'" class="graphify-state graphify-error" data-testid="graphify-error">
      {{ errorMessage }}
    </div>

    <div v-show="state === 'ready'" class="graphify-stage">
      <aside class="graphify-panel graphify-left-panel">
        <label class="graphify-label" for="graphify-search">Search</label>
        <input
          id="graphify-search"
          v-model="searchQuery"
          class="graphify-search"
          data-testid="graphify-search"
          type="search"
          placeholder="label, slug, or id"
          @keydown.enter.prevent="performSearch"
        />
        <p
          v-if="noSearchResult"
          class="graphify-muted"
          data-testid="graphify-no-results"
        >
          No matching node.
        </p>
        <p v-else-if="searchMatchIds.length" class="graphify-muted">
          {{ searchMatchIds.length }} match{{ searchMatchIds.length === 1 ? '' : 'es' }}
        </p>

        <div class="graphify-filter-heading">
          <strong>Node types</strong>
          <span>
            <button type="button" @click="selectAllTypes">Select all</button>
            <button type="button" @click="clearTypeFilters">Clear</button>
          </span>
        </div>
        <div class="graphify-checks">
          <label
            v-for="type in nodeTypes"
            :key="type"
            class="graphify-check"
          >
            <input
              v-model="typeFilters"
              type="checkbox"
              :value="type"
              :data-testid="`graphify-type-filter-${type}`"
              @change="onFiltersChanged"
            />
            <span>{{ type }}</span>
          </label>
        </div>

        <template v-if="hasCommunityFilters">
          <div class="graphify-filter-heading">
            <strong>Communities</strong>
          </div>
          <div class="graphify-checks">
            <label
              v-for="community in communities"
              :key="community"
              class="graphify-check"
            >
              <input
                v-model="communityFilters"
                type="checkbox"
                :value="community"
                @change="onFiltersChanged"
              />
              <span>{{ community }}</span>
            </label>
          </div>
        </template>

        <div class="graphify-counts" data-testid="graphify-counts">
          <span>{{ visibleNodeIds.size }} visible nodes</span>
          <span>{{ normalizedEdges.length }} total edges</span>
        </div>
      </aside>

      <div
        ref="networkRef"
        class="graphify-network"
        data-testid="graphify-network"
        aria-label="Graphify knowledge graph network"
      ></div>

      <aside class="graphify-panel graphify-inspector" data-testid="graphify-inspector">
        <template v-if="selectedNode">
          <p class="graphify-kicker">Selected node</p>
          <h3>{{ selectedNode.label }}</h3>
          <dl class="graphify-facts">
            <div><dt>Type</dt><dd>{{ selectedNode.type }}</dd></div>
            <div><dt>ID</dt><dd>{{ selectedNode.id }}</dd></div>
            <div><dt>Slug</dt><dd>{{ slugFromNode(selectedNode) }}</dd></div>
            <div><dt>Degree</dt><dd>{{ selectedNode.degree }}</dd></div>
            <div v-if="selectedNode.community"><dt>Community</dt><dd>{{ selectedNode.community }}</dd></div>
          </dl>

          <button
            v-if="selectedRoute"
            type="button"
            class="graphify-primary-action"
            data-testid="graphify-open-node"
            @click="openSelectedRoute"
          >
            {{ selectedCtaLabel }}
          </button>

          <section>
            <h4>Neighbors</h4>
            <ul class="graphify-neighbors" data-testid="graphify-neighbors">
              <li v-for="neighbor in selectedNeighbors" :key="neighbor.id">
                <button type="button" @click="focusNode(neighbor.id)">
                  <span>{{ neighbor.label }}</span>
                  <small>{{ neighbor.type }}</small>
                </button>
              </li>
            </ul>
          </section>

          <section v-if="formatMetadataEntries(selectedNode.metadata).length">
            <h4>Metadata</h4>
            <dl class="graphify-metadata">
              <div
                v-for="entry in formatMetadataEntries(selectedNode.metadata)"
                :key="entry.key"
              >
                <dt>{{ entry.key }}</dt>
                <dd>{{ entry.value }}</dd>
              </div>
            </dl>
          </section>
        </template>
        <template v-else>
          <p class="graphify-kicker">Inspector</p>
          <h3>No node selected</h3>
          <p class="graphify-muted">
            Search or click a node to inspect its details and direct neighbors.
          </p>
        </template>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.graphify-explorer {
  min-height: calc(100vh - 96px);
  width: 100%;
  max-width: 100%;
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  background:
    radial-gradient(circle at 25% 20%, rgba(74, 144, 217, 0.18), transparent 32rem),
    linear-gradient(135deg, #020617 0%, #111827 54%, #0f172a 100%);
  color: #e5e7eb;
}

.graphify-topbar {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: center;
  padding: 1rem;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
}

.graphify-topbar h2,
.graphify-inspector h3,
.graphify-inspector h4 {
  margin: 0;
  color: #f8fafc;
}

.graphify-kicker {
  margin: 0 0 0.25rem;
  color: #93c5fd;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

.graphify-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.graphify-controls button,
.graphify-filter-heading button,
.graphify-primary-action,
.graphify-neighbors button {
  border: 1px solid rgba(148, 163, 184, 0.34);
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.82);
  color: #e5e7eb;
  cursor: pointer;
  font: inherit;
}

.graphify-controls button {
  padding: 0.45rem 0.7rem;
}

.graphify-stage {
  position: relative;
  display: grid;
  grid-template-columns: minmax(220px, 280px) minmax(0, 1fr) minmax(260px, 320px);
  min-height: 720px;
  width: 100%;
  max-width: 100%;
}

.graphify-network {
  min-width: 0;
  min-height: 720px;
}

.graphify-panel {
  z-index: 2;
  min-width: 0;
  padding: 1rem;
  background: rgba(15, 23, 42, 0.86);
  border-color: rgba(148, 163, 184, 0.2);
  backdrop-filter: blur(10px);
}

.graphify-left-panel {
  border-right: 1px solid rgba(148, 163, 184, 0.18);
}

.graphify-inspector {
  border-left: 1px solid rgba(148, 163, 184, 0.18);
  overflow: auto;
}

.graphify-label,
.graphify-filter-heading strong {
  display: block;
  margin-bottom: 0.4rem;
  color: #f8fafc;
  font-weight: 700;
}

.graphify-search {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  padding: 0.55rem 0.65rem;
  border: 1px solid rgba(148, 163, 184, 0.36);
  border-radius: 6px;
  background: rgba(2, 6, 23, 0.72);
  color: #f8fafc;
}

.graphify-filter-heading {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  align-items: center;
  margin-top: 1rem;
}

.graphify-filter-heading span {
  display: inline-flex;
  gap: 0.35rem;
}

.graphify-filter-heading button {
  padding: 0.25rem 0.45rem;
  font-size: 0.78rem;
}

.graphify-checks {
  display: grid;
  gap: 0.4rem;
}

.graphify-check {
  display: flex;
  gap: 0.4rem;
  align-items: center;
  min-width: 0;
  overflow-wrap: anywhere;
}

.graphify-counts {
  display: grid;
  gap: 0.25rem;
  margin-top: 1rem;
  color: #cbd5e1;
  font-size: 0.85rem;
}

.graphify-state {
  padding: 2rem;
  color: #e5e7eb;
}

.graphify-error {
  color: #fecaca;
}

.graphify-muted {
  color: #cbd5e1;
}

.graphify-facts,
.graphify-metadata {
  display: grid;
  gap: 0.45rem;
  margin: 0.8rem 0;
}

.graphify-facts div,
.graphify-metadata div {
  display: grid;
  grid-template-columns: minmax(5rem, 0.35fr) minmax(0, 1fr);
  gap: 0.6rem;
}

.graphify-facts dt,
.graphify-metadata dt {
  color: #93c5fd;
  font-weight: 700;
}

.graphify-facts dd,
.graphify-metadata dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  color: #e5e7eb;
}

.graphify-primary-action {
  width: 100%;
  margin: 0.5rem 0 1rem;
  padding: 0.65rem 0.75rem;
  background: #2563eb;
  border-color: #60a5fa;
}

.graphify-neighbors {
  display: grid;
  gap: 0.4rem;
  max-height: 16rem;
  overflow: auto;
  padding: 0;
  margin: 0.6rem 0 0;
  list-style: none;
}

.graphify-neighbors button {
  display: grid;
  width: 100%;
  gap: 0.15rem;
  padding: 0.5rem 0.6rem;
  text-align: left;
}

.graphify-neighbors small {
  color: #93c5fd;
}

:fullscreen.graphify-explorer {
  min-height: 100vh;
  border-radius: 0;
}

:fullscreen .graphify-stage {
  min-height: calc(100vh - 75px);
}

:fullscreen .graphify-network {
  min-height: calc(100vh - 75px);
}

@media (max-width: 980px) {
  .graphify-explorer {
    overflow: visible;
  }

  .graphify-topbar {
    align-items: stretch;
    flex-direction: column;
  }

  .graphify-stage {
    grid-template-columns: minmax(0, 1fr);
    min-height: auto;
  }

  .graphify-left-panel,
  .graphify-inspector {
    border: 0;
  }

  .graphify-network {
    min-height: 520px;
    order: -1;
  }
}
</style>
