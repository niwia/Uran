# Uran

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
- **Steam Store Page Button**: Injected via CDP into the Steam Deck Store webview. Click "ADD TO ASSELLA" to register the game
- **Instant Hot Reloading**: Emits signals to `/tmp/SLSsteam.API` (`RELOAD`) for zero-restart configuration updates.

### AT0-M Library Manager
- **Game List**: Every game registered in AT0-M mode, with install state and size. Click a game to open its page.
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
- **Automatic key harvesting**: parses the bundle's `.lua` (`addappid`) — comment-aware, so depots Hubcap disabled (`-- addappid(…, "MISSING_KEY")`) are ignored, matching ASSella's parser exactly.
- **Depotcache pre-seeding**: extracts `.manifest` files into Steam's `depotcache/`.
- **Manifest pinning**: optional `ManifestIds` pins in `config.yaml`.

### Library Menus & Backups
- **Game context menu hooks** in Steam's "Manage" submenu: Add/Remove FakeAppId (480), Fetch DLCs, Fetch/Update Manifest, Remove Pinned Manifests, Why not downloading?
- **Config backups**: automatic timestamped backup before every write, with one-click restore.

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
3. **Backups** — browse and restore `config.yaml` snapshots.
4. **Settings** — Hubcap key (QR entry + stats), manifest pinning, DLC fetching, notifications.

---

## Building from source

```bash
git clone https://github.com/niwia/Uran
cd Uran
npm install
npm run build
./devinstall.sh
```

---

## License

MIT License.
