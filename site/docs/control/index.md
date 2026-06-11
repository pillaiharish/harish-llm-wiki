---
title: Control Plane
---

# Control Plane

Use this page to inspect local provider/model configuration through a local-only
control plane. The static site does not store secrets, test API keys directly, or
run provider calls from the browser.

<ClientOnly>
  <ControlPlaneStatus />
</ClientOnly>

## Start Locally

Run this from the nested repo:

```bash
.venv/bin/python -m wiki control-plane --host 127.0.0.1 --port 8765
```

The control plane defaults to loopback-only access. Binding it to a LAN address
requires `--unsafe-lan` and should only be used on trusted networks.
