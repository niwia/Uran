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
import { refetchGame } from "./api";
import { showQrKeyModal } from "./components/QrKeyModal";

// -- Config -------------------------------------------------------------------
const POLL_MS = 2000;
const ASSELLA_ADD_TAG = "ASSELLA_ADD:";
const ASSELLA_REFETCH_TAG = "ASSELLA_REFETCH:";
const ASSELLA_TAG = "ASSELLA:"; // legacy fallback


// -- State --------------------------------------------------------------------
let storeSocket: WebSocket | null = null;
let messageId = 1;
let wsReady = false;
let pollTimer: any = null;
let storePatchEnabled: boolean | null = null;
let stopRouteSpy: (() => void) | null = null;
let lifecycle = 0;
let lastInjectedAppId = "";
let lastConsoleTs = 0;
export const addedAppIds = new Set<string>();
export const pendingAppIds = new Set<string>();
export const refetchingAppIds = new Set<string>();

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
const injectGame = callable<[app_id: string], InjectResult & { already_added?: boolean }>("inject_game");
const discoverStoreTab = callable<[], StoreTab | null>("discover_store_tab");
const isAppAdded = callable<[app_id: string], boolean>("is_app_added");
const getAddedAppIds = callable<[], string[]>("get_added_app_ids");
const feDebug = callable<[msg: string], void>("fe_debug");

export async function syncAddedAppIds(): Promise<void> {
  try {
    const list = await getAddedAppIds();
    if (Array.isArray(list)) {
      addedAppIds.clear();
      for (const id of list) {
        if (id) addedAppIds.add(String(id));
      }
      slog(`synced ${addedAppIds.size} added games`);
    }
  } catch (err) {
    slog("syncAddedAppIds error: " + err);
  }
}

// -- Logging ------------------------------------------------------------------
function slog(msg: string): void {
  try {
    void feDebug(`[StorePatch] ${msg}`).catch(() => {});
  } catch {}
  try { console.log("[StorePatch] " + msg); } catch {}
}

