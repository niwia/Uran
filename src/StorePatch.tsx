/**
 * StorePatch.ts — Injects "Add to ASSella" button into Steam Store webview.
 *
 * The Big Picture store is a webview (GamepadUI route /routes/steamweb -> real
 * document is store.steampowered.com). We drive it through CDP WebSocket.
 *
 * Injection target: PURCHASE OPTIONS grid. We CLONE an existing listitem
 * (which carries all of Steam's panel/focus classes and typography) and
 * relabel it, so our card looks and focuses exactly like a native one.
 *
 * A MutationObserver inside the webview re-injects immediately when
 * Steam's ReactVirtualized re-renders drop our slot, so no visible gap.
 *
 * Click detection: injected script console.log("ASSELLA:<appId>");
 * plugin reads it via CDP Runtime.consoleAPICalled.
 */
import { callable } from "@decky/api";
import { injectFinishedText, notify } from "./notify";

// -- Config -------------------------------------------------------------------
const POLL_MS = 2000;
const BUTTON_COLOR_BG = "rgba(76, 175, 80, 0.92)";
const BUTTON_COLOR_TEXT = "#fff";
const ASSELLA_TAG = "ASSELLA:";
const RESTART_TAG = "RESTART:";
const COLLECTION_TAG = "Added by ASSella";


// -- State --------------------------------------------------------------------
let storeSocket: WebSocket | null = null;
let messageId = 1;
let wsReady = false;
let pollTimer: any = null;
let lastInjectedAppId = "";
let lastConsoleTs = 0;
export const addedAppIds = new Set<string>();
export const pendingAppIds = new Set<string>();

// -- Backend callables --------------------------------------------------------
type InjectResult = {
  error?: string;
  name?: string;
  depots?: string[];
  fetching?: boolean;
};
type InjectStatus = {
  done?: boolean;
  error?: string;
  keys_missing?: string[];
  depot_keys?: string[];
  manifests?: string[];
  manifest_error?: string;
};
type StoreTab = { webSocketDebuggerUrl: string; url: string };

const getInjectStatus = callable<[app_id: string], InjectStatus>(
  "get_inject_status",
);
const getSetting = callable<[key: string, defaultValue: any], any>(
  "get_setting",
);
const injectGame = callable<[app_id: string], InjectResult>("inject_game");
const restartSteam = callable<[], void>("restart_steam");
const discoverStoreTab = callable<[], StoreTab | null>("discover_store_tab");
const feDebug = callable<[msg: string], void>("fe_debug");

// -- Logging ------------------------------------------------------------------
function slog(msg: string): void {
  try {
    feDebug(msg);
  } catch {}
  try {
    console.log("[ASSella Store] " + msg);
  } catch {}
}

// -- Collection helpers -------------------------------------------------------
let _assellaCollectionId: string | null = null;

