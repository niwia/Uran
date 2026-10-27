// ==UserScript==
// @name         Photar — Steam & SteamDB at0-m Bridge
// @namespace    https://github.com/niwia/Uran
// @version      1.3.0
// @description  1-click game injection into SLSsteam via at0-m for Steam Store & SteamDB
// @author       niwia, ASSella Team
// @match        *://store.steampowered.com/app/*
// @match        *://steamdb.info/app/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @updateURL    https://raw.githubusercontent.com/niwia/Uran/main/photar/photar.user.js
// @downloadURL  https://raw.githubusercontent.com/niwia/Uran/main/photar/photar.user.js
// @run-at       document-end
// ==/UserScript==

(function () {
  'use strict';

  var EPSILON_URL = 'http://127.0.0.1:1952';
  var POLL_INTERVAL_MS = 1500;
  var MAX_POLLS = 40;

  var BASE_BLUE_BG = 'rgba(103, 193, 245, 0.2)';
  var BASE_BLUE_HOVER_BG = 'linear-gradient(-60deg, #417a9b 5%, #67c1f5 95%)';
  var TEXT_COLOR = '#67c1f5';
  var TEXT_HOVER_COLOR = '#ffffff';

  var IN_LIBRARY_BG = 'rgba(74, 222, 128, 0.2)';
  var IN_LIBRARY_HOVER_BG = 'linear-gradient(-60deg, #15803d 5%, #4ade80 95%)';
  var IN_LIBRARY_TEXT = '#86efac';

  var ERROR_BG = 'rgba(239, 68, 68, 0.2)';
  var ERROR_HOVER_BG = 'linear-gradient(-60deg, #991b1b 5%, #ef4444 95%)';
  var ERROR_TEXT = '#ef4444';

  var DEFAULT_GUIDE_URL = 'https://assella.niwia.top/epsilon';
  var TOOLTIP_TEXT = 'Add game to at0-m plugin and download from your library!';

  function isDlcPage() {
    // 1. Steam Store DLC indicator
    if (document.querySelector('.game_area_dlc_bubble, div.game_area_bubble.game_area_dlc_bubble')) {
      return true;
    }
    // 2. SteamDB DLC indicator
    var tables = document.querySelectorAll('.table-bordered tr');
    for (var i = 0; i < tables.length; i++) {
      var cells = tables[i].children;
      if (cells.length >= 2 && cells[0].textContent.trim() === 'App Type') {
        if (cells[1].textContent.trim().toUpperCase() === 'DLC') {
          return true;
        }
      }
    }
    return false;
  }

  function getAppId() {
    var match = window.location.pathname.match(/\/app\/(\d+)/);
    if (match) return match[1];
    var firstEntry = document.querySelector('.span3');
    if (firstEntry && firstEntry.nextElementSibling) {
      var candidate = firstEntry.nextElementSibling.textContent.trim();
      if (/^\d+$/.test(candidate)) return candidate;
    }
    return null;
  }

  function req(method, path, body) {
    return new Promise(function (resolve, reject) {
      GM_xmlhttpRequest({
        method: method,
        url: EPSILON_URL + path,
        headers: {
          'Content-Type': 'application/json',
          'X-Photar-Client': '1'
        },
        data: body ? JSON.stringify(body) : null,
        timeout: 8000,
        onload: function (res) {
          try {
            var data = JSON.parse(res.responseText);
            resolve({ ok: true, status: res.status, data: data });
          } catch (e) {
            resolve({ ok: false, status: res.status, text: res.responseText });
          }
        },
        ontimeout: function () {
          reject(new Error('Timeout connecting to local bridge'));
        },
        onerror: function (err) {
          reject(err);
        },
      });
    });
  }

  function initBridge(appId) {
    var state = 'INITIALIZING';
    var isSteamDB = window.location.hostname.indexOf('steamdb.info') !== -1;
    var btn = null;
    var span = null;
    var pollTimer = null;
    var pollCount = 0;
    var guideUrl = DEFAULT_GUIDE_URL;
    var currentErrorCode = null;
    var currentErrorMsg = null;

    function applyState(newState, labelOverride, titleOverride) {
      state = newState;
      if (!btn || !span) return;

      var lbl = labelOverride;
      var tip = titleOverride || TOOLTIP_TEXT;

      if (!lbl) {
        if (state === 'READY') lbl = 'Add to at0-m';
        else if (state === 'IN_LIBRARY') lbl = 'In Library';
        else if (state === 'ADDING') lbl = 'Adding...';
        else if (state === 'ERROR') lbl = currentErrorCode || '707';
        else lbl = 'Add to at0-m';
      }

      if (state === 'ERROR') {
        tip = currentErrorMsg
          ? '[Error ' + (currentErrorCode || '707') + '] ' + currentErrorMsg + ' — Click to view guide'
          : '[Error ' + (currentErrorCode || '707') + '] Click for troubleshooting guide';
      }

      span.textContent = lbl;
      btn.title = tip;
      btn.setAttribute('aria-label', tip);

      if (isSteamDB) {
        btn.setAttribute('aria-label', tip);
        if (state === 'IN_LIBRARY') {
          btn.style.borderColor = '#4ade80';
          span.style.color = IN_LIBRARY_TEXT;
        } else if (state === 'ERROR') {
          btn.style.borderColor = '#ef4444';
          span.style.color = ERROR_TEXT;
        } else if (state === 'ADDING') {
          btn.style.opacity = '0.7';
          btn.style.borderColor = '';
          span.style.color = '';
        } else {
          btn.style.opacity = '1';
          btn.style.borderColor = '';
          span.style.color = '';
        }
      } else {
        btn.setAttribute('data-tooltip-text', tip);
        if (state === 'IN_LIBRARY') {
          btn.style.opacity = '1';
          btn.style.background = IN_LIBRARY_BG;
          span.style.color = IN_LIBRARY_TEXT;
        } else if (state === 'ERROR') {
          btn.style.opacity = '1';
          btn.style.background = ERROR_BG;
          span.style.color = ERROR_TEXT;
        } else if (state === 'ADDING') {
          btn.style.opacity = '0.7';
          btn.style.background = BASE_BLUE_BG;
          span.style.color = TEXT_COLOR;
        } else {
          btn.style.opacity = '1';
          btn.style.background = BASE_BLUE_BG;
          span.style.color = TEXT_COLOR;
        }
      }
    }

    function checkStatus() {
      req('GET', '/ping')
        .then(function (pingRes) {
          if (!pingRes.ok || !pingRes.data || pingRes.data.service !== 'epsilon') {
            currentErrorCode = '505';
            currentErrorMsg = 'Bridge offline. Start Epsilon or Uran to enable.';
            guideUrl = 'https://assella.niwia.top/epsilon#err-505';
            applyState('ERROR');
            return;
          }
          if (pingRes.data.guide_url) {
            guideUrl = pingRes.data.guide_url;
          }
          if (pingRes.data.ready === false || pingRes.data.error_code) {
            currentErrorCode = pingRes.data.error_code || '504';
            currentErrorMsg = pingRes.data.error || 'System prerequisite missing';
            guideUrl = pingRes.data.guide_url || ('https://assella.niwia.top/epsilon#err-' + currentErrorCode);
          }
          return req('GET', '/status?appid=' + appId);
        })
        .then(function (statusRes) {
          if (!statusRes) return;
          if (statusRes.ok && statusRes.data) {
            if (statusRes.data.guide_url) {
              guideUrl = statusRes.data.guide_url;
            }
            if (statusRes.data.added) {
              applyState('IN_LIBRARY', 'In Library', 'Game is registered in your at0-m library. Click to refetch keys.');
            } else if (currentErrorCode) {
              applyState('ERROR');
            } else if (!statusRes.data.ready || statusRes.data.error_code) {
              currentErrorCode = statusRes.data.error_code || '707';
              currentErrorMsg = statusRes.data.error || 'Error occurred';
              guideUrl = statusRes.data.guide_url || ('https://assella.niwia.top/epsilon#err-' + currentErrorCode);
              applyState('ERROR');
            } else {
              applyState('READY');
            }
          } else {
            if (currentErrorCode) {
              applyState('ERROR');
            } else {
              applyState('READY');
            }
          }
        })
        .catch(function () {
          currentErrorCode = '505';
          currentErrorMsg = 'Bridge offline. Start Epsilon or Uran to enable.';
          guideUrl = 'https://assella.niwia.top/epsilon#err-505';
          applyState('ERROR');
        });
    }

    function startPolling() {
      if (pollTimer) clearInterval(pollTimer);
      pollCount = 0;
      pollTimer = setInterval(function () {
        pollCount++;
        if (pollCount > MAX_POLLS) {
          clearInterval(pollTimer);
          applyState('IN_LIBRARY', 'In Library');
          return;
        }

        req('GET', '/status?appid=' + appId)
          .then(function (res) {
            if (res.ok && res.data) {
              var injectStatus = res.data.inject_status;
              if (injectStatus && injectStatus.done) {
                clearInterval(pollTimer);
                if (injectStatus.error) {
                  currentErrorCode = res.data.error_code || '701';
                  currentErrorMsg = injectStatus.error;
                  guideUrl = res.data.guide_url || ('https://assella.niwia.top/epsilon#err-' + currentErrorCode);
                  applyState('ERROR');
                } else {
                  applyState('IN_LIBRARY', 'In Library');
                }
              } else if (res.data.added && !injectStatus) {
                clearInterval(pollTimer);
                applyState('IN_LIBRARY', 'In Library');
              }
            }
          })
          .catch(function () {});
      }, POLL_INTERVAL_MS);
    }

    function handleClick(e) {
      e.preventDefault();
      e.stopPropagation();

      if (state === 'ADDING') return;

      if (state === 'ERROR') {
        var errTarget = guideUrl || ('https://assella.niwia.top/epsilon#err-' + (currentErrorCode || '707'));
        window.open(errTarget, '_blank');
        return;
      }

      if (state === 'IN_LIBRARY') {
        var confirmed = confirm(
          'App ' + appId + ' is already registered in your library.\n\nDo you want to re-project configuration and fetch fresh decryption keys?'
        );
        if (!confirmed) return;

        applyState('ADDING', 'Refetching...');
        req('POST', '/refetch', { appid: appId })
          .then(function (res) {
            if (res.ok && res.data && res.data.ok === false) {
              currentErrorCode = res.data.error_code || '707';
              currentErrorMsg = res.data.error || 'Refetch failed';
              guideUrl = res.data.guide_url || ('https://assella.niwia.top/epsilon#err-' + currentErrorCode);
              applyState('ERROR');
            } else {
              applyState('IN_LIBRARY', 'In Library');
            }
          })
          .catch(function () {
            currentErrorCode = '505';
            currentErrorMsg = 'Bridge connection failed during refetch';
            guideUrl = 'https://assella.niwia.top/epsilon#err-505';
            applyState('ERROR');
          });
        return;
      }

      applyState('ADDING', 'Adding...');
      req('POST', '/inject', { appid: appId })
        .then(function (res) {
          if (!res.ok || !res.data) {
            currentErrorCode = '505';
            currentErrorMsg = 'Bridge offline or connection refused';
            guideUrl = 'https://assella.niwia.top/epsilon#err-505';
            applyState('ERROR');
            return;
          }

          if (res.data.already_added) {
            applyState('IN_LIBRARY', 'In Library');
            return;
          }

          if (res.data.ok === false || res.data.error_code) {
            currentErrorCode = res.data.error_code || '707';
            currentErrorMsg = res.data.error || 'Injection failed';
            guideUrl = res.data.guide_url || ('https://assella.niwia.top/epsilon#err-' + currentErrorCode);
            applyState('ERROR');
            return;
          }

          applyState('ADDING', 'Adding...');
          startPolling();
        })
        .catch(function (err) {
          currentErrorCode = '505';
          currentErrorMsg = err.message || 'Bridge offline';
          guideUrl = 'https://assella.niwia.top/epsilon#err-505';
          applyState('ERROR');
        });
    }

    // 1. Create Element for SteamDB
    if (isSteamDB) {
      btn = document.createElement('a');
      btn.id = 'at0m-steamdb-btn';
      btn.className = 'btn tooltipped tooltipped-n';
      btn.href = 'javascript:void(0);';
      btn.style.marginRight = '4px';
      btn.style.cursor = 'pointer';

      span = document.createElement('span');
      span.textContent = 'Add to at0-m';
      btn.appendChild(span);

      btn.addEventListener('mouseenter', function () {
        if (state === 'ERROR') {
          btn.style.backgroundColor = '#ef4444';
          span.style.color = '#ffffff';
        } else if (state === 'IN_LIBRARY') {
          btn.style.backgroundColor = '#4ade80';
          span.style.color = '#000000';
        }
      });

      btn.addEventListener('mouseleave', function () {
        if (state === 'ERROR') {
          btn.style.backgroundColor = '';
          span.style.color = ERROR_TEXT;
        } else if (state === 'IN_LIBRARY') {
          btn.style.backgroundColor = '';
          span.style.color = IN_LIBRARY_TEXT;
        }
      });

      btn.addEventListener('click', handleClick);

      var siteSelectors = {
        steamdb: function () {
          var appLinks = document.querySelectorAll('.app-links');
          if (appLinks.length > 1 && appLinks[1].firstElementChild) {
            return appLinks[1].firstElementChild;
          }
          if (appLinks.length > 0 && appLinks[0].firstElementChild) {
            return appLinks[0].firstElementChild;
          }
          var pagehead = document.querySelector('.pagehead-actions');
          if (pagehead && pagehead.firstElementChild) {
            return pagehead.firstElementChild;
          }
          return null;
        },
      };

      var target = siteSelectors.steamdb();
      if (target) {
        target.insertAdjacentElement('beforebegin', btn);
        checkStatus();
      }
      return;
    }

    // 2. Create Element for Steam Store (matches Steam native button layout)
    btn = document.createElement('a');
    btn.id = 'at0m-store-btn';
    btn.className = 'btnv6_blue_hoverfade btn_medium queue_btn_inactive';
    btn.href = 'javascript:void(0);';
    btn.style.cssText =
      'display:block;' +
      'background:' + BASE_BLUE_BG + ';' +
      'border:none;' +
      'border-radius:2px;' +
      'padding:1px;' +
      'cursor:pointer;' +
      'text-decoration:none;' +
      'transition:all 0.2s ease;';

    span = document.createElement('span');
    span.style.cssText =
      'display:block;' +
      'background:transparent;' +
      'color:' + TEXT_COLOR + ';' +
      'font-family:"Motiva Sans", Arial, Helvetica, sans-serif;' +
      'font-size:15px;' +
      'line-height:30px;' +
      'padding:0 15px;' +
      'text-align:center;' +
      'white-space:nowrap;' +
      'transition:all 0.2s ease;';
    span.textContent = 'Add to at0-m';
    btn.appendChild(span);

    btn.addEventListener('mouseenter', function () {
      if (state === 'ADDING') return;
      if (state === 'IN_LIBRARY') {
        btn.style.background = IN_LIBRARY_HOVER_BG;
        span.style.color = '#ffffff';
      } else if (state === 'ERROR') {
        btn.style.background = ERROR_HOVER_BG;
        span.style.color = '#ffffff';
      } else {
        btn.style.background = BASE_BLUE_HOVER_BG;
        span.style.color = TEXT_HOVER_COLOR;
      }
    });

    btn.addEventListener('mouseleave', function () {
      if (state === 'ADDING') return;
      if (state === 'IN_LIBRARY') {
        btn.style.background = IN_LIBRARY_BG;
        span.style.color = IN_LIBRARY_TEXT;
      } else if (state === 'ERROR') {
        btn.style.background = ERROR_BG;
        span.style.color = ERROR_TEXT;
      } else {
        btn.style.background = BASE_BLUE_BG;
        span.style.color = TEXT_COLOR;
      }
    });

    btn.addEventListener('click', handleClick);

    var wrap = document.createElement('div');
    wrap.id = 'at0m-store-wrap';
    wrap.appendChild(btn);

    // Target injection positions on Steam Store
    var injected = false;

    // Strategy A: Next to Wishlist button inside .queue_actions_ctn
    var wishArea = document.querySelector('#add_to_wishlist_area');
    var queueCtn = document.querySelector('.queue_actions_ctn');

    if (wishArea) {
      var wishCol = wishArea.closest('.queue_control_button') || wishArea;
      if (wishCol.parentElement) {
        wrap.className = 'queue_control_button queue_btn_at0m';
        wrap.style.cssText = 'float:left; margin-right:4px; margin-bottom:4px;';
        wishCol.parentElement.insertBefore(wrap, wishCol.nextSibling || wishCol);
        injected = true;
      }
    } else if (queueCtn) {
      wrap.className = 'queue_control_button queue_btn_at0m';
      wrap.style.cssText = 'float:left; margin-right:4px; margin-bottom:4px;';
      queueCtn.appendChild(wrap);
      injected = true;
    }

    // Strategy B: Fallback to the purchase area (e.g. Free-to-play or games without wishlist)
    if (!injected) {
      var purchaseAction =
        document.querySelector('.game_area_purchase_game .game_purchase_action') ||
        document.querySelector('.game_purchase_action');
      if (purchaseAction) {
        wrap.className = 'at0m_purchase_action_wrap';
        wrap.style.cssText = 'display:inline-block; margin-right:6px; vertical-align:middle;';
        var cartBtn = purchaseAction.querySelector('.btn_addtocart') || purchaseAction.firstElementChild;
        if (cartBtn) {
          purchaseAction.insertBefore(wrap, cartBtn);
        } else {
          purchaseAction.appendChild(wrap);
        }
        injected = true;
      }
    }

    if (injected) {
      checkStatus();
    }
  }

  function mount() {
    if (isDlcPage()) {
      return;
    }

    var appId = getAppId();
    if (!appId) return;

    if (document.getElementById('at0m-store-btn') || document.getElementById('at0m-steamdb-btn')) {
      return;
    }

    initBridge(appId);
  }

  mount();

  var lastUrl = window.location.href;
  var observer = new MutationObserver(function () {
    if (window.location.href !== lastUrl) {
      lastUrl = window.location.href;
      var existingStore = document.getElementById('at0m-store-wrap');
      if (existingStore) existingStore.remove();
      var existingDb = document.getElementById('at0m-steamdb-btn');
      if (existingDb) existingDb.remove();
      setTimeout(mount, 500);
    } else {
      if (!isDlcPage() && !document.getElementById('at0m-store-btn') && !document.getElementById('at0m-steamdb-btn')) {
        mount();
      }
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });
})();

