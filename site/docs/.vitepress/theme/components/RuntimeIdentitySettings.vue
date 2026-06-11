<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { withBase } from 'vitepress'

type RuntimeIdentityDefaults = {
  defaultOwnerName: string
  defaultSiteTitle: string
  allowBrowserOverride: boolean
}

const STORAGE_KEY = 'llmWiki.runtimeIdentity.v1'

const defaults = ref<RuntimeIdentityDefaults>({
  defaultOwnerName: 'Harish',
  defaultSiteTitle: 'Harish LLM Wiki',
  allowBrowserOverride: true,
})
const ownerName = ref('Harish')
const siteTitle = ref('Harish LLM Wiki')
const status = ref('')
const loaded = ref(false)

const storagePreview = computed(() =>
  JSON.stringify(
    {
      ownerName: ownerName.value.trim(),
      siteTitle: siteTitle.value.trim(),
    },
    null,
    2
  )
)

function cleanText(value: unknown, fallback: string): string {
  if (typeof value !== 'string') return fallback
  const trimmed = value.trim().replace(/\s+/g, ' ').slice(0, 80)
  return trimmed || fallback
}

async function loadDefaults(): Promise<void> {
  try {
    const response = await fetch(withBase('/site-branding.json'), { cache: 'no-store' })
    if (!response.ok) return
    const payload = (await response.json()) as Partial<RuntimeIdentityDefaults>
    defaults.value = {
      defaultOwnerName: cleanText(payload.defaultOwnerName, defaults.value.defaultOwnerName),
      defaultSiteTitle: cleanText(payload.defaultSiteTitle, defaults.value.defaultSiteTitle),
      allowBrowserOverride: payload.allowBrowserOverride !== false,
    }
  } catch {
    status.value = 'Using built-in defaults because the public branding file could not be loaded.'
  }
}

function loadCurrentOverride(): void {
  if (typeof window === 'undefined') return
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) {
      ownerName.value = defaults.value.defaultOwnerName
      siteTitle.value = defaults.value.defaultSiteTitle
      return
    }
    const parsed = JSON.parse(raw) as { ownerName?: string; siteTitle?: string }
    ownerName.value = cleanText(parsed.ownerName, defaults.value.defaultOwnerName)
    siteTitle.value = cleanText(parsed.siteTitle, defaults.value.defaultSiteTitle)
  } catch {
    ownerName.value = defaults.value.defaultOwnerName
    siteTitle.value = defaults.value.defaultSiteTitle
  }
}

function notifyRuntimeProvider(): void {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent('llm-wiki-runtime-identity-change'))
}

function saveOverride(): void {
  if (typeof window === 'undefined' || !defaults.value.allowBrowserOverride) return
  const payload = {
    ownerName: cleanText(ownerName.value, defaults.value.defaultOwnerName),
    siteTitle: cleanText(siteTitle.value, defaults.value.defaultSiteTitle),
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
  ownerName.value = payload.ownerName
  siteTitle.value = payload.siteTitle
  status.value = 'Browser-local display override saved.'
  notifyRuntimeProvider()
}

function resetToDefaults(): void {
  ownerName.value = defaults.value.defaultOwnerName
  siteTitle.value = defaults.value.defaultSiteTitle
  if (typeof window !== 'undefined') window.localStorage.removeItem(STORAGE_KEY)
  status.value = 'Generated defaults restored for this browser.'
  notifyRuntimeProvider()
}

function clearOverride(): void {
  if (typeof window !== 'undefined') window.localStorage.removeItem(STORAGE_KEY)
  ownerName.value = defaults.value.defaultOwnerName
  siteTitle.value = defaults.value.defaultSiteTitle
  status.value = 'Browser override cleared.'
  notifyRuntimeProvider()
}

onMounted(async () => {
  await loadDefaults()
  loadCurrentOverride()
  loaded.value = true
  notifyRuntimeProvider()
})
</script>

<template>
  <section class="runtime-settings" data-testid="runtime-identity-settings">
    <div class="runtime-settings-header">
      <p class="wiki-muted">Browser-local display settings</p>
      <h2>Runtime identity</h2>
      <p>
        Change how the site title and owner name appear in this browser. These settings are
        presentation-only, stay in localStorage, and never store API keys, provider tokens, or
        model credentials.
      </p>
    </div>

    <div v-if="!loaded" class="runtime-settings-card">
      Loading generated defaults...
    </div>

    <div v-else class="runtime-settings-grid">
      <form class="runtime-settings-card" @submit.prevent="saveOverride">
        <label class="runtime-settings-field">
          Owner / display name
          <input
            v-model="ownerName"
            data-testid="runtime-owner-input"
            type="text"
            autocomplete="off"
            maxlength="80"
            :disabled="!defaults.allowBrowserOverride"
          />
        </label>

        <label class="runtime-settings-field">
          Site title
          <input
            v-model="siteTitle"
            data-testid="runtime-title-input"
            type="text"
            autocomplete="off"
            maxlength="80"
            :disabled="!defaults.allowBrowserOverride"
          />
        </label>

        <div class="runtime-settings-actions">
          <button
            class="runtime-settings-primary"
            data-testid="runtime-save"
            type="submit"
            :disabled="!defaults.allowBrowserOverride"
          >
            Save browser override
          </button>
          <button data-testid="runtime-reset" type="button" @click="resetToDefaults">
            Reset to generated defaults
          </button>
          <button data-testid="runtime-clear" type="button" @click="clearOverride">
            Clear browser override
          </button>
        </div>

        <p class="runtime-settings-status" data-testid="runtime-status" aria-live="polite">
          {{ status || 'No browser override has been saved yet.' }}
        </p>
      </form>

      <aside class="runtime-settings-card runtime-settings-preview">
        <h3>Preview</h3>
        <dl>
          <div>
            <dt>Owner</dt>
            <dd data-testid="runtime-preview-owner">{{ ownerName }}</dd>
          </div>
          <div>
            <dt>Site title</dt>
            <dd data-testid="runtime-preview-title">{{ siteTitle }}</dd>
          </div>
          <div>
            <dt>Storage key</dt>
            <dd><code>{{ STORAGE_KEY }}</code></dd>
          </div>
        </dl>
        <pre data-testid="runtime-storage-preview">{{ storagePreview }}</pre>
      </aside>
    </div>

    <div class="runtime-settings-note">
      <strong>Launch-wide defaults:</strong>
      run <code>.venv/bin/python -m wiki configure-site --owner-name "Your Name" --title "Your Wiki"</code>
      from the nested repo, then rebuild with <code>.venv/bin/python -m wiki build-site --refresh</code>.
    </div>
  </section>
</template>
