# Epsilon — at0-m and uran companion

> **Photar** (Browser Userscript) $\leftrightarrow$ **Epsilon** (Localhost Bridge / systemd) $\leftrightarrow$ **Uran 0.6.3 Engine** $\leftrightarrow$ **SLSsteam**

---

## 1. Overview & Concept

Named after the characters from *Astro Boy* / *Pluto*:
- **Epsilon**: The photon-powered robot operating quietly in the background. It is a lightweight, local socket-activated daemon and API bridge powered by the **Uran 0.6.3 backend engine**.
- **Photar**: The photon energy beam projecting from the web. It is a Tampermonkey userscript injecting native **"Add to at0-m"** buttons onto **Steam Store** and **SteamDB** pages.
- *"Save me more sunlight!"* — Photar

This bridge enables **1-click game injection directly from your browser** into SLSsteam, without needing to manually search for games inside Steam Deck GamepadUI or the Uran plugin menu.

---

## 2. Hybrid Zero-Footprint Architecture

Epsilon uses a **hybrid listener architecture** that ensures **0% CPU and 0 MB idle RAM footprint**:

```
                       ┌──────────────────────────────┐
                       │  Photar (Tampermonkey Script)│
                       │   • store.steampowered.com   │
                       │   • steamdb.info             │
                       └──────────────┬───────────────┘
                                      │ HTTP (CORS preflight & JSON)
                                      ▼
                           127.0.0.1:1952 (Port)
                                      │
            ┌─────────────────────────┴────────────────────────┐
            │                                                  │
            ▼                                                  ▼
┌───────────────────────────────┐              ┌───────────────────────────────┐
│ Primary: systemd User Socket  │              │ Fallback: Uran Decky Plugin   │
│  (`epsilon.socket`)           │              │  (`Plugin._main()` loopback)  │
│                               │              │                               │
│ • Listens on 127.0.0.1:1952  │              │ • Checks if port 1952 is in  │
│ • Process is DEAD when idle   │              │   use by systemd              │
│ • Wakes `daemon.py` on-demand │              │ • If free, binds non-blocking │
│ • Auto-exits after 120s idle  │              │   asyncio server inside Decky │
└──────────────┬────────────────┘              └──────────────┬────────────────┘
               │                                              │
               └──────────────────────┬───────────────────────┘
                                      ▼
                        ┌───────────────────────────┐
                        │    uran_backend (0.6.3)   │
                        │ • Atomic config.yaml lock │
                        │ • Hubcap Keys & AppTokens │
                        │ • SpaceBunny 1.5 config   │
                        │ • Manifest depotcache     │
                        │ • SLS reload signaling    │
                        └───────────────────────────┘
```

### Why this design is ideal:
1. **Works with or without Uran/Decky**: Users on pure desktop Linux (Arch, Fedora, Ubuntu, Steam Deck Desktop Mode) can run Epsilon independently via systemd.
2. **Zero Idle Resource Consumption**: Under `systemd --user` socket activation, `daemon.py` is **not running** until you click a button in your browser. After handling requests, it automatically exits after 120 seconds of inactivity.
3. **No Port Collisions**: When Uran loads in Decky, it checks if port `1952` is already active. If systemd is running it, Uran defers to it; if systemd is not installed, Uran automatically provides an embedded non-blocking loopback server.
4. **Shared 0.6.3 Engine**: Both paths execute [`Injector.inject(app_id)`](file:///home/aiwin/Documents/assella-decky/uran_backend/inject.py#L563) with identical file paths, atomic write locks, SpaceBunny bridge sync, and manifest downloads.

---

## 3. Directory Structure

```text
assella-decky/
├── uran_backend/
│   ├── epsilon_server.py    <-- Core HTTP dispatcher & async/sync servers
│   ├── plugin_api.py        <-- Wired with embedded Epsilon loopback fallback
│   └── ...                  <-- Standard 0.6.3 services (inject, sls, hubcap)
├── epsilon/
│   ├── daemon.py            <-- Standalone & socket-activated CLI entry point
│   ├── epsilon.socket       <-- systemd --user socket definition (port 1952)
│   ├── epsilon.service      <-- systemd --user service definition
│   ├── install.sh           <-- 1-click Linux / Steam Deck installer
│   └── uninstall.sh         <-- Clean uninstaller
├── photar/
│   └── photar.user.js       <-- Tampermonkey userscript for Steam & SteamDB
└── tests/
    └── test_epsilon.py      <-- Complete unit test suite for Epsilon API
```

---

## 4. Setup & Installation Guide

### Option 1: Standalone Linux Desktop & Steam Deck Desktop Mode

To install Epsilon as a socket-activated systemd user service:

```bash
cd /path/to/assella-decky/epsilon
./install.sh
```

The script automatically:
1. Detects your Python 3 binary and project paths.
2. Copies `epsilon.socket` and generates `epsilon.service` into `~/.config/systemd/user/`.
3. Reloads `systemctl --user daemon-reload`.
4. Enables and starts `epsilon.socket`.
5. Verifies the connection with a test ping.

### How to Stop or Manage Epsilon

- **Stop temporarily**:
  ```bash
  systemctl --user stop epsilon.socket epsilon.service
  ```
- **Start or restart**:
  ```bash
  systemctl --user restart epsilon.socket
  ```
- **Check live logs**:
  ```bash
  journalctl --user -u epsilon.service -f
  ```
- **Completely uninstall**:
  ```bash
  cd /path/to/assella-decky/epsilon
  ./uninstall.sh
  ```

### Option 2: Steam Deck Gaming Mode (Decky Plugin)

If you have Uran installed in Decky:
- **No manual setup required!**
- Uran's `Plugin._main()` automatically starts the Epsilon embedded loopback on port `1952` when the plugin loads (if systemd isn't already managing it).