// -- Collection helpers (disabled per user request) --------------------------
export async function tagInAssellaCollection(_appId: string): Promise<void> {
  // Feature disabled
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

      var ASSELLA_ADD_TAG = ${JSON.stringify(ASSELLA_ADD_TAG)};
      var ASSELLA_REFETCH_TAG = ${JSON.stringify(ASSELLA_REFETCH_TAG)};

      var BASE_BLUE_BG = 'rgba(103, 193, 245, 0.2)';
      var BASE_BLUE_HOVER_BG = 'linear-gradient(-60deg, #417a9b 5%, #67c1f5 95%)';
      var TEXT_COLOR = '#67c1f5';
      var TEXT_HOVER_COLOR = '#ffffff';

      function getState() {
        if (!window.__assellaStoreState) {
          window.__assellaStoreState = {
            appId: '',
            label: 'Add to Uran',
            tooltip: 'Add game to at0-m plugin and download from your library!',
            actionTag: ASSELLA_ADD_TAG,
            clickLabel: 'Adding...',
            locked: false
          };
        }
        return window.__assellaStoreState;
      }

      function registerFocusNode(element, referenceElement) {
        try {
          if (!element || !referenceElement) return;
          if (window.__assellaUranFocusNode) {
            try { window.__assellaUranFocusNode.OnUnmount(); } catch(e){}
            window.__assellaUranFocusNode = null;
          }
          var fiberKey = Object.keys(referenceElement).find(function(k) { return k.indexOf('__reactFiber') === 0; });
          var cur = fiberKey ? referenceElement[fiberKey] : null;
          var refNode = null;
          while (cur) {
            if (cur.memoizedProps && cur.memoizedProps.node) {
              refNode = cur.memoizedProps.node;
              break;
            }
            cur = cur.return;
          }
          if (!refNode) return;
          var parent = refNode.m_Parent;
          var navParent = parent;
          if (parent && parent.m_Parent && parent.m_rgChildren && parent.m_rgChildren.length <= 1) {
            navParent = parent.m_Parent;
          }
          if (!navParent) navParent = parent || refNode;

          if (navParent.m_rgChildren) {
            for (var ci = navParent.m_rgChildren.length - 1; ci >= 0; ci--) {
              var ch = navParent.m_rgChildren[ci];
              if (ch && ch.m_element && (ch.m_element.id === 'Uran-btns' || (ch.m_element.textContent && ch.m_element.textContent.indexOf('Uran') !== -1))) {
                try { ch.OnUnmount(); } catch(e){}
              }
            }
          }

          var NodeClass = refNode.constructor;
          var uranNode = new NodeClass(refNode.m_Tree, navParent, refNode.m_FocusRing);
          uranNode.SetProperties({
            layout: 0,
            focusable: true,
            focusClassName: 'Focusable',
            focusWithinClassName: 'Focusable'
          });
          uranNode.OnMount(element);
          if (navParent.EnsureChildrenSorted) {
            navParent.EnsureChildrenSorted(true);
          }
          window.__assellaUranFocusNode = uranNode;
          log('registered Uran focus node in Valve FocusNavTree');
        } catch(e) {
          log('FocusNavTree registration error: ' + e);
        }
      }

      function makeButton(text, tag, clickLabel, disabled, isWishlistStyle) {
        var S = getState();
        var b = document.createElement('button');
        b.type = 'button';
        b.className = isWishlistStyle
          ? 'btnv6_blue_hoverfade btn_medium queue_btn_inactive Focusable'
          : 'btnv6_blue_hoverfade btn_medium queue_btn_inactive';
        b.setAttribute('data-assella-action', tag || ASSELLA_ADD_TAG);
        b.setAttribute('data-panel', '{"focusable":true,"clickOnActivate":true}');
        b.setAttribute('role', 'button');
        b.tabIndex = 0;

        var tip = S.tooltip || 'Add game to at0-m plugin and download from your library!';
        b.setAttribute('data-tooltip-text', tip);
        b.title = tip;
        b.setAttribute('aria-label', tip);

        var span = document.createElement('span');
        span.textContent = text;

        if (isWishlistStyle) {
          span.style.cssText =
            'display:flex;' +
            'align-items:center;' +
            'justify-content:center;' +
            'width:100%;' +
            'height:100%;' +
            'box-sizing:border-box;' +
            'padding:0 16px;' +
            'background:transparent;' +
            'color:' + TEXT_COLOR + ';' +
            'border-radius:2px;' +
            'font-family:"Motiva Sans", Arial, sans-serif;' +
            'font-size:14px;' +
            'font-weight:500;' +
            'letter-spacing:0.2px;' +
            'white-space:nowrap;' +
            'transition:all 0.2s ease;';

          b.style.cssText =
            'width:100%;' +
            'height:36px;' +
            'display:flex;' +
            'align-items:center;' +
            'justify-content:center;' +
            'background:' + BASE_BLUE_BG + ';' +
            'border:none;' +
            'border-radius:2px;' +
            'padding:1px;' +
            'box-sizing:border-box;' +
            'cursor:' + (disabled ? 'default;' : 'pointer;') +
            'opacity:' + (disabled ? '0.7;' : '1;') +
            'text-decoration:none;' +
            'transition:all 0.2s ease;';
        } else {
          span.style.cssText =
            'display:block;' +
            'background:transparent;' +
            'color:' + TEXT_COLOR + ';' +
            'border-radius:2px;' +
            'font-family:"Motiva Sans", Arial, sans-serif;' +
            'font-size:15px;' +
            'line-height:30px;' +
            'padding:0 15px;' +
            'box-sizing:border-box;' +
            'white-space:nowrap;' +
            'text-align:center;' +
            'transition:all 0.2s ease;';

          b.style.cssText =
            'display:inline-block;' +
            'background:' + BASE_BLUE_BG + ';' +
            'border:none;' +
            'border-radius:2px;' +
            'padding:1px;' +
            'box-sizing:border-box;' +
            'cursor:' + (disabled ? 'default;' : 'pointer;') +
            'opacity:' + (disabled ? '0.7;' : '1;') +
            'text-decoration:none;' +
            'transition:all 0.2s ease;';
        }

        b.appendChild(span);

        b.addEventListener('vgp_onok', function(e) {
          b.click();
        });
        b.addEventListener('keydown', function(e) {
          if (e.key === 'Enter' || e.key === ' ') {
            b.click();
          }
        });

        if (window.$J && window.$J.fn && window.$J.fn.v_tooltip) {
          try {
            window.$J(b).v_tooltip({
              tooltipClass: 'store_tooltip',
              defaultType: 'text',
              dataName: 'tooltipText'
            });
          } catch(e) {}
        }

        if (disabled) {
          b.disabled = true;
        } else {
          b.onclick = function(e) {
            e.stopPropagation();
            e.preventDefault();
            if (b.disabled) return;
            var S = getState();
            var targetLabel = S.clickLabel || (S.actionTag === ASSELLA_REFETCH_TAG ? 'Refetching...' : 'Adding...');
            span.textContent = targetLabel;
            b.style.opacity = '0.7';
            b.disabled = true;
            console.log(S.actionTag + S.appId);
          };
          b.onmouseenter = function() {
            if (!b.disabled) {
              b.style.background = BASE_BLUE_HOVER_BG;
              span.style.color = TEXT_HOVER_COLOR;
            }
          };
          b.onmouseleave = function() {
            if (!b.disabled) {
              b.style.background = BASE_BLUE_BG;
              span.style.color = TEXT_COLOR;
            }
          };
          b.onfocus = function() {
            if (!b.disabled) {
              b.style.background = BASE_BLUE_HOVER_BG;
              span.style.color = TEXT_HOVER_COLOR;
            }
          };
          b.onblur = function() {
            if (!b.disabled) {
              b.style.background = BASE_BLUE_BG;
              span.style.color = TEXT_COLOR;
            }
          };
        }
        return b;
      }

      function findExisting() {
        var all = document.querySelectorAll('#Uran-btns, #assella-purchase-slot');
        if (all.length > 1) {
          for (var i = 1; i < all.length; i++) {
            all[i].remove();
          }
        }
        return all[0] || null;
      }

      function updateExisting(existing) {
        if (!existing) return false;
        var S = getState();
        var slotApp = existing.getAttribute('data-assella-appid');
        if (slotApp !== S.appId) return false;

        var mainBtn = existing.querySelector('button[data-assella-action]');
        if (mainBtn) {
          mainBtn.setAttribute('data-assella-action', S.actionTag);
          var span = mainBtn.querySelector('span');
          if (span) {
            span.textContent = S.label;
          } else {
            mainBtn.textContent = S.label;
          }
          if (S.tooltip) {
            mainBtn.setAttribute('data-tooltip-text', S.tooltip);
            mainBtn.title = S.tooltip;
            mainBtn.setAttribute('aria-label', S.tooltip);
          }
          mainBtn.style.opacity = S.locked ? '0.7' : '1';
          mainBtn.style.cursor = S.locked ? 'default' : 'pointer';
          mainBtn.disabled = !!S.locked;
          if (!S.locked) {
            mainBtn.style.background = BASE_BLUE_BG;
            if (span) {
              span.style.background = 'transparent';
              span.style.color = TEXT_COLOR;
            }
          }
        }

        return true;
      }

      function createButtonWrapper(isWishlistStyle) {
        var S = getState();
        var w = document.createElement('div');
        w.id = 'Uran-btns';
        w.setAttribute('data-assella-appid', S.appId);
        w.setAttribute('data-assella-inner', '1');
        if (isWishlistStyle) {
          w.className = 'Panel Focusable';
          w.style.cssText = 'width:100%; display:flex; flex-direction:column; gap:4px;';
        } else {
          w.className = 'queue_control_button queue_btn_uran';
          w.style.cssText = 'flex-grow:0;';
        }
        w.appendChild(makeButton(S.label, S.actionTag, S.clickLabel, S.locked, isWishlistStyle));
        return w;
      }

      /* ------------------------------------------------------------------ */
      /* Strategy 1 (Wishlist Position): Inject under/top of wishlist button*/
      /* ------------------------------------------------------------------ */
      function injectNearWishlist() {
        var allBtns = document.querySelectorAll('button, a.btnv6_blue_hoverfade, #add_to_wishlist_area a');
        var wishBtn = null;
        for (var i = 0; i < allBtns.length; i++) {
          var b = allBtns[i];
          if (b.id === 'Uran-btns' || (b.closest && b.closest('#Uran-btns'))) continue;
          if (b.offsetHeight === 0) continue;
          var t = (b.textContent || b.getAttribute('aria-label') || '').toLowerCase();
          if (t.indexOf('wishlist') !== -1) {
            wishBtn = b;
            break;
          }
        }
        if (!wishBtn) return false;

        var colItem = wishBtn.closest ? wishBtn.closest('._2YzOLNBx6TonKU0Zmp20l4') : null;
        var isGameModeWishlist = !!colItem;
        if (!colItem) {
          colItem = wishBtn.closest ? wishBtn.closest('#add_to_wishlist_area, .queue_control_button') : null;
          if (!colItem) colItem = wishBtn.parentElement;
        }
        if (!colItem || !colItem.parentElement) return false;

        var colContainer = colItem.parentElement;
        var S = getState();

        if (isGameModeWishlist) {
          var w = createButtonWrapper(true);
          var btn = w.querySelector('button');
          if (colItem.nextSibling) {
            colContainer.insertBefore(w, colItem.nextSibling);
          } else {
            colContainer.appendChild(w);
          }
          registerFocusNode(btn || w, wishBtn);
          log('injected Game Mode wishlist-style button for ' + S.appId);
          return true;
        } else {
          var w = document.createElement('div');
          w.id = 'Uran-btns';
          w.className = 'queue_control_button queue_btn_uran';
          w.setAttribute('data-assella-appid', S.appId);
          w.setAttribute('data-assella-inner', '1');
          w.style.cssText = 'flex-grow:0;';
          var btn = makeButton(S.label, S.actionTag, S.clickLabel, S.locked, false);
          w.appendChild(btn);
          if (colItem.nextSibling) {
            colContainer.insertBefore(w, colItem.nextSibling);
          } else {
            colContainer.appendChild(w);
          }
          log('injected Desktop Steam wishlist button for ' + S.appId);
          return true;
        }
      }

      /* ------------------------------------------------------------------ */
      /* Strategy 2 (New Steam React Layout): Insert button inside the      */
      /*   purchase card right before the price and Add to Cart button      */
      /* ------------------------------------------------------------------ */
      function injectReactPurchaseRow() {
        var ft = document.getElementById('FeatureTarget_purchase-options');
        if (!ft || ft.offsetHeight === 0) return false;

        /* Find the first purchase card (base game option) */
        var card = ft.querySelector('._1F2jbNP9IHRfKonl_3baY8, [class*="_1F2jbNP9IHRfKonl"]') || ft;

        /* Find the price widget or cart button in this card */
        var priceWidget = card.querySelector('.StoreSalePriceWidgetContainer, [class*="StoreSalePriceWidgetContainer"]');
        var cartBtn = card.querySelector('button[title*="Cart" i], button[title*="CART" i], button[aria-label*="cart" i]');
        var target = priceWidget || cartBtn;
        if (!target || !target.parentElement) return false;

        var row = target.parentElement;
        var w = createButtonWrapper(false);
        row.insertBefore(w, target);
        registerFocusNode(w.querySelector('button') || w, target);
        log('injected inline button before price/cart for ' + S.appId);
        return true;
      }

      /* ------------------------------------------------------------------ */
      /* Strategy 3 (Any visible Add to Cart / Price row on the page)       */
      /* ------------------------------------------------------------------ */
      function injectNearCartButton() {
        var allBtns = document.querySelectorAll('button[title*="Cart" i], button[title*="CART" i], button[aria-label*="cart" i], button');
        var cartBtn = null;
        for (var i = 0; i < allBtns.length; i++) {
          var b = allBtns[i];
          if (b.id === 'Uran-btns' || b.closest('#Uran-btns')) continue;
          if (b.offsetHeight === 0) continue;
          var title = (b.getAttribute('title') || b.getAttribute('aria-label') || b.textContent || '').trim().toUpperCase();
          if (title.indexOf('ADD TO CART') !== -1 || title === 'ADD TO CART') {
            cartBtn = b;
            break;
          }
        }
        if (!cartBtn || !cartBtn.parentElement) return false;

        var row = cartBtn.parentElement;
        var price = row.querySelector('.StoreSalePriceWidgetContainer, [class*="StoreSalePriceWidgetContainer"], .game_purchase_price');
        var insertBeforeTarget = price || cartBtn;

        var w = createButtonWrapper(false);
        row.insertBefore(w, insertBeforeTarget);
        registerFocusNode(w.querySelector('button') || w, insertBeforeTarget);
        log('injected inline button near cart/price for ' + S.appId);
        return true;
      }

      /* ------------------------------------------------------------------ */
      /* Strategy 4 (Legacy Steam Store): .game_purchase_action             */
      /* ------------------------------------------------------------------ */
      function injectOldSteamAction() {
        var actionArea = document.querySelector('.game_purchase_action');
        if (!actionArea || actionArea.offsetHeight === 0) return false;

        var w = createButtonWrapper(false);
        if (actionArea.firstChild) {
          actionArea.insertBefore(w, actionArea.firstChild);
        } else {
          actionArea.appendChild(w);
        }
        log('injected legacy purchase action button for ' + S.appId);
        return true;
      }

      /* ------------------------------------------------------------------ */
      /* Strategy 5 (Fallback banner): prepend to purchase area             */
      /* ------------------------------------------------------------------ */
      function injectFallback() {
        var hosts = document.querySelectorAll('.game_area_purchase, #game_area_purchase, #purchaseOptionsContent');
        var host = null;
        for (var i = 0; i < hosts.length; i++) {
          if (hosts[i].offsetHeight > 0) { host = hosts[i]; break; }
        }
        if (!host) return false;

        var S = getState();
        var w = document.createElement('div');
        w.id = 'Uran-btns';
        w.setAttribute('data-assella-appid', S.appId);
        w.style.cssText = 'padding:14px; margin:12px 0; background:rgba(0,0,0,0.35); border-radius:6px; display:flex; gap:8px; align-items:center;';
        w.appendChild(makeButton(S.label, S.actionTag, S.clickLabel, S.locked, false));
        host.prepend(w);
        log('fallback banner injected for ' + S.appId);
        return true;
      }

      /* ------------------------------------------------------------------ */
      /* Main injection orchestrator — tries strategies in priority order    */
      /* ------------------------------------------------------------------ */
      function injectFromState() {
        var S = getState();
        if (!S.appId) return;

        var existing = findExisting();
        if (existing) {
          if (updateExisting(existing)) return;
          existing.remove();
        }

        if (injectNearWishlist()) return;
        if (injectReactPurchaseRow()) return;
        if (injectNearCartButton()) return;
        if (injectOldSteamAction()) return;
        if (injectFallback()) return;
        log('no supported purchase area found for ' + S.appId);
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

  if (!addedAppIds.has(appId) && labelOverride === undefined) {
    try {
      const added = await isAppAdded(appId);
      if (added) {
        addedAppIds.add(appId);
      }
    } catch {}
  }

  const isAdded = addedAppIds.has(appId);
  const isPending = !isAdded && pendingAppIds.has(appId);
  const isRefetching = isAdded && refetchingAppIds.has(appId);

  const label =
    labelOverride ??
    (isRefetching
      ? "Refetching..."
      : isAdded
      ? "Refetch from Hubcap"
      : isPending
      ? "Adding..."
      : "Add to Uran");
  const locked = lockedOverride ?? (isPending || isRefetching);
  const actionTag = isAdded ? ASSELLA_REFETCH_TAG : ASSELLA_ADD_TAG;
  const clickLabel = isAdded ? "Refetching..." : "Adding...";
  const tooltip =
    isRefetching || label === "Refetching..."
      ? "Refetching manifests and depot keys..."
      : isAdded || label === "Refetch from Hubcap"
      ? "Refetch manifests and depot keys from Hubcap"
      : isPending || label === "Adding..."
      ? "Adding game to library..."
      : "Add game to at0-m plugin and download from your library!";

  const stateScript =
    "(function(){try{" +
    "var S=window.__assellaStoreState;if(!S){S={};window.__assellaStoreState=S;}" +
    "S.appId=" +
    JSON.stringify(appId) +
    ";S.label=" +
    JSON.stringify(label) +
    ";S.tooltip=" +
    JSON.stringify(tooltip) +
    ";S.actionTag=" +
    JSON.stringify(actionTag) +
    ";S.clickLabel=" +
    JSON.stringify(clickLabel) +
    ";S.locked=" +
    JSON.stringify(locked) +
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
        "if(window.__assellaUranFocusNode){try{window.__assellaUranFocusNode.OnUnmount();}catch(e){}window.__assellaUranFocusNode=null;}" +
        "var s=document.querySelectorAll('#assella-purchase-slot, #Uran-btns');" +
        "for(var i=0;i<s.length;i++){s[i].remove();}" +
        "}catch(e){}})();",
    },
  });
}

