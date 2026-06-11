---
title: Settings
---

# Settings

Use this page for browser-local display preferences. It does not upload files,
store browser-side secrets, request API keys, test providers, run models, or
change generated resource data.

<ClientOnly>
  <RuntimeIdentitySettings />
</ClientOnly>

## What This Changes

- The visible site title in this browser.
- The visible owner/display name in this browser.
- The browser tab title when VitePress includes the generated site title.

## What This Does Not Change

- `.env` provider configuration.
- API keys or provider tokens.
- LLM model selection.
- Generated notes, graph data, search indexes, or resource metadata.

For launch-wide defaults, run:

```bash
.venv/bin/python -m wiki configure-site --owner-name "Your Name" --title "Your Wiki"
.venv/bin/python -m wiki build-site --refresh
```