export async function tagInAssellaCollection(
  appId: string,
  retries = 3,
): Promise<void> {
  for (let attempt = 0; attempt < retries; attempt++) {
    try {
      const cs =
        (window as any).collectionStore || (window as any).g_CollectionStore;
      if (!cs) {
        slog(
          `tagInAssellaCollection attempt ${attempt + 1}/${retries}: no collectionStore`,
        );
        if (attempt < retries - 1) {
          await new Promise((r) => setTimeout(r, 1000));
          continue;
        }
        notify(
          "Uran",
          `Collection store unavailable — game added but not tagged`,
        );
        return;
      }

      let collectionId =
        _assellaCollectionId || cs.GetCollectionIDByUserTag?.(COLLECTION_TAG);
      let collection = collectionId ? cs.GetCollection?.(collectionId) : null;

      if (!collection) {
        _assellaCollectionId = null;
        slog("creating collection: " + COLLECTION_TAG);
        collectionId =
          (await cs.CreateNewCollection?.(COLLECTION_TAG)) ||
          (await cs.CreateCustomCollection?.(COLLECTION_TAG));
        if (!collectionId) {
          slog("CreateNewCollection returned falsy");
          if (attempt < retries - 1) {
            await new Promise((r) => setTimeout(r, 1000));
            continue;
          }
          notify(
            "Uran",
            `Could not create "${COLLECTION_TAG}" collection`,
          );
          return;
        }
        collection = cs.GetCollection?.(collectionId);
        if (!collection) {
          slog("collection created but GetCollection returned null");
          if (attempt < retries - 1) {
            await new Promise((r) => setTimeout(r, 1000));
            continue;
          }
          notify(
            "Uran",
            `Collection created but not yet available`,
          );
          return;
        }
      }

      _assellaCollectionId = collectionId as string;
      const numAppId = Number(appId);

      if (typeof collection.AddApp === "function") {
        await collection.AddApp(numAppId);
      } else if (typeof cs.AddAppToCollection === "function") {
        await cs.AddAppToCollection(collectionId, numAppId);
      } else if (typeof collection.AddAppToCollection === "function") {
        await collection.AddAppToCollection(numAppId);
      } else if (typeof cs.AddAppsToCollection === "function") {
        await cs.AddAppsToCollection(collectionId, [numAppId]);
      } else {
        slog(
          "No known AddApp method on collection: " +
            Object.keys(collection).join(", "),
        );
        if (attempt < retries - 1) {
          await new Promise((r) => setTimeout(r, 1000));
          continue;
        }
        return;
      }

      try {
        cs.SaveCollections?.();
      } catch {}
      try {
        collection.Save?.();
      } catch {}

      slog(`tagged ${appId} in "${COLLECTION_TAG}" (attempt ${attempt + 1})`);
      return;
    } catch (e) {
      slog(
        `tagInAssellaCollection attempt ${attempt + 1}/${retries} error: ${e}`,
      );
      _assellaCollectionId = null;
      if (attempt < retries - 1) {
        await new Promise((r) => setTimeout(r, 1000));
      }
    }
  }
  notify(
    "Uran",
    `Failed to add game to collection after ${retries} tries`,
  );
}

function pollInjectJob(appId: string, name: string, onDone?: () => void): void {
  const startedAt = Date.now();
  const MAX_WAIT_MS = 300000;
  const timer = setInterval(async () => {
    try {
      const job = await getInjectStatus(appId);
      if (job?.done) {
        clearInterval(timer);
        notify("Uran", injectFinishedText(name, job));
        onDone?.();
      } else if (Date.now() - startedAt > MAX_WAIT_MS) {
        clearInterval(timer);
        notify("Uran", `Background work for ${name} timed out`);
        onDone?.();
      }
    } catch {
      /* keep polling */
    }
  }, 2000);
}

// -- CDP WebSocket ------------------------------------------------------------
function extractAppId(url: string): string {
  const m = url?.match(/\/app\/(\d+)/);
  return m?.[1] ?? "";
}

function wsSend(obj: Record<string, unknown>): void {
  if (!storeSocket || storeSocket.readyState !== WebSocket.OPEN) return;
  storeSocket.send(JSON.stringify(obj));
}

/**
 * Injected script that runs inside the Steam Store webview.
 */