function handleStoreAdd(appId: string): void {
  slog("webview add click: " + appId);
  if (addedAppIds.has(appId)) {
    handleStoreRefetch(appId);
    return;
  }
  pendingAppIds.add(appId);
  inject(appId, true, "Adding...", true);
  injectGame(appId)
    .then((r: any) => {
      if (r && r.already_added) {
        pendingAppIds.delete(appId);
        addedAppIds.add(appId);
        notify("Uran", r.error || "This game is already registered in your library.");
        inject(appId, true, "Refetch from Hubcap", false);
        return;
      }
      if (r && !r.error) {
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
          inject(appId, true, "Refetch from Hubcap", false);
        });
      } else {
        pendingAppIds.delete(appId);
        if (r?.blocked === "no_api_key" || r?.error?.includes("No Hubcap API key")) {
          showQrKeyModal(() => handleStoreAdd(appId));
        } else {
          notify(
            "Uran",
            r?.error || `Failed to add game ${appId}`,
          );
        }
        inject(appId, true);
      }
    })
    .catch((e: any) => {
      pendingAppIds.delete(appId);
      notify("Uran", `Failed to add game ${appId}: ${e}`);
      inject(appId, true);
    });
}

function handleStoreRefetch(appId: string): void {
  slog("webview refetch click: " + appId);
  refetchingAppIds.add(appId);
  inject(appId, true, "Refetching...", true);
  notify("Uran", `Refetching Hubcap manifests & keys for app ${appId}...`);
  refetchGame(appId)
    .then((r: any) => {
      refetchingAppIds.delete(appId);
      if (r?.ok) {
        const added = r.depots_added?.length || 0;
        const keys = r.keys_added?.length || 0;
        notify(
          "Uran",
          `Refetched ${r.name || appId} (${added} depot${added === 1 ? "" : "s"}, ${keys} key${keys === 1 ? "" : "s"})`,
        );
      } else {
        notify("Uran", r?.error || `Refetch failed for ${appId}`);
      }
      inject(appId, true, "Refetch from Hubcap", false);
    })
    .catch((e: any) => {
      refetchingAppIds.delete(appId);
      notify("Uran", `Refetch failed for ${appId}: ${e}`);
      inject(appId, true, "Refetch from Hubcap", false);
    });
}