### Option 3: Manual Testing in Terminal

You can run the daemon directly in foreground mode for testing:

```bash
python3 epsilon/daemon.py --port 1952
```

---

## 5. Installing the Photar Userscript

1. Install the **Tampermonkey** extension in your browser:
   - [Chrome Web Store](https://chromewebstore.google.com/detail/tampermonkey/dhdgffkkminghmkfjojehanbpfakkejk)
   - [Firefox Add-ons](https://addons.mozilla.org/firefox/addon/tampermonkey/)
2. Open the Tampermonkey Dashboard $\rightarrow$ **Utilities** $\rightarrow$ **Install from file or URL**, or click **Create a new script**.
3. Paste the contents of [`photar/photar.user.js`](file:///home/aiwin/Documents/assella-decky/photar/photar.user.js).
4. Save the script (Ctrl+S).

### Browser Behavior
- Navigate to any Steam Store page (e.g. `https://store.steampowered.com/app/730/`) or SteamDB page (`https://steamdb.info/app/730/`).
- Photar connects to `http://127.0.0.1:1952/ping`.
- If ready, the button displays **`Add to at0-m`**.
- If the game is already in your SLSsteam library, the button shows **`In Library`**.
- Clicking **`Add to at0-m`** sets the button to **`Adding...`**, triggers background injection into SLSsteam, and updates to **`In Library`**.

---

## 6. REST API Specification

Epsilon strictly binds to `127.0.0.1:1952`. It enforces numeric AppID sanitization to prevent injection vulnerabilities.

### `OPTIONS *`
- **Purpose**: CORS preflight for browser `fetch` and `XMLHttpRequest`.
- **Response**: `200 OK` with `Access-Control-Allow-Origin: *`.

### `GET /ping`
- **Purpose**: Health check & capability probe.
- **Response**:
```json
{
  "ok": true,
  "service": "epsilon",
  "version": "0.6.3",
  "engine": "uran_backend",
  "sls_active": true,
  "has_hubcap_key": true
}
```

### `GET /status?appid=<app_id>`
- **Purpose**: Query library status and injection worker progress.
- **Response**:
```json
{
  "ok": true,
  "appid": "730",
  "name": "Counter-Strike 2",
  "added": true,
  "inject_status": {
    "done": true,
    "running": false,
    "depot_keys": ["731", "732"],
    "keys_missing": []
  }
}
```

### `POST /inject`
- **Payload**: `{"appid": "620"}`
- **Response (Started)**:
```json
{
  "ok": true,
  "name": "Portal 2",
  "depots": ["621", "622"],
  "fetching": true
}
```
- **Response (Already Added)**:
```json
{
  "ok": false,
  "already_added": true,
  "error": "Portal 2 is already registered in your library."
}
```

### `POST /refresh`
- **Payload**: `{"appid": "620"}`
- **Purpose**: Re-projects game configuration and mounts newly discovered keys/depots without wiping enabled DLCs.

### `POST /refetch`
- **Payload**: `{"appid": "620"}`
- **Purpose**: Force-bypasses manifest cache and refetches fresh decryption keys and SmartTickets from Hubcap.

---

## 7. Verification & Troubleshooting

### Check systemd Socket Status
```bash
systemctl --user status epsilon.socket
```

### View Live Epsilon Logs
```bash
journalctl --user -u epsilon.service -f
```

### Manual Curl Test
```bash
curl -i http://127.0.0.1:1952/ping
curl -i http://127.0.0.1:1952/status?appid=730
```

### Run Automated Test Suite
```bash
python3 tests/test_epsilon.py
```
