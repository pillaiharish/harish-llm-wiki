<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

type ProviderSummary = {
  provider: string
  label: string
  tokenKind: string
  configured: boolean
  keyPresent: boolean
  modelConfigured: boolean
  configuredModel: string
  metadataEndpoint?: string | null
}

type CheckResult = {
  provider: string
  checkedAt: string
  configured: boolean
  keyPresent: boolean
  modelConfigured: boolean
  configuredModel: string
  availableModels: string[]
  modelAvailable: boolean | null
  connectivity: 'ok' | 'failed' | 'unknown'
  ok: boolean
  error?: { type: string; message: string } | null
  message: string
}

type ModelSummary = {
  provider: string
  configuredModel: string
  modelConfigured: boolean
  availableModels: string[]
  metadataAvailable: boolean
}

type ProcessingRun = {
  run_id: string
  resource_id: string
  operation: string
  provider: string
  model: string
  status: string
  completed_at: string
  total_tokens: number
  usage_source: string
  estimated_cost: number
}

type TokenSummary = {
  run_count: number
  ledger_entry_count: number
  success_count: number
  failed_count: number
  cache_hit_count: number
  total_tokens: number
  estimated_cost: number
  by_provider: Record<string, { entries: number; total_tokens: number; estimated_cost: number }>
}

const CONTROL_ORIGIN = 'http://127.0.0.1:8765'

const loading = ref(true)
const unavailable = ref(false)
const status = ref<any | null>(null)
const providers = ref<ProviderSummary[]>([])
const models = ref<ModelSummary[]>([])
const runs = ref<ProcessingRun[]>([])
const tokenSummary = ref<TokenSummary | null>(null)
const checkResults = ref<Record<string, CheckResult>>({})
const checkingProvider = ref('')
const lastError = ref('')

const providerCards = computed(() => providers.value.length ? providers.value : [])
const providerBreakdown = computed(() => Object.entries(tokenSummary.value?.by_provider || {}))

async function fetchJson(path: string, options: RequestInit = {}) {
  const headers: Record<string, string> = { ...(options.headers as Record<string, string> | undefined) }
  if (options.body) headers['Content-Type'] = 'application/json'
  const response = await fetch(`${CONTROL_ORIGIN}${path}`, {
    cache: 'no-store',
    ...options,
    headers,
  })
  if (!response.ok) {
    throw new Error(`Control plane returned HTTP ${response.status}`)
  }
  return response.json()
}

function configuredModelFor(provider: string): string {
  const model = models.value.find((item) => item.provider === provider)
  return model?.configuredModel || ''
}

async function loadControlPlane() {
  loading.value = true
  unavailable.value = false
  lastError.value = ''
  try {
    const [statusPayload, providerPayload, modelPayload, runPayload, tokenPayload] = await Promise.all([
      fetchJson('/api/status'),
      fetchJson('/api/providers'),
      fetchJson('/api/models'),
      fetchJson('/api/runs'),
      fetchJson('/api/token-ledger/summary'),
    ])
    status.value = statusPayload
    providers.value = providerPayload.providers || []
    models.value = modelPayload.models || []
    runs.value = runPayload.runs || []
    tokenSummary.value = tokenPayload.summary || runPayload.summary || null
  } catch (error) {
    unavailable.value = true
    providers.value = []
    models.value = []
    runs.value = []
    tokenSummary.value = null
    status.value = null
    lastError.value = error instanceof Error ? error.message : 'Control plane unavailable.'
  } finally {
    loading.value = false
  }
}

async function checkProvider(provider: string) {
  checkingProvider.value = provider
  try {
    const result = await fetchJson('/api/providers/check', {
      method: 'POST',
      body: JSON.stringify({ provider }),
    }) as CheckResult
    checkResults.value = { ...checkResults.value, [provider]: result }
  } catch (error) {
    checkResults.value = {
      ...checkResults.value,
      [provider]: {
        provider,
        checkedAt: new Date().toISOString(),
        configured: false,
        keyPresent: false,
        modelConfigured: false,
        configuredModel: '',
        availableModels: [],
        modelAvailable: null,
        connectivity: 'failed',
        ok: false,
        error: {
          type: 'request_error',
          message: error instanceof Error ? error.message : 'Check failed.',
        },
        message: 'Control-plane request failed.',
      },
    }
  } finally {
    checkingProvider.value = ''
  }
}

