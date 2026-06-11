<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { withBase } from 'vitepress'

type SnapshotResource = {
  id: string
  title: string
  route: string
  url?: string
  source_type: string
  status: string
  provider?: string
  model?: string
  topics?: string[]
  concepts?: string[]
  tags?: string[]
  review_flags?: string[]
  failure_reason?: string
  links?: {
    resource?: string
    review?: string
    graphify?: string
    explorer?: string
  }
}

type OperationsSnapshot = {
  schema_version: string
  generated_at: string
  resource_count: number
  resources: SnapshotResource[]
  summary?: {
    by_source_type?: Record<string, number>
    by_status?: Record<string, number>
  }
  review_summary?: Record<string, number>
  graph_summary?: {
    nodes?: number
    edges?: number
    resources?: number
  }
}

type ProcessingRun = {
  run_id: string
  resource_id: string
  operation: string
  provider: string
  model: string
  status: string
  started_at?: string
  completed_at?: string
  total_tokens?: number
  usage_source?: string
  estimated_cost?: number
  error?: string
}

type TokenSummary = {
  run_count: number
  ledger_entry_count: number
  success_count: number
  failed_count: number
  cache_hit_count: number
  total_tokens: number
  estimated_cost: number
  by_provider?: Record<string, { entries: number; total_tokens: number; estimated_cost: number }>
}

const CONTROL_ORIGIN = 'http://127.0.0.1:8765'

const snapshot = ref<OperationsSnapshot | null>(null)
const snapshotError = ref('')
const localUnavailable = ref(false)
const localStatus = ref<any | null>(null)
const runs = ref<ProcessingRun[]>([])
const tokenSummary = ref<TokenSummary | null>(null)
const localError = ref('')
const query = ref('')
const sourceFilter = ref('all')
const reviewFilter = ref('all')
const statusFilter = ref('all')
const sortMode = ref('title')

const resources = computed(() => snapshot.value?.resources || [])
const reviewCount = computed(() => {
  const summary = snapshot.value?.review_summary || {}
  return Object.entries(summary).reduce((total, [, value]) => total + Number(value || 0), 0)
})
const sourceTypes = computed(() => Object.keys(snapshot.value?.summary?.by_source_type || {}).sort())
const statuses = computed(() => Object.keys(snapshot.value?.summary?.by_status || {}).sort())
const reviewFlags = computed(() => {
  const flags = new Set<string>()
  for (const resource of resources.value) {
    for (const flag of resource.review_flags || []) flags.add(flag)
  }
  return [...flags].sort()
})
const providerBreakdown = computed(() => Object.entries(tokenSummary.value?.by_provider || {}))

const filteredResources = computed(() => {
  const text = query.value.trim().toLowerCase()
  const filtered = resources.value.filter((resource) => {
    const haystack = [
      resource.id,
      resource.title,
      resource.url || '',
      resource.source_type,
      resource.status,
      resource.provider || '',
      resource.model || '',
      ...(resource.topics || []),
      ...(resource.concepts || []),
      ...(resource.tags || []),
      ...(resource.review_flags || []),
    ].join(' ').toLowerCase()
    if (text && !haystack.includes(text)) return false
    if (sourceFilter.value !== 'all' && resource.source_type !== sourceFilter.value) return false
    if (statusFilter.value !== 'all' && resource.status !== statusFilter.value) return false
    if (reviewFilter.value === 'none' && (resource.review_flags || []).length > 0) return false
    if (
      reviewFilter.value !== 'all' &&
      reviewFilter.value !== 'none' &&
      !(resource.review_flags || []).includes(reviewFilter.value)
    ) {
      return false
    }
    return true
  })
  return filtered.sort((left, right) => {
    if (sortMode.value === 'status') return left.status.localeCompare(right.status) || left.title.localeCompare(right.title)
    if (sortMode.value === 'source') return left.source_type.localeCompare(right.source_type) || left.title.localeCompare(right.title)
    return left.title.localeCompare(right.title)
  })
})