function buildInjectScript(): string {
  return `(function() {
    try {
      function log(msg){ try { console.log('ASSELLA-STORE:' + msg); } catch(e){} }

      var BG = ${JSON.stringify(BUTTON_COLOR_BG)};
      var FG = ${JSON.stringify(BUTTON_COLOR_TEXT)};
      var ASSELLA_TAG = ${JSON.stringify(ASSELLA_TAG)};
      var RESTART_TAG = ${JSON.stringify(RESTART_TAG)};

      if (!window.__assellaStoreState) {
        window.__assellaStoreState = { appId:'', label:'ADD TO ASSELLA', locked:false, showRestart:false };
      }
      var S = window.__assellaStoreState;

      function makeButton(text, tag, clickLabel, disabled) {
        var b = document.createElement('button');
        b.type = 'button';
        b.textContent = text;
        b.setAttribute('data-assella-action', tag);
        b.tabIndex = 0;
        b.style.cssText =
          'display:inline-block;' +
          'padding:10px 18px;' +
          'margin-right:8px;' +
          'border:none;' +
          'border-radius:4px;' +
          'background:' + (tag === RESTART_TAG ? '#3a3a4c' : BG) + ';' +
          'color:' + FG + ';' +
          'font-family:inherit;' +
          'font-size:14px;' +
          'font-weight:700;' +
          'letter-spacing:0.5px;' +
          'cursor:' + (disabled ? 'default' : 'pointer') + ';' +
          'opacity:' + (disabled ? '0.7' : '1') + ';' +
          'transition:background 0.15s, opacity 0.15s;';
        if (!disabled) {
          b.onclick = function(e) {
            e.stopPropagation();
            if (clickLabel) {
              b.textContent = clickLabel;
              b.style.opacity = '0.7';
              b.disabled = true;
            }
            console.log(tag + S.appId);
          };
        }
        return b;
      }

      function findExisting() {
        return document.getElementById('assella-purchase-slot')
            || document.getElementById('Uran-btns');
      }

      function updateExisting(existing) {
        if (!existing) return false;
        var slotApp = existing.getAttribute('data-assella-appid');
        if (slotApp !== S.appId) return false;

        var mainBtn = existing.querySelector('button[data-assella-action="' + ASSELLA_TAG + '"]');
        if (mainBtn) {
          mainBtn.textContent = S.label;
          mainBtn.style.opacity = S.locked ? '0.7' : '1';
          mainBtn.style.cursor = S.locked ? 'default' : 'pointer';
        }

        var restart = existing.querySelector('button[data-assella-action="' + RESTART_TAG + '"]');
        if (S.showRestart && !restart) {
          var inner = existing.querySelector('[data-assella-inner]') || existing;
          inner.appendChild(makeButton('RESTART STEAM', RESTART_TAG, 'RESTARTING...', false));
        } else if (!S.showRestart && restart) {
          restart.remove();
        }
        return true;
      }

      function injectFallback() {
        var host = document.querySelector('.game_area_purchase')
                || document.querySelector('#game_area_purchase')
                || document.body;
        if (!host) return false;
        var w = document.createElement('div');
        w.id = 'Uran-btns';
        w.setAttribute('data-assella-appid', S.appId);
        w.style.cssText = 'padding:14px; margin:12px 0; background:rgba(0,0,0,0.35); border-radius:6px;';
        w.appendChild(makeButton(S.label, ASSELLA_TAG, 'ADDING...', S.locked));
        if (S.showRestart) {
          w.appendChild(makeButton('RESTART STEAM', RESTART_TAG, 'RESTARTING...', false));
        }
        host.prepend(w);
        log('fallback banner injected for ' + S.appId);
        return true;
      }

      function injectFromState() {
        if (!S.appId) return;

        var existing = findExisting();
        if (existing) {
          if (updateExisting(existing)) return;
          existing.remove();
        }

        var candidates = document.querySelectorAll('[role="listitem"], .game_area_purchase_game, .game_area_purchase_platform');
        var ref = null;
        for (var i = 0; i < candidates.length; i++) {
          var c = candidates[i];
          if (c.id === 'assella-purchase-slot' || c.id === 'Uran-btns') continue;
          if (c.querySelector('button, .btn_addtocart, .game_purchase_action')) {
            ref = c;
            break;
          }
        }

        if (!ref) {
          injectFallback();
          return;
        }

        var clone = ref.cloneNode(true);
        clone.id = 'assella-purchase-slot';
        clone.setAttribute('data-id', 'assella_purchase_option');
        clone.setAttribute('data-assella-appid', S.appId);
        clone.style.outline = 'none';

        var title = clone.querySelector('h1, h2, h3, [class*="game_area_purchase_game_dropdown_selection"]');
        if (title) title.textContent = 'ASSella';

        var desc = clone.querySelector('[class*="purchase_subtext"], [class*="game_area_purchase_game_dropdown_selection_price"]');
        if (desc) {
          desc.textContent = 'Add game to your ASSella / SLS library';
        }

        var btn = clone.querySelector('button, .btn_addtocart, [class*="btn_primary"]');
        if (btn) {
          btn.textContent = S.label;
          btn.setAttribute('data-assella-action', ASSELLA_TAG);
          if (btn.parentElement) btn.parentElement.setAttribute('data-assella-inner', '1');
          btn.style.background = BG;
          btn.style.color = FG;
          btn.style.opacity = S.locked ? '0.7' : '1';
          btn.style.cursor = S.locked ? 'default' : 'pointer';
          btn.onclick = function(e) {
            e.stopPropagation();
            if (!S.locked) {
              btn.textContent = 'ADDING...';
              btn.style.opacity = '0.7';
              console.log(ASSELLA_TAG + S.appId);
            }
          };
          if (S.showRestart) {
            var rBtn = makeButton('EXIT STEAM', RESTART_TAG, 'EXITING...', false);
            btn.parentElement.appendChild(rBtn);
          }
        }

        ref.parentElement.insertBefore(clone, ref);
        log('injected purchase slot card for ' + S.appId);
      }

      window.__assellaInjectFromState = injectFromState;

      if (!window.__assellaObserverInstalled) {
        window.__assellaObserverInstalled = true;
        var mo = new MutationObserver(function() {
          if (!window.__assellaStoreState || !window.__assellaStoreState.appId) return;
          var cur = findExisting();
          if (!cur) {
            window.__assellaInjectFromState();
          } else {
            updateExisting(cur);
          }
        });
        mo.observe(document.body, { childList: true, subtree: true });
        log('MutationObserver installed');
      }

      injectFromState();
    } catch(err) {
      try { console.log('ASSELLA-STORE: error ' + err); } catch(e){}
    }
  })();`;
}

