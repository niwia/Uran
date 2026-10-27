// ==UserScript==
// @name         Photar — Steam & SteamDB at0-m Bridge
// @namespace    https://github.com/niwia/Uran
// @version      1.1.0
// @description  1-click game injection into SLSsteam via at0-m for Steam Store & SteamDB
// @author       niwia, ASSella Team
// @match        *://store.steampowered.com/app/*
// @match        *://steamdb.info/app/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @run-at       document-end
// ==/UserScript==

(function () {
  'use strict';

  var EPSILON_URL = 'http://127.0.0.1:1952';
  var POLL_INTERVAL_MS = 1500;
  var MAX_POLLS = 40;

  var BASE_BLUE_BG = 'rgba(103, 193, 245, 0.2)';
  var BASE_BLUE_HOVER_BG = 'rgba(103, 193, 245, 0.4)';
  var TEXT_COLOR = '#67c1f5';
  var TEXT_HOVER_COLOR = '#ffffff';
  var TOOLTIP_TEXT = 'Add game to at0-m plugin and download from your library!';

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

    function applyState(newState, labelOverride, titleOverride) {
      state = newState;
      if (!btn || !span) return;

      var lbl = labelOverride;
      var tip = titleOverride || TOOLTIP_TEXT;

      if (!lbl) {
        if (state === 'READY') lbl = 'Add to at0-m';
        else if (state === 'IN_LIBRARY') lbl = 'In Library';
        else if (state === 'ADDING') lbl = 'Adding...';
        else if (state === 'OFFLINE') lbl = 'Add to at0-m';
        else if (state === 'ERROR') lbl = 'Failed';
        else lbl = 'Add to at0-m';
      }

      span.textContent = lbl;
      btn.title = tip;
      btn.setAttribute('aria-label', tip);

      if (isSteamDB) {
        btn.setAttribute('aria-label', tip);
        if (state === 'IN_LIBRARY') {
          btn.style.borderColor = '#4ade80';
          span.style.color = '#86efac';
        } else if (state === 'ADDING') {
          btn.style.opacity = '0.7';
        } else {
          btn.style.opacity = '1';
          btn.style.borderColor = '';
          span.style.color = '';
        }
      } else {
        btn.setAttribute('data-tooltip-text', tip);
        if (state === 'IN_LIBRARY') {
          btn.style.background = 'rgba(74, 222, 128, 0.2)';
          span.style.color = '#86efac';
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
            applyState('OFFLINE', null, 'Bridge offline. Start Epsilon or Uran to enable.');
            return;
          }
          return req('GET', '/status?appid=' + appId);
        })
        .then(function (statusRes) {
          if (!statusRes) return;
          if (statusRes.ok && statusRes.data && statusRes.data.added) {
            applyState('IN_LIBRARY', 'In Library', 'Game is registered in your at0-m library.');
          } else {
            applyState('READY');
          }
        })
        .catch(function () {
          applyState('OFFLINE', null, 'Bridge offline. Start Epsilon or Uran to enable.');
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
                  applyState('ERROR', 'Failed', injectStatus.error);
                  setTimeout(checkStatus, 4000);
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

      if (state === 'IN_LIBRARY') {
        var confirmed = confirm(
          'App ' + appId + ' is already in your at0-m library.\n\nDo you want to re-project configuration and fetch fresh decryption keys?'
        );
        if (!confirmed) return;

        applyState('ADDING', 'Refetching...');
        req('POST', '/refetch', { appid: appId })
          .then(function () {
            applyState('IN_LIBRARY', 'In Library');
          })
          .catch(function () {
            applyState('IN_LIBRARY', 'In Library');
          });
        return;
      }

      applyState('ADDING', 'Adding...');
      req('POST', '/inject', { appid: appId })
        .then(function (res) {
          if (!res.ok || !res.data) {
            applyState('ERROR', 'Failed', 'Connection error');
            setTimeout(checkStatus, 3000);
            return;
          }

          if (res.data.already_added) {
            applyState('IN_LIBRARY', 'In Library');
            return;
          }

          if (res.data.ok === false) {
            applyState('ERROR', 'Failed', res.data.error || 'Injection failed');
            setTimeout(checkStatus, 4000);
            return;
          }

          applyState('ADDING', 'Adding...');
          startPolling();
        })
        .catch(function (err) {
          applyState('ERROR', 'Failed', err.message || 'Injection failed');
          setTimeout(checkStatus, 3000);
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

      btn.addEventListener('click', handleClick);

      // Injection logic matching CS.RIN.RU Enhanced
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

    // 2. Create Element for Steam Store (matches Uran StorePatch)
    btn = document.createElement('a');
    btn.id = 'at0m-store-btn';
    btn.className = 'btnv6_blue_hoverfade btn_medium queue_btn_inactive';
    btn.href = 'javascript:void(0);';
    btn.style.cssText =
      'display:inline-block;' +
      'background:' + BASE_BLUE_BG + ';' +
      'border:none;' +
      'border-radius:2px;' +
      'padding:1px;' +
      'cursor:pointer;' +
      'text-decoration:none;' +
      'margin-right:4px;' +
      'vertical-align:middle;' +
      'transition:all 0.2s ease;';

    span = document.createElement('span');
    span.style.cssText =
      'display:block;' +
      'background:transparent;' +
      'color:' + TEXT_COLOR + ';' +
      'border-radius:2px;' +
      'font-family:"Motiva Sans", Arial, sans-serif;' +
      'font-size:15px;' +
      'line-height:30px;' +
      'padding:0 15px;' +
      'text-align:center;' +
      'white-space:nowrap;' +
      'transition:all 0.2s ease;';
    span.textContent = 'Add to at0-m';
    btn.appendChild(span);

    btn.addEventListener('mouseenter', function () {
      if (state !== 'ADDING') {
        btn.style.background = state === 'IN_LIBRARY' ? 'rgba(74, 222, 128, 0.35)' : BASE_BLUE_HOVER_BG;
        span.style.color = state === 'IN_LIBRARY' ? '#ffffff' : TEXT_HOVER_COLOR;
      }
    });

    btn.addEventListener('mouseleave', function () {
      if (state !== 'ADDING') {
        btn.style.background = state === 'IN_LIBRARY' ? 'rgba(74, 222, 128, 0.2)' : BASE_BLUE_BG;
        span.style.color = state === 'IN_LIBRARY' ? '#86efac' : TEXT_COLOR;
      }
    });

    btn.addEventListener('click', handleClick);

    var wrap = document.createElement('div');
    wrap.id = 'at0m-store-wrap';
    wrap.style.cssText = 'display:inline-block; margin:4px 0; vertical-align:middle;';
    wrap.appendChild(btn);

    // Target injection positions on Steam Store
    var wishlistArea =
      document.querySelector('#add_to_wishlist_area') ||
      document.querySelector('.queue_actions_ctn') ||
      document.querySelector('.game_area_purchase_action') ||
      document.querySelector('#game_area_purchase');

    if (wishlistArea) {
      if (wishlistArea.id === 'add_to_wishlist_area' || wishlistArea.classList.contains('queue_actions_ctn')) {
        wishlistArea.insertAdjacentElement('afterbegin', wrap);
      } else {
        wishlistArea.insertAdjacentElement('beforebegin', wrap);
      }
      checkStatus();
    }
  }

  function mount() {
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
      if (!document.getElementById('at0m-store-btn') && !document.getElementById('at0m-steamdb-btn')) {
        mount();
      }
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });
})();
