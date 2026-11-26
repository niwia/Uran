"""Built-in mobile-friendly AT0-M Web UI served directly by Epsilon at ``/``.

Same-origin HTTP on ``http://<lan-ip>:1952/#k=<token>`` — works on any phone
browser on the same Wi-Fi without Mixed Content, CORS, or extra software,
and works even when ASSella is closed.
"""


def render_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover" />
<meta name="theme-color" content="#0b0d12" />
<title>at0m — phone &amp; local console</title>
<style>
  :root {
    --bg: #0b0d12;
    --card: #151923;
    --line: rgba(255,255,255,0.12);
    --fg: #f3f5fa;
    --muted: #9aa4b8;
    --accent: #1ba1e2;
    --ok: #4ade80;
    --warn: #fbbf24;
    --danger: #f87171;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--fg);
    font: 15px/1.45 "Segoe UI", system-ui, -apple-system, sans-serif;
    padding-bottom: 5rem;
  }
  header {
    position: sticky; top: 0; z-index: 20;
    background: rgba(11,13,18,0.94);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--line);
    padding: 0.75rem 1rem;
  }
  .top { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }
  .brand { font-weight: 700; letter-spacing: 0.04em; font-size: 1.05rem; display: flex; align-items: center; gap: 0.5rem; }
  .dot { width: 9px; height: 9px; background: var(--muted); display: inline-block; }
  .dot.ok { background: var(--ok); }
  .search-row { display: flex; gap: 0.5rem; margin-top: 0.65rem; }
  input[type=search], input[type=password] {
    flex: 1; min-width: 0; min-height: 44px;
    background: var(--card); color: var(--fg);
    border: 1px solid var(--line); padding: 0 0.75rem;
    font-size: 15px; outline: none;
  }
  input:focus { border-color: var(--accent); }
  button {
    min-height: 44px; padding: 0 0.9rem;
    border: 1px solid var(--line); background: var(--card);
    color: var(--fg); font-size: 14px; font-weight: 600; cursor: pointer;
  }
  button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  button.danger { border-color: rgba(248,113,113,0.45); color: var(--danger); }
  button:disabled { opacity: 0.45; cursor: default; }
  main { padding: 0.85rem 1rem; max-width: 960px; margin: 0 auto; }
  .grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }
  @media (min-width: 720px) {
    .grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  }
  .tile {
    background: var(--card); border: 1px solid var(--line);
    padding: 0.75rem; display: flex; flex-direction: column;
    justify-content: space-between; min-height: 112px; cursor: pointer;
    text-align: left;
  }
  .tile:hover { border-color: var(--accent); }
  .tile-title { font-weight: 600; font-size: 0.95rem; word-break: break-word; }
  .tile-meta { font-size: 0.78rem; color: var(--muted); margin-top: 0.35rem; display: flex; justify-content: space-between; }
  .pill { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; }
  .pill.ok { color: var(--ok); }
  .pill.warn { color: var(--warn); }
  .pair-box {
    background: var(--card); border: 1px solid var(--line);
    padding: 1rem; margin-bottom: 1rem;
  }
  .sheet-bg {
    position: fixed; inset: 0; background: rgba(0,0,0,0.65); z-index: 40;
    display: flex; align-items: flex-end; justify-content: center;
  }
  .sheet {
    width: 100%; max-width: 560px; max-height: 86vh; overflow-y: auto;
    background: #10141d; border-top: 2px solid var(--accent);
    padding: 1rem;
  }
  .actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.5rem; margin-top: 0.85rem; }
  .toast {
    position: fixed; bottom: 1rem; left: 1rem; right: 1rem; max-width: 480px;
    margin: 0 auto; background: #1c2230; border-left: 3px solid var(--accent);
    padding: 0.75rem 0.9rem; z-index: 60; font-size: 0.9rem;
  }
  .hidden { display: none !important; }
  .muted { color: var(--muted); font-size: 0.85rem; }
</style>
</head>
<body>
<header>
  <div class="top">
    <div class="brand"><span id="dot" class="dot"></span><span>at0m // epsilon</span></div>
    <div style="display:flex;gap:0.4rem;">
      <button id="updatesBtn" type="button">updates</button>
      <button id="unpairBtn" type="button" class="hidden">unpair</button>
    </div>
  </div>
  <form id="searchForm" class="search-row">
    <input id="searchInput" type="search" placeholder="search library &amp; steam..." autocomplete="off" />
    <button type="submit" class="primary">go</button>
  </form>
