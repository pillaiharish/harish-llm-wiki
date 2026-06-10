<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'

type SearchItem = {
  id?: string
  title?: string
  type?: string
  summary?: string
  tags?: string[]
  topics?: string[]
  source_url?: string
  local_page?: string
  provider?: string
  model?: string
  prompt_version?: string
  review_status?: string
  stale_status?: string
}

type DataState = 'loading' | 'ready' | 'error'

const dataState = ref<DataState>('loading')
const errorMessage = ref<string | null>(null)
const items = ref<SearchItem[]>([])

const searchTerm = ref('')
const typeFilter = ref('')
const topicFilter = ref('')
const providerFilter = ref('')
const reviewFilter = ref('')
const staleFilter = ref('')

const RESULT_LIMIT = 100

function uniq(values: Array<string | undefined | null>): string[] {
  const set = new Set<string>()
  for (const v of values) {
    if (v && String(v).length > 0) set.add(String(v))
  }
  return Array.from(set).sort()
}

const allTypes = computed<string[]>(() =>
  uniq(items.value.map((i) => i.type))
)
const allTopics = computed<string[]>(() =>
  uniq(items.value.flatMap((i) => i.topics || []))
)
const allProviders = computed<string[]>(() =>
  uniq(items.value.map((i) => i.provider))
)
const allReviewStates = computed<string[]>(() =>
  uniq(items.value.map((i) => i.review_status))
)
const allStaleStates = computed<string[]>(() =>
  uniq(items.value.map((i) => i.stale_status))
)

const filteredItems = computed<SearchItem[]>(() => {
  const q = searchTerm.value.trim().toLowerCase()
  const t = typeFilter.value
  const tp = topicFilter.value
  const pv = providerFilter.value
  const rv = reviewFilter.value
  const st = staleFilter.value
  return items.value.filter((i) => {
    if (q) {
      const hay = `${i.title || ''} ${i.summary || ''}`.toLowerCase()
      if (hay.indexOf(q) === -1) return false
    }
    if (t && i.type !== t) return false
    if (tp) {
      const topics = i.topics || []
      if (!topics.includes(tp)) return false
    }
    if (pv && i.provider !== pv) return false
    if (rv && i.review_status !== rv) return false
    if (st && i.stale_status !== st) return false
    return true
  })
})

const visibleItems = computed<SearchItem[]>(() =>
  filteredItems.value.slice(0, RESULT_LIMIT)
)

const totalCount = computed<number>(() => items.value.length)
const matchedCount = computed<number>(() => filteredItems.value.length)

function buildIndexUrl(): string {
  const base = (import.meta.env.BASE_URL as string) || '/'
  return base.replace(/\/$/, '/') + 'search/all.json'
}