async function connect(tab: StoreTab): Promise<void> {
  if (!storePatchEnabled || !tab.webSocketDebuggerUrl) return;
  if (storeSocket) {
    try {
      storeSocket.close();
    } catch {}
    storeSocket = null;
    wsReady = false;
  }
  slog("CDP: connecting to " + tab.webSocketDebuggerUrl);
  const socket = new WebSocket(tab.webSocketDebuggerUrl);
  storeSocket = socket;
  socket.onopen = () => {
    if (!storePatchEnabled || storeSocket !== socket) {
      socket.close();
      return;
    }
    wsSend({ id: messageId++, method: "Page.enable" });
    wsSend({ id: messageId++, method: "Runtime.enable" });
    syncAddedAppIds().catch(() => {});
    setTimeout(() => {
      if (!storePatchEnabled || storeSocket !== socket) return;
      wsReady = true;
      const appId = extractAppId(tab.url);
      if (appId) inject(appId, true);
    }, 1500);
  };
  socket.onmessage = (ev) => {
    if (!storePatchEnabled || storeSocket !== socket) return;
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
            } else if (arg.value.startsWith(ASSELLA_REFETCH_TAG)) {
              const appId = arg.value.slice(ASSELLA_REFETCH_TAG.length);
              handleStoreRefetch(appId);
            } else if (arg.value.startsWith(ASSELLA_ADD_TAG)) {
              const appId = arg.value.slice(ASSELLA_ADD_TAG.length);
              handleStoreAdd(appId);
            } else if (arg.value.startsWith(ASSELLA_TAG)) {
              const appId = arg.value.slice(ASSELLA_TAG.length);
              if (addedAppIds.has(appId)) {
                handleStoreRefetch(appId);
              } else {
                handleStoreAdd(appId);
              }
            }
          }
        }
      }
    } catch {}
  };
  socket.onerror = () => {
    if (storeSocket !== socket) return;
    slog("CDP: socket error");
    wsReady = false;
  };
  socket.onclose = () => {
    if (storeSocket !== socket) return;
    slog("CDP: socket closed");
    storeSocket = null;
    wsReady = false;
  };
}

async function pollCdp(): Promise<void> {
  if (!storePatchEnabled) return;
  try {
    const res = await discoverStoreTab();
    if (!storePatchEnabled) return;
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
  syncAddedAppIds().catch(() => {});
  const thisLifecycle = ++lifecycle;
  getSetting("steam_store_enabled", true)
    .then((enabled) => {
      if (lifecycle === thisLifecycle) setStorePatchEnabled(enabled !== false);
    })
    .catch((error) => {
      slog("could not read Steam Store setting; leaving injection enabled: " + error);
      if (lifecycle === thisLifecycle) setStorePatchEnabled(true);
    });
  return () => {
    slog("initStorePatch: cleanup");
    lifecycle++;
    setStorePatchEnabled(false);
  };
}

export function setStorePatchEnabled(enabled: boolean): void {
  if (storePatchEnabled === enabled) return;
  storePatchEnabled = enabled;
  if (enabled) {
    slog("Steam Store button injection enabled");
    stopRouteSpy = initRouteSpy();
    startPoll();
  } else {
    slog("Steam Store button injection disabled");
    stopPoll();
    stopRouteSpy?.();
    stopRouteSpy = null;
  }
}