/** Push current state into the webview and ask it to inject. */
async function inject(
  appId: string,
  force = false,
  labelOverride?: string,
  lockedOverride?: boolean,
): Promise<void> {
  if (!appId) return;
  if (appId === lastInjectedAppId && !force && labelOverride === undefined) {
    return;
  }
  lastInjectedAppId = appId;

  let showRestart = false;
  try {
    const s = await getSetting("show_restart_button", false);
    showRestart = s === true;
  } catch {}

  const isAdded = addedAppIds.has(appId);
  const isPending = !isAdded && pendingAppIds.has(appId);
  const label =
    labelOverride ??
    (isAdded ? "ADDED" : isPending ? "ADDING..." : "ADD TO ASSELLA");
  const locked = lockedOverride ?? (isAdded || isPending);

  const stateScript =
    "(function(){try{" +
    "var S=window.__assellaStoreState;if(!S){S={};window.__assellaStoreState=S;}" +
    "S.appId=" +
    JSON.stringify(appId) +
    ";S.label=" +
    JSON.stringify(label) +
    ";S.locked=" +
    JSON.stringify(locked) +
    ";S.showRestart=" +
    JSON.stringify(showRestart) +
    ";}catch(e){}})();";
  wsSend({
    id: messageId++,
    method: "Runtime.evaluate",
    params: { expression: stateScript },
  });
  wsSend({
    id: messageId++,
    method: "Runtime.evaluate",
    params: { expression: buildInjectScript() },
  });
}

function remove(): void {
  lastInjectedAppId = "";
  wsSend({
    id: messageId++,
    method: "Runtime.evaluate",
    params: {
      expression:
        "(function(){try{" +
        "var s=document.getElementById('assella-purchase-slot'); if(s) s.remove();" +
        "var o=document.getElementById('Uran-btns'); if(o) o.remove();" +
        "}catch(e){}})();",
    },
  });
}

