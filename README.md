<img width="3397" height="1298" alt="uran" src="https://github.com/user-attachments/assets/b664f362-4412-4bb6-9924-6121a6eecb10" />

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) companion plugin for [ASSella](https://github.com/niwia/ASSella).

Registers Steam games into SLSsteam using ASSella's **AT0-M** (Steam native download) mode, manages your AT0-M library, and shares one Hubcap API key with ASSella.

Designed for public use: connects directly to the [Hubcap API](https://hubcapmanifest.com) and reads/writes the same files ASSella does, so both tools stay in sync.

---

## Features

### Game Search & Injection
- **Steam Store & App ID Search**: Search any Steam game by title or exact AppID.
- **AT0-M Injection**: Registers the AppID, its depots and its decryption keys into `config.yaml` in a single atomic pass — the same way ASSella's AT0-M mode does.
  - Only depots that have a key (or are Steamworks shared redistributables) are registered, so Steam never fails with `DepotWithoutKey`.
  - Every entry is tagged with the game name so ASSella can attribute it during cleanup.
- **Shared Registry**: Writes the same `plugin_library.json` record ASSella uses, so injected games appear in ASSella's AT0-M library.
- **Steam Store Page Button**: Injected via CDP into the Steam Deck Store webview. Settings checks whether Steam's CEF debugging port is open and shows recent injection logs.
- **Instant Hot Reloading**: Emits signals to `/tmp/SLSsteam.API` (`RELOAD`) for zero-restart configuration updates.

### AT0-M Library Manager
- **Game List**: Every game registered in AT0-M mode, with install state and size. Click a game to open its page.
- **Per-game AppIDs**: the base game is always included; toggle each DLC to add or remove the depots and keys it owns. Toggling one off removes exactly what toggling it on added — no leftover entries.
- **Refresh Keys & Depots**: re-checks Hubcap and rewrites the game's depots and keys in one pass, so a key that arrives after the game was added gets the depot it mounts (a plain manifest update only writes the key).
- **Per-game integrations**:
  - **SLSonline** — maps the game to Spacewar (480) via `FakeAppIds`.
  - **NetSock** — Steam Networking Sockets patch via `LaunchOptions` (`env LD_AUDIT=…`).
  - **EOS Proxy** — applies the Epic Online Services proxy DLL.
  - **EOS + NetSock** — enables both together.
- **Uninstall** (with confirmation): removes game files, Steam metadata (`appmanifest`, `downloading`, `temp`, `compatdata`) and every trace from `config.yaml` and `plugin_library.json`. Shared redistributables are always left alone.

### Hubcap API Key
- **Shared with ASSella**: the key lives in Assella's own config, so both tools always use the same key.
- **QR code entry**: no keyboard needed — show a QR code, scan it with your phone, paste the key on a small local web page served by the Deck. The key is validated against Hubcap before it is saved. The page is token-protected and closes automatically.
- **Account stats**: shows your Hubcap username, remaining requests today, and key expiry.

### Hubcap Manifests & Depot Keys
- **Public Hubcap API**: fetches the game manifest bundle for an AppID.
- **Route selection**: Settings → Hubcap Connection picks how Uran reaches the API.
  - *Automatic* (default) — try direct first; on a blocked route, retry once through the edge proxy.
  - *Direct only* — never use the proxy.
  - *Edge proxy only* — skip the direct route entirely.
  The fallback fires only on transport-level failures (DNS, refused, reset, TLS interception). HTTP-level problems — rate limits, bad keys, missing bundles — are surfaced to you as-is and never retried elsewhere, since a second host would only double-burn quota or hide the real error.
- **Route feedback**: the panel shows whether each route is currently reachable, whether the proxy fallback is in use, and the last connection detail. "Test Connection" probes both routes on demand.
- **Automatic key harvesting**: parses the bundle's `.lua` (`addappid`) — comment-aware, so depots Hubcap disabled (`-- addappid(…, "MISSING_KEY")`) are ignored, matching ASSella's parser exactly.
- **Depotcache pre-seeding**: extracts `.manifest` files into Steam's `depotcache/`.
- **Manifest pinning**: optional `ManifestIds` pins in `config.yaml`.

### Library Menus
- **Game context menu hooks** in Steam's "Manage" submenu: Add/Remove FakeAppId (480), Fetch DLCs, Fetch/Update Manifest, Remove Pinned Manifests, Why not downloading?

---

## Requirements

- SteamOS / Linux with [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)
- [SLSsteam](https://github.com/AceSLS/SLSsteam) installed
- (Optional) [ASSella](https://github.com/niwia/ASSella) desktop installation
- A [Hubcap API](https://hubcapmanifest.com) key

---

## Tabs

1. **Search** — search games, inject into SLSsteam, view recent injects.
2. **AT0-M** — manage your AT0-M library: per-game integrations and uninstall.
3. **Settings** — Hubcap key, Steam Store status and logs, manifest pinning, and notifications.

---

## Building from source

```bash
git clone https://github.com/niwia/Uran
cd Uran
npm ci
npm run build
./devinstall.sh
```

Use `npm ci && npm run package` to create the installable `Uran.zip`. In Settings → Steam Store, check whether CEF debugging is detected and read the recent patch logs. The button cannot be injected when Steam's debugging port is closed; Steam needs to be launched with `--cef-enable-debugging`. A detected port still cannot guarantee compatibility with Valve's current Store page layout.

`dist/` is not committed. GitHub Actions runs `npm run package`, which builds the
frontend before zipping. To run or test the plugin straight from a local clone, build
the frontend yourself first:

```bash
npm ci
npm run build     # required once after checkout, and after any src/ change
./devinstall.sh
```

Declaring the plugin from the repo without `dist/` will load a stale or missing
bundle, because Decky reads `dist/index.js` from the installed directory.

`plugin.json` is the single source of truth for the version. `python3 check_version.py`
verifies that `package.json` agrees with it, and CI runs that check on every build.

---

## Updates

Uran does not install updates itself. Settings → Check for Updates compares the
installed version against the latest GitHub release and shows whether an update
is available. Installing is left to Decky Loader (menu → Plugins → Uran →
Update), which already tracks a plugin's releases — so there is no second code
path writing to the plugin directory.

---

## Backend layout

`main.py` is a composition root only: it imports `Plugin` and gets out of the
way. All behaviour lives in `uran_backend/`, where each module owns one concern
and receives its collaborators explicitly:

| Module | Responsibility |
| --- | --- |
| `context.py` | Environment discovery; the `Context` every service receives |
| `services.py` | Builds the service graph |
| `plugin_api.py` | The Decky RPC surface — method names are the plugin's contract |
| `http.py` | `requests`, or a urllib shim when Decky has no `requests` |
| `paths.py` | SLSsteam / Steam / ACCELA path discovery and shared INI edits |
| `settings.py` | Plugin settings and the shared Hubcap key |
| `hubcap.py` | Hubcap API client and the blocked-route proxy fallback |
| `sls_config.py` | Comment- and inode-preserving YAML engine |
| `library.py` | `plugin_library.json` registry and the local depot key cache |
| `manifests.py` | Hubcap bundle download, depotcache seeding, manifest pins |
| `manifest_lua.py` | Comment-aware parsing of Hubcap's Lua |
| `inject.py` | Injection into `config.yaml` and DLC handling |
| `integrations.py` | SLSonline, NetSock and the EOS proxy |
| `atom.py` | The AT0-M library read model |
| `guards.py` | Environment and already-registered preflight checks |
| `keycare.py` | LAN key capture server and Hubcap key management |
| `steam_store.py` | CEF debugging discovery and Store patch diagnostics |
| `uninstall.py` | AT0-M uninstall |
| `updates.py` | Version and release check |

There are no module-level service singletons or `bind_core` magic: a renamed
dependency fails at import time rather than on a user's Deck.

Decky does not bundle third-party Python packages, so `http.py` falls back to a
stdlib urllib shim. The shim mirrors the slice of the `requests` API used here,
including its exception namespace.

---

## Tests

```bash
npm test          # or: python3 tests/run_all.py
```

No framework and no dependencies — each file is runnable directly. The suite
covers the code where a silent mistake damages a user's config: the
comment-preserving YAML engine, the comment-aware Lua parser, and the
blocked-route fallback classifier.

---

## License

MIT License.
