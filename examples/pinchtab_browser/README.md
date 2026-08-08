# pinchtab_browser

A single-agent example that **drives a real Chrome** through
[PinchTab](https://pinchtab.com/), a local browser-control daemon that speaks
MCP over stdio.

PinchTab reads pages as an accessibility tree with stable element refs
(`e0`, `e1`, …) rather than screenshots, so page state costs roughly a few
hundred tokens instead of an image. The agent clicks refs, not CSS selectors or
pixel coordinates.

## Layout

```
pinchtab_browser/
├── config.yaml                    # the agent (claude-sdk brain, no model pinned)
└── tools/mcp/pinchtab.yaml        # MCP server — auto-discovered, exposes the pinchtab_* tools
```

No core-engine changes: the server is reached through omnigent's standard
`tools/mcp/*.yaml` auto-discovery, the sanctioned extension point.

## Operator setup

### 1. Install PinchTab

```bash
curl -fsSL https://pinchtab.com/install.sh | bash
# or
brew install pinchtab/tap/pinchtab
```

### 2. Generate the local config and token

```bash
pinchtab config init      # writes the config and mints server.token
```

The default config binds the daemon to `127.0.0.1` and requires a bearer token.
**Leave both alone.** PinchTab's dashboard, HTTP API, and MCP bridge are
explicitly *not* built for untrusted users, multi-tenant use, or public-internet
exposure — a non-loopback `server.bind` hands whoever can reach the port a
browser running as you, with your cookies and sessions.

### 3. Start the daemon

```bash
pinchtab daemon install   # runs it as a background service

# sanity check — the API answers only on loopback, and only with the token
curl -H "Authorization: Bearer $(pinchtab config token)" http://127.0.0.1:9867/health
```

### 4. Export the token, then run the agent

```bash
export PINCHTAB_TOKEN="$(pinchtab config token)"
omnigent run examples/pinchtab_browser/
```

`tools/mcp/pinchtab.yaml` reads the token from `PINCHTAB_TOKEN` — the repo never
holds a credential. If the variable is unset, the bundle fails to load with an
unresolved-variable error rather than starting up unauthenticated.

Keep the token out of your shell history and out of committed files: prefer the
command substitution above (or a secret manager) over pasting the literal value.

### Optional: a different daemon target

`PINCHTAB_SERVER` in `tools/mcp/pinchtab.yaml` points at
`http://127.0.0.1:9867`, PinchTab's default control-plane port. Change it only
if you moved the local daemon's port. Pointing it at a remote host is out of
scope for this example and unsupported by PinchTab's security model.

## Tool namespace

PinchTab's tools are all namespaced `pinchtab_*` (`pinchtab_navigate`,
`pinchtab_snapshot`, `pinchtab_click`, `pinchtab_type`, `pinchtab_get_text`,
the `pinchtab_wait_for_*` family, …). They sit alongside — and never shadow —
omnigent's framework-owned `browser_*` built-ins, which drive the desktop app's
embedded browser instead.

## Safety notes

- The agent gets a browser with your real profile: logged-in sessions, cookies,
  saved payment methods. Treat a task as you would handing someone your laptop.
- PinchTab's IDPI defense restricts browsing to a local allowlist by default;
  widen it deliberately, per site, not globally.
- The bundle declares no `os_env`, so the agent has no local file or shell
  tools — the browser is its only reach.