async function fetchJson(url: string, options: RequestInit = {}) {
  const response = await fetch(url, { cache: 'no-store', ...options })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

async function loadSnapshot() {
  try {
    snapshot.value = await fetchJson(withBase('/operations/operations_snapshot.json')) as OperationsSnapshot
  } catch (error) {
    snapshotError.value = error instanceof Error ? error.message : 'Unable to load operations snapshot.'
  }
}

async function loadLocalControlPlane() {
  localUnavailable.value = false
  localError.value = ''
  try {
    const [statusPayload, runPayload, tokenPayload] = await Promise.all([
      fetchJson(`${CONTROL_ORIGIN}/api/status`),
      fetchJson(`${CONTROL_ORIGIN}/api/runs`),
      fetchJson(`${CONTROL_ORIGIN}/api/token-ledger/summary`),
    ])
    localStatus.value = statusPayload
    runs.value = runPayload.runs || []
    tokenSummary.value = tokenPayload.summary || runPayload.summary || null
  } catch (error) {
    localUnavailable.value = true
    localStatus.value = null
    runs.value = []
    tokenSummary.value = null
    localError.value = error instanceof Error ? error.message : 'Local control plane unavailable.'
  }
}

function formatLabel(value: string | undefined): string {
  if (!value) return 'none'
  return value.replace(/[_-]+/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase())
}

function formatDate(value: string | undefined): string {
  if (!value) return 'unknown'
  return value.replace('T', ' ').replace(/\.\d+\+00:00$/, 'Z')
}

function formatCost(value: number | undefined): string {
  return `$${Number(value || 0).toFixed(6)}`
}

function safeHref(value: string | undefined): string {
  return withBase(value || '/')
}

onMounted(() => {
  void loadSnapshot()
  void loadLocalControlPlane()
})
</script>

<template>
  <section class="operations-dashboard" data-testid="operations-dashboard">
    <div class="operations-hero">
      <p class="wiki-muted">Read-only local workbench</p>
      <h2>Operations dashboard</h2>
      <p>
        Explore resources, review queues, graph coverage, and local run accounting. Static
        snapshot data works everywhere; run and token summaries appear only when the local control
        plane is running on <code>{{ CONTROL_ORIGIN }}</code>.
      </p>
      <p class="operations-boundary" data-testid="operations-boundary">
        Boundary: no browser API-key fields, no provider generation calls, no processing actions,
        and no reprocess buttons are included in this dashboard.
      </p>
    </div>

    <div v-if="snapshotError" class="operations-card operations-error">
      <h3>Snapshot unavailable</h3>
      <p>{{ snapshotError }}</p>
    </div>

    <div v-else class="operations-grid">
      <section class="operations-card operations-summary-card" data-testid="operations-static-summary">
        <span class="wiki-chip">Static snapshot</span>
        <h3>Resources</h3>
        <strong>{{ snapshot?.resource_count || 0 }}</strong>
        <span>Total resources</span>
      </section>
      <section class="operations-card operations-summary-card">
        <span class="wiki-chip">Review</span>
        <h3>Queue</h3>
        <strong>{{ reviewCount }}</strong>
        <span>Review signals</span>
      </section>
      <section class="operations-card operations-summary-card">
        <span class="wiki-chip">Graph</span>
        <h3>Coverage</h3>
        <strong>{{ snapshot?.graph_summary?.nodes || 0 }}</strong>
        <span>{{ snapshot?.graph_summary?.edges || 0 }} edges</span>
      </section>
      <section class="operations-card operations-summary-card" data-testid="operations-local-summary">
        <span class="wiki-chip">Local ledger</span>
        <h3>Runs</h3>
        <strong>{{ tokenSummary?.run_count || 0 }}</strong>
        <span>{{ tokenSummary?.total_tokens || 0 }} tokens</span>
      </section>
    </div>

    <section class="operations-card operations-local-panel" data-testid="operations-local-panel">
      <div class="operations-section-heading">
        <div>
          <span class="wiki-chip">Read-only enrichment</span>
          <h3>Local control plane</h3>
        </div>
        <button type="button" @click="loadLocalControlPlane">Refresh</button>
      </div>
      <div v-if="localUnavailable" class="operations-empty" data-testid="operations-local-unavailable">
        <p>Local control plane is not running. Start it from the nested repo, then refresh.</p>
        <pre><code>.venv/bin/python -m wiki control-plane --host 127.0.0.1 --port 8765</code></pre>
        <p class="wiki-muted">{{ localError }}</p>
      </div>
      <div v-else class="operations-local-ready" data-testid="operations-local-ready">
        <div class="operations-run-summary">
          <div><strong>{{ tokenSummary?.success_count || 0 }}</strong><span>Successful</span></div>
          <div><strong>{{ tokenSummary?.failed_count || 0 }}</strong><span>Failed</span></div>
          <div><strong>{{ tokenSummary?.cache_hit_count || 0 }}</strong><span>Cache hits</span></div>
          <div><strong>{{ formatCost(tokenSummary?.estimated_cost) }}</strong><span>Estimated cost</span></div>
        </div>
        <p class="wiki-muted">Connected to {{ localStatus?.host || '127.0.0.1' }}:{{ localStatus?.port || 8765 }}.</p>
      </div>
    </section>

    <section v-if="providerBreakdown.length" class="operations-card" data-testid="operations-provider-breakdown">
      <div class="operations-section-heading">
        <div>
          <span class="wiki-chip">Token ledger</span>
          <h3>Provider breakdown</h3>
        </div>
      </div>
      <div class="operations-breakdown-grid">
        <div v-for="[provider, item] in providerBreakdown" :key="provider" class="operations-breakdown-item">
          <strong>{{ provider }}</strong>
          <span>{{ item.total_tokens }} tokens</span>
          <span>{{ item.entries }} entries</span>
        </div>
      </div>
    </section>

    <section class="operations-card operations-resource-explorer" data-testid="operations-resource-explorer">
      <div class="operations-section-heading">
        <div>
          <span class="wiki-chip">Database explorer</span>
          <h3>Resources</h3>
        </div>
        <span>{{ filteredResources.length }} shown</span>
      </div>

      <div class="operations-toolbar">
        <label>
          <span>Search</span>
          <input
            v-model="query"
            data-testid="operations-search"
            type="search"
            placeholder="Title, resource id, URL, topic, concept"
          />
        </label>
        <label>
          <span>Source type</span>
          <select v-model="sourceFilter" data-testid="operations-source-filter">
            <option value="all">All source types</option>
            <option v-for="source in sourceTypes" :key="source" :value="source">{{ formatLabel(source) }}</option>
          </select>
        </label>
        <label>
          <span>Status</span>
          <select v-model="statusFilter" data-testid="operations-status-filter">
            <option value="all">All statuses</option>
            <option v-for="status in statuses" :key="status" :value="status">{{ formatLabel(status) }}</option>
          </select>
        </label>
        <label>
          <span>Review</span>
          <select v-model="reviewFilter" data-testid="operations-review-filter">
            <option value="all">All review states</option>
            <option value="none">No review flags</option>
            <option v-for="flag in reviewFlags" :key="flag" :value="flag">{{ formatLabel(flag) }}</option>
          </select>
        </label>
        <label>
          <span>Sort</span>
          <select v-model="sortMode" data-testid="operations-sort">
            <option value="title">Title</option>
            <option value="status">Status</option>
            <option value="source">Source type</option>
          </select>
        </label>
      </div>

      <div v-if="filteredResources.length" class="operations-resource-list">
        <article
          v-for="resource in filteredResources.slice(0, 80)"
          :key="resource.id"
          class="operations-resource-card"
          data-testid="operations-resource-card"
        >
          <div class="operations-card-header">
            <span class="wiki-chip">{{ formatLabel(resource.source_type) }}</span>
            <span class="wiki-chip">{{ formatLabel(resource.status) }}</span>
            <span v-for="flag in resource.review_flags || []" :key="flag" class="wiki-chip operations-review-chip">
              {{ formatLabel(flag) }}
            </span>
          </div>
          <h4><a :href="safeHref(resource.links?.resource || resource.route)">{{ resource.title }}</a></h4>
          <p class="operations-token"><code>{{ resource.id }}</code></p>
          <p v-if="resource.url" class="operations-token">{{ resource.url }}</p>
          <div v-if="resource.topics?.length || resource.concepts?.length || resource.tags?.length" class="operations-chip-row">
            <span v-for="topic in resource.topics || []" :key="`topic-${resource.id}-${topic}`" class="wiki-chip">
              {{ topic }}
            </span>
            <span v-for="concept in resource.concepts || []" :key="`concept-${resource.id}-${concept}`" class="wiki-chip">
              {{ concept }}
            </span>
            <span v-for="tag in resource.tags || []" :key="`tag-${resource.id}-${tag}`" class="wiki-chip">
              {{ tag }}
            </span>
          </div>
          <p v-if="resource.provider || resource.model" class="wiki-muted">
            {{ resource.provider || 'unknown provider' }} / {{ resource.model || 'unknown model' }}
          </p>
          <p v-if="resource.failure_reason" class="operations-error-text">{{ resource.failure_reason }}</p>
          <div class="operations-link-row">
            <a :href="safeHref(resource.links?.resource || resource.route)">Open resource</a>
            <a :href="safeHref(resource.links?.review || '/review/')">Review</a>
            <a :href="safeHref(resource.links?.graphify || '/graph/graphify')">Graphify</a>
            <a :href="safeHref(resource.links?.explorer || '/explorer/')">Explorer search</a>
          </div>
        </article>
      </div>
      <div v-else class="operations-empty">No resources match the current filters.</div>
    </section>

    <section class="operations-card" data-testid="operations-recent-runs">
      <div class="operations-section-heading">
        <div>
          <span class="wiki-chip">Local only</span>
          <h3>Recent runs</h3>
        </div>
      </div>
      <div v-if="runs.length" class="operations-run-list">
        <article v-for="run in runs.slice(0, 12)" :key="run.run_id" class="operations-run-row">
          <div>
            <strong>{{ run.operation }}</strong>
            <span class="operations-token">{{ run.run_id }}</span>
          </div>
          <div>
            <span class="wiki-chip">{{ formatLabel(run.status) }}</span>
            <span>{{ run.provider }} / {{ run.model }}</span>
          </div>
          <div>
            <span>{{ run.total_tokens || 0 }} tokens</span>
            <span>{{ formatDate(run.completed_at || run.started_at) }}</span>
          </div>
          <p v-if="run.error" class="operations-error-text">{{ run.error }}</p>
        </article>
      </div>
      <div v-else class="operations-empty" data-testid="operations-runs-empty">
        No local runs are available yet. Process resources from the CLI first, then refresh this page.
      </div>
    </section>
  </section>
</template>