async function connect(tab: StoreTab): Promise<void> {
  if (!tab.webSocketDebuggerUrl) return;
  if (storeSocket) {
    try {
      storeSocket.close();
    } catch {}
    storeSocket = null;
    wsReady = false;
  }
  slog("CDP: connecting to " + tab.webSocketDebuggerUrl);
  storeSocket = new WebSocket(tab.webSocketDebuggerUrl);
  storeSocket.onopen = () => {
    wsSend({ id: messageId++, method: "Page.enable" });
    wsSend({ id: messageId++, method: "Runtime.enable" });
    setTimeout(() => {
      wsReady = true;
      const appId = extractAppId(tab.url);
      if (appId) inject(appId, true);
    }, 1500);
  };
  storeSocket.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data);
      if (data.method === "Page.frameNavigated" && data.params?.frame) {
        const frame = data.params.frame;
        if (!frame.parentId) {
          setTimeout(() => {
            const appId = extractAppId(frame.url || "");
            if (appId) inject(appId, true);
            else remove();
          }, 2000);
        }
      }
      if (data.method === "Runtime.consoleAPICalled" && data.params?.args) {
        const ts =
          typeof data.params.timestamp === "number" ? data.params.timestamp : 0;
        if (ts > 0 && ts <= lastConsoleTs) {
          return;
        }

        if (ts > 0) lastConsoleTs = ts;

        for (const arg of data.params.args) {
          if (arg.type === "string" && arg.value) {
            if (arg.value.startsWith("ASSELLA-STORE:")) {
              slog("webview: " + arg.value);
            } else if (arg.value.startsWith(ASSELLA_TAG)) {
              const appId = arg.value.slice(ASSELLA_TAG.length);
              slog("webview click: " + appId);
              pendingAppIds.add(appId);
              inject(appId, true, "ADDING...", true);
              injectGame(appId)
                .then((r: InjectResult) => {
                  if (r && !r.error) {
                    tagInAssellaCollection(appId);
                    const name = r.name || appId;
                    const extra = "";
                    const depotInfo = r.depots
                      ? ` — ${r.depots.length} depot(s)`
                      : "";
                    notify("Uran", `Added ${name}${extra}${depotInfo}`);
                    if (r.fetching) {
                      notify("Uran", `Fetching Hubcap manifests & keys for ${name}...`);
                    }
                    pollInjectJob(appId, name, () => {
                      pendingAppIds.delete(appId);
                      addedAppIds.add(appId);
                      inject(appId, true);
                    });
                  } else {
                    pendingAppIds.delete(appId);
                    notify(
                      "Uran",
                      r?.error || `Failed to add game ${appId}`,
                    );
                    inject(appId, true);
                  }
                })
                .catch((e: any) => {
                  pendingAppIds.delete(appId);
                  notify("Uran", `Failed to add game ${appId}: ${e}`);
                  inject(appId, true);
                });
            } else if (arg.value.startsWith(RESTART_TAG)) {
              restartSteam();
            }
          }
        }
      }
    } catch {}
  };
  storeSocket.onerror = () => {
    slog("CDP: socket error");
    wsReady = false;
  };
  storeSocket.onclose = () => {
    slog("CDP: socket closed");
    storeSocket = null;
    wsReady = false;
  };
}

async function pollCdp(): Promise<void> {
  try {
    const res = await discoverStoreTab();
    if (res) {
      if (!storeSocket || storeSocket.readyState !== WebSocket.OPEN) {
        await connect(res);
      } else if (wsReady) {
        const appId = extractAppId(res.url);
        if (appId && appId !== lastInjectedAppId) {
          inject(appId, true);
        }
      }
    } else {
      if (storeSocket) {
        remove();
        try {
          storeSocket.close();
        } catch {}
        storeSocket = null;
        wsReady = false;
        lastInjectedAppId = "";
      }
    }
  } catch (e) {
    slog("pollCdp error: " + e);
  }
}

function startPoll(): void {
  stopPoll();
  pollCdp();
  pollTimer = setInterval(pollCdp, POLL_MS);
}

function stopPoll(): void {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  if (storeSocket) {
    remove();
    try {
      storeSocket.close();
    } catch {}
    storeSocket = null;
    wsReady = false;
  }
  lastInjectedAppId = "";
}

function initRouteSpy(): () => void {
  const origPush = history.pushState;
  const origReplace = history.replaceState;
  const report = (src: string) => {
    const loc = window.location;
    slog(`ROUTE-SPY[${src}] pathname=${loc.pathname} hash=${loc.hash}`);
  };
  history.pushState = function (...args: any[]) {
    const r = origPush.apply(this as any, args as any);
    report("pushState");
    return r;
  };
  history.replaceState = function (...args: any[]) {
    const r = origReplace.apply(this as any, args as any);
    report("replaceState");
    return r;
  };
  const onPop = () => report("popstate");
  const onHash = () => report("hashchange");
  window.addEventListener("popstate", onPop);
  window.addEventListener("hashchange", onHash);
  report("init");
  return () => {
    history.pushState = origPush;
    history.replaceState = origReplace;
    window.removeEventListener("popstate", onPop);
    window.removeEventListener("hashchange", onHash);
  };
}

export function initStorePatch(): () => void {
  slog("initStorePatch: starting");
  const stopSpy = initRouteSpy();
  startPoll();
  return () => {
    slog("initStorePatch: cleanup");
    stopSpy();
    stopPoll();
  };
}