</header>

<main>
  <div id="pairNameBox" class="pair-box hidden">
    <div style="font-weight:600;margin-bottom:0.4rem;">Name this instance</div>
    <p class="muted" style="margin:0 0 0.65rem;">Choose a name for this device (for example: My Phone). It will be saved in your paired devices list.</p>
    <form id="pairNameForm" class="search-row" style="margin-top:0;">
      <input id="deviceNameInput" type="search" placeholder="My Phone" maxlength="40" autocomplete="off" />
      <button id="pairProceedBtn" type="submit" class="primary">Proceed</button>
    </form>
  </div>
  <div id="pairBox" class="pair-box hidden">
    <div style="font-weight:600;margin-bottom:0.4rem;">Pair with Epsilon</div>
    <p class="muted" style="margin:0 0 0.65rem;">Scan the QR code in ASSella → Companions → Epsilon (or paste a console token below).</p>
    <div class="search-row" style="margin-top:0;">
      <input id="tokenInput" type="password" placeholder="at0m_..." autocomplete="off" />
      <button id="pairBtn" type="button" class="primary">pair</button>
    </div>
  </div>
  <div id="statusLine" class="muted" style="margin-bottom:0.65rem;">Connecting to Epsilon…</div>
  <div id="grid" class="grid"></div>
</main>

<div id="sheetBg" class="sheet-bg hidden">
  <div class="sheet">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:0.5rem;">
      <strong id="sheetTitle" style="font-size:1.1rem;"></strong>
      <button id="sheetClose" type="button">close</button>
    </div>
    <div id="sheetMeta" class="muted" style="margin-top:0.35rem;"></div>
    <div id="sheetActions" class="actions"></div>
  </div>
</div>

<div id="toast" class="toast hidden"></div>

