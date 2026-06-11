<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted } from 'vue'
import { withBase } from 'vitepress'

type RuntimeIdentityDefaults = {
  schemaVersion?: string
  defaultOwnerName: string
  defaultSiteTitle: string
  allowBrowserOverride: boolean
}

type RuntimeIdentityOverride = {
  ownerName?: string
  siteTitle?: string
}

type RuntimeIdentity = {
  ownerName: string
  siteTitle: string
}

const STORAGE_KEY = 'llmWiki.runtimeIdentity.v1'
const fallbackDefaults: RuntimeIdentityDefaults = {
  schemaVersion: 'runtime_identity_v1',
  defaultOwnerName: 'Harish',
  defaultSiteTitle: 'Harish LLM Wiki',
  allowBrowserOverride: true,
}

let defaults: RuntimeIdentityDefaults = fallbackDefaults
let lastApplied: RuntimeIdentity | null = null
let observer: MutationObserver | null = null
let scheduledApply: number | null = null
let mounted = false

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
    defaults = {
      schemaVersion: 'runtime_identity_v1',
      defaultOwnerName: cleanText(payload.defaultOwnerName, fallbackDefaults.defaultOwnerName),
      defaultSiteTitle: cleanText(payload.defaultSiteTitle, fallbackDefaults.defaultSiteTitle),
      allowBrowserOverride: payload.allowBrowserOverride !== false,
    }
  } catch {
    defaults = fallbackDefaults
  }
}

function readOverride(): RuntimeIdentityOverride {
  if (!defaults.allowBrowserOverride || typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as RuntimeIdentityOverride
    return {
      ownerName: cleanText(parsed.ownerName, defaults.defaultOwnerName),
      siteTitle: cleanText(parsed.siteTitle, defaults.defaultSiteTitle),
    }
  } catch {
    return {}
  }
}

function activeIdentity(): RuntimeIdentity {
  const override = readOverride()
  return {
    ownerName: cleanText(override.ownerName, defaults.defaultOwnerName),
    siteTitle: cleanText(override.siteTitle, defaults.defaultSiteTitle),
  }
}

function shouldReplace(current: string | null | undefined, fallback: string, previous?: string): boolean {
  const text = (current || '').trim()
  return text === fallback || (Boolean(previous) && text === previous)
}

function applyIdentity(): void {
  if (typeof document === 'undefined' || typeof window === 'undefined') return
  const identity = activeIdentity()
  const previousTitle = lastApplied?.siteTitle

  document.documentElement.dataset.runtimeOwnerName = identity.ownerName
  document.documentElement.dataset.runtimeSiteTitle = identity.siteTitle

  if (document.title.includes(defaults.defaultSiteTitle)) {
    document.title = document.title.replaceAll(defaults.defaultSiteTitle, identity.siteTitle)
  } else if (previousTitle && document.title.includes(previousTitle)) {
    document.title = document.title.replaceAll(previousTitle, identity.siteTitle)
  }

  const navTitle = document.querySelector<HTMLElement>('.VPNavBarTitle .title span')
  if (navTitle && navTitle.textContent?.trim() !== identity.siteTitle) {
    navTitle.textContent = identity.siteTitle
  }

  const heroName = document.querySelector<HTMLElement>('.VPHero .name')
  if (
    heroName &&
    shouldReplace(heroName.textContent, defaults.defaultSiteTitle, previousTitle) &&
    heroName.textContent?.trim() !== identity.siteTitle
  ) {
    heroName.textContent = identity.siteTitle
  }

  const footerMessage = document.querySelector<HTMLElement>('.VPFooter .message')
  if (footerMessage) {
    const current = footerMessage.textContent || ''
    if (
      current.includes(defaults.defaultSiteTitle) ||
      (previousTitle && current.includes(previousTitle)) ||
      /^Generated with /.test(current.trim())
    ) {
      const nextMessage = `Generated with ${identity.siteTitle}`
      if (footerMessage.textContent !== nextMessage) {
        footerMessage.textContent = nextMessage
      }
    }
  }

  lastApplied = identity
  window.dispatchEvent(
    new CustomEvent('llm-wiki-runtime-identity-applied', {
      detail: {
        ownerName: identity.ownerName,
        siteTitle: identity.siteTitle,
        allowBrowserOverride: defaults.allowBrowserOverride,
      },
    })
  )
}

function scheduleApply(): void {
  if (!mounted || typeof window === 'undefined') return
  if (scheduledApply !== null) window.clearTimeout(scheduledApply)
  scheduledApply = window.setTimeout(() => {
    scheduledApply = null
    void nextTick(() => applyIdentity())
  }, 30)
}

async function refreshIdentity(): Promise<void> {
  await loadDefaults()
  scheduleApply()
}

onMounted(() => {
  mounted = true
  void refreshIdentity()

  window.addEventListener('storage', scheduleApply)
  window.addEventListener('llm-wiki-runtime-identity-change', scheduleApply)
  window.addEventListener('popstate', scheduleApply)
  window.addEventListener('hashchange', scheduleApply)

  observer = new MutationObserver(scheduleApply)
  if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true })
  }
})

onBeforeUnmount(() => {
  mounted = false
  if (scheduledApply !== null && typeof window !== 'undefined') {
    window.clearTimeout(scheduledApply)
  }
  scheduledApply = null
  observer?.disconnect()
  observer = null
  if (typeof window !== 'undefined') {
    window.removeEventListener('storage', scheduleApply)
    window.removeEventListener('llm-wiki-runtime-identity-change', scheduleApply)
    window.removeEventListener('popstate', scheduleApply)
    window.removeEventListener('hashchange', scheduleApply)
  }
})
</script>

<template>
  <span data-testid="runtime-identity-provider" hidden aria-hidden="true" />
</template>
