<script setup lang="ts">
import { computed, ref } from 'vue'

type InputMode = 'url' | 'batch'
type Provider = 'mock' | 'ollama_local' | 'ollama_cloud' | 'openai_compatible'

type CommandSection = {
  id: string
  title: string
  command: string
  note?: string
}

const inputMode = ref<InputMode>('url')
const url = ref('https://example.com/article')
const batchFile = ref('inputs/batch_urls.example.txt')
const provider = ref<Provider>('mock')
const processDryRun = ref(false)
const onlyStale = ref(false)
const skipIngest = ref(false)
const confirmCloudRun = ref(false)
const rebuildSite = ref(true)
const validateAfterBuild = ref(true)
const copiedId = ref('')

const cloudProviders: Provider[] = ['ollama_cloud', 'openai_compatible']

const providerLabel = computed(() => {
  if (provider.value === 'mock') return 'Mock provider'
  if (provider.value === 'ollama_local') return 'Ollama local'
  if (provider.value === 'ollama_cloud') return 'Ollama Cloud'
  return 'OpenAI-compatible'
})

const isCloudProvider = computed(() => cloudProviders.includes(provider.value))

function quoteArg(value: string): string {
  const cleaned = value.replace(/\s+/g, ' ').trim()
  return `"${cleaned.replace(/(["\\$`])/g, '\\$1')}"`
}

function processFlags({ dryRun }: { dryRun: boolean }): string {
  const flags = ['process-new']
  if (dryRun) flags.push('--dry-run')
  if (onlyStale.value) flags.push('--only-stale')
  if (skipIngest.value) flags.push('--skip-ingest')
  flags.push('--provider', provider.value)
  if (isCloudProvider.value && !dryRun && confirmCloudRun.value) flags.push('--yes')
  return flags.join(' ')
}

const addInputCommand = computed(() => {
  if (inputMode.value === 'url') {
    return `.venv/bin/python -m wiki add-resource --url ${quoteArg(url.value)}`
  }
  return [
    `.venv/bin/python -m wiki add-batch --file ${quoteArg(batchFile.value)} --dry-run`,
    `.venv/bin/python -m wiki add-batch --file ${quoteArg(batchFile.value)}`,
  ].join('\n')
})

const previewCommand = computed(() => `.venv/bin/python -m wiki ${processFlags({ dryRun: true })}`)

const processCommand = computed(() => {
  const dryRun = processDryRun.value || (isCloudProvider.value && !confirmCloudRun.value)
  return `.venv/bin/python -m wiki ${processFlags({ dryRun })}`
})

const processRunsForReal = computed(() => !processCommand.value.includes('--dry-run'))

const commandSections = computed<CommandSection[]>(() => {
  const sections: CommandSection[] = [
    {
      id: 'add-input',
      title: inputMode.value === 'url' ? 'Add one URL' : 'Preview and add batch',
      command: addInputCommand.value,
      note:
        inputMode.value === 'url'
          ? 'add-resource currently has no --dry-run flag.'
          : 'Batch mode supports a dry-run before adding resources.',
    },
    {
      id: 'preview-processing',
      title: 'Preview processing',
      command: previewCommand.value,
      note: 'Always dry-run; this command should not write notes or call a real provider for processing.',
    },
    {
      id: 'process',
      title: processRunsForReal.value ? 'Process resources' : 'Process command is still dry-run',
      command: processCommand.value,
      note:
        isCloudProvider.value && !confirmCloudRun.value
          ? 'Cloud providers stay in dry-run mode until you explicitly confirm a real provider run.'
          : 'Run from the nested repo root.',
    },
  ]
  if (rebuildSite.value) {
    sections.push({
      id: 'build-site',
      title: 'Refresh generated site',
      command: '.venv/bin/python -m wiki build-site --refresh',
    })
  }
  if (validateAfterBuild.value) {
    sections.push({
      id: 'validate',
      title: 'Validate before sharing',
      command: [
        '.venv/bin/python -m pytest',
        '.venv/bin/python -m wiki smoke-site',
        '.venv/bin/python -m wiki validate',
      ].join('\n'),
    })
  }
  return sections
})

const allCommands = computed(() => commandSections.value.map((section) => section.command).join('\n\n'))

const providerNote = computed(() => {
  if (provider.value === 'mock') return 'Mock mode uses deterministic local output and no cloud tokens.'
  if (provider.value === 'ollama_local') return 'Ollama local mode uses your local Ollama server and no cloud tokens.'
  if (provider.value === 'ollama_cloud') return 'Ollama Cloud uses local .env API keys only when you run CLI commands.'
  return 'OpenAI-compatible mode uses local .env endpoint, key, and model settings only when you run CLI commands.'
})