async function loadIndex(): Promise<void> {
  if (typeof window === 'undefined') return
  if (typeof fetch === 'undefined') {
    dataState.value = 'error'
    errorMessage.value = 'fetch is not available in this runtime'
    return
  }
  const url = buildIndexUrl()
  try {
    const resp = await fetch(url)
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`)
    }
    const payload = (await resp.json()) as { items?: SearchItem[] }
    const list = Array.isArray(payload?.items) ? payload.items : []
    items.value = list
    dataState.value = list.length > 0 ? 'ready' : 'ready'
    errorMessage.value = null
  } catch (e: any) {
    dataState.value = 'error'
    errorMessage.value =
      (e && e.message) ? String(e.message) : String(e)
    items.value = []
  }
}

function resetFilters(): void {
  searchTerm.value = ''
  typeFilter.value = ''
  topicFilter.value = ''
  providerFilter.value = ''
  reviewFilter.value = ''
  staleFilter.value = ''
}

function displaySummary(summary?: string): string {
  if (!summary) return ''
  const cleaned = summary
    .split(/\r?\n/)
    .filter((line) => !line.trim().startsWith('|'))
    .join(' ')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\|[-\s:|]+\|/g, ' ')
    .replace(/\|\s*Date learned\s*\|[\s\S]*$/i, ' ')
    .replace(/\|\s*Date\s*\|[\s\S]*$/i, ' ')
    .replace(/#{1,6}\s*/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  return cleaned.length > 260 ? `${cleaned.slice(0, 257).trimEnd()}...` : cleaned
}

onMounted(() => {
  void loadIndex()
})

onBeforeUnmount(() => {
  // No persistent listeners to clean up: all refs and DOM nodes
  // are owned by Vue and the component template.
})
</script>

<template>
  <div class="search-explorer" data-state="loading">
    <div
      id="explorer-live-stats"
      class="se-stats"
      :data-state="dataState"
      aria-live="polite"
    >
      <p v-if="dataState === 'loading'" id="explorer-live-stats-line">
        Loading search index…
      </p>
      <p v-else-if="dataState === 'error'" id="explorer-live-stats-line">
        Could not load search index. Check /search/all.json.
      </p>
      <p v-else id="explorer-live-stats-line">
        Indexed {{ totalCount }} items
        <template v-if="matchedCount !== totalCount">
          · showing {{ matchedCount }} match<span v-if="matchedCount !== 1">es</span>
        </template>.
      </p>
    </div>

    <div class="se-controls">
      <label class="se-label" for="explorer-q">Search:</label>
      <input
        id="explorer-q"
        v-model="searchTerm"
        type="search"
        placeholder="title or summary"
        autocomplete="off"
      />

      <label class="se-label" for="explorer-type">Type:</label>
      <select id="explorer-type" v-model="typeFilter">
        <option value="">All types</option>
        <option v-for="t in allTypes" :key="`type-${t}`" :value="t">
          {{ t }}
        </option>
      </select>

      <label class="se-label" for="explorer-topic">Topic:</label>
      <select id="explorer-topic" v-model="topicFilter">
        <option value="">All topics</option>
        <option v-for="t in allTopics" :key="`topic-${t}`" :value="t">
          {{ t }}
        </option>
      </select>

      <label class="se-label" for="explorer-provider">Provider:</label>
      <select id="explorer-provider" v-model="providerFilter">
        <option value="">All providers</option>
        <option v-for="t in allProviders" :key="`provider-${t}`" :value="t">
          {{ t }}
        </option>
      </select>

      <label class="se-label" for="explorer-review">Review:</label>
      <select id="explorer-review" v-model="reviewFilter">
        <option value="">All review states</option>
        <option
          v-for="t in allReviewStates"
          :key="`review-${t}`"
          :value="t"
        >
          {{ t }}
        </option>
      </select>

      <label class="se-label" for="explorer-stale">Stale:</label>
      <select id="explorer-stale" v-model="staleFilter">
        <option value="">All stale states</option>
        <option v-for="t in allStaleStates" :key="`stale-${t}`" :value="t">
          {{ t }}
        </option>
      </select>

      <button
        id="explorer-reset"
        type="button"
        class="se-button"
        @click="resetFilters"
      >
        Reset filters
      </button>
    </div>

    <div id="explorer-results" class="se-results" :data-count="visibleItems.length">
      <p v-if="dataState === 'error'" class="se-error">
        Could not load search index. Check /search/all.json.
        <span v-if="errorMessage" class="se-error-detail">
          ({{ errorMessage }})
        </span>
      </p>
      <p
        v-else-if="dataState === 'ready' && visibleItems.length === 0"
        class="se-empty"
      >
        <em>No matching resources.</em>
      </p>
      <ul v-else-if="visibleItems.length > 0" class="se-list">
        <li
          v-for="item in visibleItems"
          :key="String(item.id || item.local_page || item.title || '')"
          class="se-row"
          :data-item-id="String(item.id || '')"
          :data-item-type="String(item.type || '')"
        >
          <a
            v-if="item.local_page"
            :href="item.local_page"
            class="se-link"
          >{{ item.title || item.local_page }}</a>
          <span v-else class="se-link se-link-static">
            {{ item.title || '(untitled)' }}
          </span>
          <code v-if="item.type" class="se-type">{{ item.type }}</code>
          <span v-if="displaySummary(item.summary)" class="se-summary">{{ displaySummary(item.summary) }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.search-explorer {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  margin: 0.75rem 0 1.25rem;
}
.se-stats {
  font-size: 0.95rem;
  color: var(--vp-c-text-2, #555);
  border-left: 3px solid var(--vp-c-divider, #ddd);
  padding: 0.55rem 0.75rem;
  background: var(--vp-c-bg-soft, #fafafa);
  border-radius: 8px;
}
.se-stats[data-state='error'] {
  border-left-color: #c0392b;
  color: #c0392b;
}
.se-stats[data-state='ready'] {
  border-left-color: #2ecc71;
}
.se-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
  align-items: flex-end;
  padding: 0.8rem;
  border: 1px solid var(--vp-c-divider, #ddd);
  border-radius: 8px;
  background: var(--vp-c-bg-soft, #fafafa);
}
.se-label {
  display: grid;
  gap: 0.2rem;
  font-weight: 600;
  color: var(--vp-c-text-1, #222);
}
.se-controls input[type='search'],
.se-controls select {
  max-width: 100%;
  padding: 0.42rem 0.55rem;
  border: 1px solid var(--vp-c-divider, #ccc);
  border-radius: 6px;
  background: var(--vp-c-bg, #fff);
  font: inherit;
}
.se-controls input[type='search'] {
  min-width: 240px;
}
.se-button {
  padding: 0.45rem 0.75rem;
  border: 1px solid var(--vp-c-divider, #ccc);
  border-radius: 6px;
  background: var(--vp-c-bg, #fff);
  cursor: pointer;
  font: inherit;
}
.se-button:hover {
  background: var(--vp-c-default-soft, #eef);
}
.se-results ul.se-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 0.55rem;
}
.se-row {
  border: 1px solid var(--vp-c-divider, #ddd);
  border-radius: 8px;
  padding: 0.75rem 0.85rem;
  background: var(--vp-c-bg, #fff);
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem 0.55rem;
  align-items: baseline;
  min-width: 0;
}
.se-link {
  min-width: 0;
  font-weight: 600;
  color: var(--vp-c-brand-1, #3451b2);
  text-decoration: none;
  overflow-wrap: anywhere;
}
.se-link:hover {
  text-decoration: underline;
}
.se-link-static {
  color: var(--vp-c-text-1, #222);
  cursor: default;
}
.se-type {
  font-size: 0.75rem;
  padding: 0.08rem 0.42rem;
  border-radius: 999px;
  background: var(--vp-c-default-soft, #eef);
  color: var(--vp-c-text-2, #555);
  line-height: 1.45;
}
.se-summary {
  font-size: 0.9rem;
  color: var(--vp-c-text-2, #555);
  flex: 1 1 100%;
  min-width: 0;
  overflow-wrap: anywhere;
}
.se-error {
  color: #c0392b;
  font-weight: 600;
}
.se-error-detail {
  font-weight: 400;
  color: var(--vp-c-text-2, #555);
}
.se-empty {
  color: var(--vp-c-text-2, #555);
  font-style: italic;
}

@media (max-width: 720px) {
  .se-controls,
  .se-controls input[type='search'],
  .se-controls select,
  .se-button {
    width: 100%;
  }

  .se-controls input[type='search'] {
    min-width: 0;
  }
}
</style>