<script>
(() => {
  const $ = (id) => document.getElementById(id);
  let token = localStorage.getItem('at0m.token') || '';
  let pendingPairCode = '';
  const pm = location.hash.match(/(?:^#|&)pair=([^&]+)/);
  if (pm) {
    pendingPairCode = decodeURIComponent(pm[1]).trim();
    history.replaceState(null, '', location.pathname + location.search);
  } else {
    const m = location.hash.match(/(?:^#|&)k=([^&]+)/);
    if (m) {
      token = decodeURIComponent(m[1]).trim();
      if (token) localStorage.setItem('at0m.token', token);
      history.replaceState(null, '', location.pathname + location.search);
    }
  }

  let games = [];
  let active = null;
  let toastTimer = null;

  function showToast(msg) {
    const el = $('toast');
    el.textContent = msg;
    el.classList.remove('hidden');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add('hidden'), 3500);
  }

  async function api(path, opts = {}) {
    const headers = { 'X-At0m-Client': '1', ...(opts.headers || {}) };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    if (opts.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    const res = await fetch(path, { ...opts, headers, cache: 'no-store' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
    return data;
  }

  function renderGrid(list) {
    const g = $('grid');
    g.innerHTML = '';
    for (const item of list) {
      const aid = String(item.app_id || item.appid || '');
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'tile';
      const installed = !!item.installed;
      const registered = item.registered !== false;
      btn.innerHTML =
        '<div class="tile-title"></div>' +
        '<div class="tile-meta"><span>' + aid + '</span>' +
        '<span class="pill ' + (installed ? 'ok' : registered ? '' : 'warn') + '">' +
        (installed ? 'installed' : registered ? 'in at0-m' : 'steam') + '</span></div>';
      btn.querySelector('.tile-title').textContent = item.title || item.name || ('App ' + aid);
      btn.onclick = () => openSheet({ ...item, app_id: aid, registered });
      g.appendChild(btn);
    }
  }

  function openSheet(item) {
    active = item;
    $('sheetTitle').textContent = item.title || item.name || ('App ' + item.app_id);
    $('sheetMeta').textContent = 'AppID ' + item.app_id + (item.installed ? ' · Installed on disk' : '');
    const act = $('sheetActions');
    act.innerHTML = '';
    const mk = (label, cls, fn) => {
      const b = document.createElement('button');
      b.type = 'button';
      if (cls) b.className = cls;
      b.textContent = label;
      b.onclick = fn;
      act.appendChild(b);
    };
    if (!item.registered) {
      mk('Register to at0-m', 'primary', async () => {
        await runAction('/v1/register', { appid: item.app_id }, 'Registered ' + item.app_id);
      });
    } else {
      mk('Refresh keys', 'primary', async () => {
        await runAction('/v1/refetch', { appid: item.app_id }, 'Keys refreshed');
      });
      mk('Install in Steam', '', async () => {
        await runAction('/v1/steam/install', { appid: item.app_id }, 'Sent install to Steam');
      });
      mk('Unregister', '', async () => {
        if (!confirm('Unregister ' + item.app_id + ' from AT0-M?')) return;
        await runAction('/v1/unregister', { appid: item.app_id }, 'Unregistered');
        $('sheetBg').classList.add('hidden');
      });
      mk('Uninstall', 'danger', async () => {
        if (!confirm('Uninstall ' + item.app_id + ' (SLSsteam + files)?')) return;
        await runAction('/v1/uninstall', { appid: item.app_id }, 'Uninstalled');
        $('sheetBg').classList.add('hidden');
      });
    }
    $('sheetBg').classList.remove('hidden');
  }

  async function runAction(path, body, okMsg) {
    try {
      await api(path, { method: 'POST', body: JSON.stringify(body) });
      showToast(okMsg);
      await loadLibrary();
    } catch (e) {
      showToast(e.message);
    }
  }

  async function loadLibrary() {
    const res = await api('/v1/library');
    games = res.games || [];
    $('statusLine').textContent = games.length + ' game' + (games.length === 1 ? '' : 's') + ' in AT0-M';
    renderGrid(games);
  }

  async function connect() {
    if (pendingPairCode) {
      $('pairNameBox').classList.remove('hidden');
      $('pairBox').classList.add('hidden');
      $('statusLine').textContent = 'Ready to pair — name this device to continue.';
      $('deviceNameInput').focus();
      return;
    }
    try {
      const s = await api('/v1/session');
      $('dot').classList.add('ok');
      $('pairNameBox').classList.add('hidden');
      $('pairBox').classList.add('hidden');
      $('unpairBtn').classList.remove('hidden');
      $('statusLine').textContent = 'Paired · Epsilon ' + (s.version || '') + (s.sls_active ? '' : ' · SLSsteam inactive');
      await loadLibrary();
    } catch (e) {
      $('dot').classList.remove('ok');
      $('pairBox').classList.remove('hidden');
      $('unpairBtn').classList.add('hidden');
      $('statusLine').textContent = e.message;
    }
  }

  $('pairNameForm').onsubmit = async (e) => {
    e.preventDefault();
    const name = $('deviceNameInput').value.trim() || 'Phone';
    $('pairProceedBtn').disabled = true;
    try {
      const res = await api('/v1/pair/complete', {
        method: 'POST',
        body: JSON.stringify({ code: pendingPairCode, name })
      });
      token = res.token || '';
      if (token) localStorage.setItem('at0m.token', token);
      pendingPairCode = '';
      showToast('Paired as ' + name);
      await connect();
    } catch (err) {
      showToast(err.message);
    } finally {
      $('pairProceedBtn').disabled = false;
    }
  };

  $('pairBtn').onclick = () => {
    token = $('tokenInput').value.trim();
    if (token) localStorage.setItem('at0m.token', token);
    connect();
  };
  $('unpairBtn').onclick = () => {
    token = '';
    localStorage.removeItem('at0m.token');
    $('grid').innerHTML = '';
    connect();
  };
  $('sheetClose').onclick = () => $('sheetBg').classList.add('hidden');
  $('sheetBg').onclick = (e) => { if (e.target === $('sheetBg')) $('sheetBg').classList.add('hidden'); };
  $('updatesBtn').onclick = async () => {
    try {
      const res = await api('/v1/updates/check', { method: 'POST', body: '{}' });
      const ups = res.updates || res.results || {};
      const n = Object.values(ups).filter((u) => u && u.update_available).length;
      showToast(n ? n + ' update(s) available' : 'All games up to date');
    } catch (e) {
      showToast(e.message);
    }
  };
  $('searchForm').onsubmit = async (e) => {
    e.preventDefault();
    const q = $('searchInput').value.trim();
    if (!q) { renderGrid(games); return; }
    try {
      const res = await api('/v1/search?q=' + encodeURIComponent(q));
      renderGrid(res.results || []);
      $('statusLine').textContent = (res.results || []).length + ' search result(s)';
    } catch (err) {
      showToast(err.message);
    }
  };

  connect();
})();
</script>
</body>
</html>
"""