async function copyText(id: string, text: string): Promise<void> {
  copiedId.value = ''
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      copiedId.value = id
      window.setTimeout(() => {
        if (copiedId.value === id) copiedId.value = ''
      }, 1400)
    }
  } catch {
    copiedId.value = ''
  }
}
</script>

<template>
  <section class="ingest-builder" data-testid="ingest-command-builder" aria-labelledby="ingest-builder-title">
    <div class="ingest-builder-header">
      <div>
        <p class="wiki-muted">Static command builder</p>
        <h2 id="ingest-builder-title">Build a local ingest command flow</h2>
      </div>
      <button class="ingest-copy-all" type="button" @click="copyText('all', allCommands)">
        {{ copiedId === 'all' ? 'Copied' : 'Copy all' }}
      </button>
    </div>

    <div class="ingest-builder-grid">
      <form class="ingest-builder-panel" aria-label="Command builder controls">
        <fieldset>
          <legend>Input</legend>
          <label class="ingest-radio">
            <input v-model="inputMode" type="radio" value="url" />
            One URL
          </label>
          <label class="ingest-radio">
            <input v-model="inputMode" type="radio" value="batch" />
            Batch file
          </label>
          <div class="ingest-disabled-option" data-testid="ingest-yaml-reference">
            <strong>YAML resource manifest</strong>
            <span>Reference only. No YAML import CLI exists yet.</span>
          </div>
        </fieldset>

        <label v-if="inputMode === 'url'" class="ingest-field">
          URL
          <input v-model="url" data-testid="ingest-url-input" type="url" autocomplete="off" />
        </label>
        <label v-else class="ingest-field">
          Batch file path
          <input v-model="batchFile" data-testid="ingest-batch-input" type="text" autocomplete="off" />
        </label>

        <label class="ingest-field">
          Provider
          <select v-model="provider" data-testid="ingest-provider-select">
            <option value="mock">mock</option>
            <option value="ollama_local">ollama_local</option>
            <option value="ollama_cloud">ollama_cloud</option>
            <option value="openai_compatible">openai_compatible</option>
          </select>
        </label>

        <div class="ingest-token-note" :class="{ 'is-cloud': isCloudProvider }" data-testid="ingest-token-note">
          <strong>{{ providerLabel }}</strong>
          <span>{{ providerNote }}</span>
        </div>

        <fieldset>
          <legend>Processing flags</legend>
          <label class="ingest-check">
            <input v-model="processDryRun" type="checkbox" />
            Keep process command as dry-run
          </label>
          <label class="ingest-check">
            <input v-model="onlyStale" type="checkbox" />
            Add --only-stale
          </label>
          <label class="ingest-check">
            <input v-model="skipIngest" type="checkbox" />
            Add --skip-ingest
          </label>
          <label class="ingest-check">
            <input v-model="rebuildSite" type="checkbox" />
            Rebuild site
          </label>
          <label class="ingest-check">
            <input v-model="validateAfterBuild" type="checkbox" />
            Validate after build
          </label>
        </fieldset>

        <label v-if="isCloudProvider" class="ingest-cloud-confirm">
          <input v-model="confirmCloudRun" data-testid="ingest-cloud-confirm" type="checkbox" />
          I understand this can use local .env API tokens when I run the CLI.
        </label>
      </form>

      <div class="ingest-command-preview" aria-live="polite">
        <article
          v-for="section in commandSections"
          :key="section.id"
          class="ingest-generated-command wiki-card"
          :data-testid="`ingest-command-${section.id}`"
        >
          <div class="ingest-command-title">
            <h3>{{ section.title }}</h3>
            <button type="button" @click="copyText(section.id, section.command)">
              {{ copiedId === section.id ? 'Copied' : 'Copy' }}
            </button>
          </div>
          <pre class="ingest-command"><code>{{ section.command }}</code></pre>
          <p v-if="section.note" class="wiki-muted">{{ section.note }}</p>
        </article>
      </div>
    </div>

    <div class="ingest-yaml-note wiki-card">
      <h3>YAML manifest is reference-only</h3>
      <p>
        <code>inputs/resources.example.yaml</code> documents a possible manifest shape, but this repo
        currently does not provide a YAML import CLI. Use <code>add-resource</code> for one URL or
        <code>add-batch</code> for URL lists.
      </p>
    </div>
  </section>
</template>