function statusLabel(result: CheckResult | undefined, provider: ProviderSummary): string {
  if (result) return result.connectivity
  if (!provider.configured) return 'not configured'
  return 'not checked'
}

function formatCost(value: number | undefined): string {
  return `$${Number(value || 0).toFixed(6)}`
}

function formatDate(value: string | undefined): string {
  if (!value) return 'unknown'
  return value.replace('T', ' ').replace(/\.\d+\+00:00$/, 'Z')
}

onMounted(() => {
  void loadControlPlane()
})
</script>

<template>
  <section class="control-plane" data-testid="control-plane">
    <div class="control-plane-header">
      <p class="wiki-muted">Local-only metadata checks</p>
      <h2>Provider control plane</h2>
      <p>
        This page connects only to <code>{{ CONTROL_ORIGIN }}</code>. It performs metadata-only
        checks and shows redacted provider and
        model status from a local process; it never asks the browser for API keys and never starts
        resource processing.
      </p>
      <button type="button" data-testid="control-plane-refresh" @click="loadControlPlane">
        Refresh status
      </button>
    </div>

    <div v-if="loading" class="control-plane-card">Checking local control plane...</div>

    <div v-else-if="unavailable" class="control-plane-card control-plane-unavailable" data-testid="control-plane-unavailable">
      <h3>Local control plane is not running</h3>
      <p>Start it from the nested repo, then refresh this page.</p>
      <pre><code>.venv/bin/python -m wiki control-plane --host 127.0.0.1 --port 8765</code></pre>
      <p class="wiki-muted">{{ lastError }}</p>
    </div>

    <div v-else class="control-plane-ready" data-testid="control-plane-ready">
      <div class="control-plane-status-grid">
        <section class="control-plane-card">
          <span class="wiki-chip">Running</span>
          <h3>Server</h3>
          <p><strong>URL:</strong> {{ CONTROL_ORIGIN }}</p>
          <p><strong>Version:</strong> {{ status?.version }}</p>
          <p><strong>Last checked:</strong> {{ status?.checkedAt }}</p>
        </section>
        <section class="control-plane-card">
          <span class="wiki-chip">Current config</span>
          <h3>Configured provider</h3>
          <p><strong>Provider:</strong> {{ status?.currentProvider?.provider }}</p>
          <p><strong>Model:</strong> {{ status?.currentProvider?.configuredModel || 'not configured' }}</p>
          <p><strong>Configured:</strong> {{ status?.currentProvider?.configured ? 'yes' : 'no' }}</p>
        </section>
      </div>

      <div class="control-provider-grid">
        <article
          v-for="provider in providerCards"
          :key="provider.provider"
          class="control-plane-card control-provider-card"
          :data-testid="`control-provider-${provider.provider}`"
        >
          <div class="control-provider-heading">
            <div>
              <span class="wiki-chip">{{ provider.tokenKind === 'cloud' ? 'cloud config' : 'no cloud tokens' }}</span>
              <h3>{{ provider.label }}</h3>
            </div>
            <span
              class="control-status-pill"
              :class="`is-${checkResults[provider.provider]?.connectivity || 'pending'}`"
            >
              {{ statusLabel(checkResults[provider.provider], provider) }}
            </span>
          </div>

          <dl class="control-provider-facts">
            <div>
              <dt>Configured</dt>
              <dd>{{ provider.configured ? 'yes' : 'no' }}</dd>
            </div>
            <div>
              <dt>Key present</dt>
              <dd>{{ provider.keyPresent ? 'yes' : 'no' }}</dd>
            </div>
            <div>
              <dt>Model</dt>
              <dd>{{ configuredModelFor(provider.provider) || provider.configuredModel || 'not configured' }}</dd>
            </div>
            <div>
              <dt>Metadata</dt>
              <dd>{{ provider.metadataEndpoint || 'not available' }}</dd>
            </div>
          </dl>

          <button
            type="button"
            :data-testid="`control-check-${provider.provider}`"
            :disabled="checkingProvider === provider.provider"
            @click="checkProvider(provider.provider)"
          >
            {{ checkingProvider === provider.provider ? 'Checking...' : 'Check metadata' }}
          </button>

          <div
            v-if="checkResults[provider.provider]"
            class="control-check-result"
            :data-testid="`control-result-${provider.provider}`"
          >
            <p>{{ checkResults[provider.provider].message }}</p>
            <p v-if="checkResults[provider.provider].modelAvailable !== null">
              Model available:
              {{ checkResults[provider.provider].modelAvailable ? 'yes' : 'no' }}
            </p>
            <p v-if="checkResults[provider.provider].error" class="control-error">
              {{ checkResults[provider.provider].error?.type }}:
              {{ checkResults[provider.provider].error?.message }}
            </p>
          </div>
        </article>
      </div>

      <section class="control-runs-panel control-plane-card" data-testid="control-runs-panel">
        <div class="control-provider-heading">
          <div>
            <span class="wiki-chip">Read-only accounting</span>
            <h3>Processing runs and token ledger</h3>
          </div>
          <span class="control-status-pill is-ok">
            {{ tokenSummary?.run_count || 0 }} runs
          </span>
        </div>

        <div
          v-if="tokenSummary && tokenSummary.run_count > 0"
          class="control-run-summary"
          data-testid="control-runs-summary"
        >
          <div>
            <strong>{{ tokenSummary.run_count }}</strong>
            <span>Runs</span>
          </div>
          <div>
            <strong>{{ tokenSummary.success_count }}</strong>
            <span>Successful</span>
          </div>
          <div>
            <strong>{{ tokenSummary.failed_count }}</strong>
            <span>Failed</span>
          </div>
          <div>
            <strong>{{ tokenSummary.cache_hit_count }}</strong>
            <span>Cache hits</span>
          </div>
          <div>
            <strong>{{ tokenSummary.total_tokens }}</strong>
            <span>Tokens</span>
          </div>
          <div>
            <strong>{{ formatCost(tokenSummary.estimated_cost) }}</strong>
            <span>Estimated cost</span>
          </div>
        </div>

        <div v-else class="control-empty-state" data-testid="control-runs-empty">
          <h4>No processing runs recorded yet</h4>
          <p>
            Process resources from the local CLI first. This page will then show
            run history, cache hits, token estimates, and provider/model totals.
          </p>
        </div>

        <div v-if="providerBreakdown.length" class="control-provider-breakdown">
          <h4>Provider breakdown</h4>
          <dl class="control-provider-facts">
            <div v-for="[provider, item] in providerBreakdown" :key="provider">
              <dt>{{ provider }}</dt>
              <dd>{{ item.total_tokens }} tokens / {{ item.entries }} entries</dd>
            </div>
          </dl>
        </div>

        <div v-if="runs.length" class="control-run-list" data-testid="control-run-list">
          <h4>Recent runs</h4>
          <article
            v-for="run in runs.slice(0, 8)"
            :key="run.run_id"
            class="control-run-row"
            :data-testid="`control-run-row-${run.status}`"
          >
            <div>
              <strong>{{ run.operation }}</strong>
              <span>{{ run.resource_id }}</span>
            </div>
            <div>
              <span class="wiki-chip">{{ run.status }}</span>
              <span>{{ run.provider }} / {{ run.model }}</span>
            </div>
            <div>
              <span>{{ run.total_tokens || 0 }} tokens</span>
              <span>{{ formatDate(run.completed_at) }}</span>
            </div>
          </article>
        </div>

        <div class="control-next-links">
          <a href="/ingest/">Ingest guide</a>
          <a href="/review/">Review queue</a>
          <a href="/resources/">Resources</a>
        </div>
      </section>
    </div>

    <p class="control-plane-boundary">
      Boundary: this page reads metadata, processing runs, and token ledger summaries. It does not
      call chat, completions, generate, or resource-processing endpoints.
    </p>
  </section>
</template>
