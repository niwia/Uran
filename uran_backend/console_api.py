"""AT0-M web console API — token-gated ``/v1`` surface for Epsilon.

Photar (the userscript) keeps its own routes and is untouched. The console is a
web page from ASSella's docs origin, so it gets a separate namespace with a real
credential: a per-install token in ``settings.json``, generated on first daemon
start, shown by ASSella, handed over in the URL fragment and compared with
``hmac.compare_digest``. CORS alone is not auth.

Register calls ``Injector.inject(app_id)`` exactly like Photar, so keys and
manifests are resolved on this machine from the local Hubcap key: a page can
never write arbitrary decryption keys into ``config.yaml``. Responses carry no
keys, only presence and masks.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import threading
import time
from typing import Any

from .epsilon_responses import inject_response, guide_url
from .sls_config import sanitize_id

logger = logging.getLogger("Epsilon")

TOKEN_SETTING = "epsilon_console_token"
ENABLED_SETTING = "epsilon_console_enabled"
TOKEN_PREFIX = "at0m_"
CLIENT_HEADER = "x-at0m-client"
MAX_BODY_BYTES = 256 * 1024

# Only non-secret knobs; every value is validated before it is written.
SETTINGS_SCHEMA: dict[str, tuple[str, tuple[str, ...]]] = {
    "fetch_dlcs_on_inject": ("bool", ()),
    "add_delisted_dlcs": ("bool", ()),
    "hubcap_gateway": ("enum", ("auto", "direct", "proxy")),
    "notification_mode": ("enum", ("auto", "steam", "desktop", "none")),
    # Shared with Uran/ASSella: the Steam Store button patch. Epsilon only
    # stores the switch and reports whether Steam is exposing its CEF
    # debugging port; the DOM patch itself stays in Uran.
    "steam_store_enabled": ("bool", ()),
    # Shared with ASSella: expose epsilon.socket on 0.0.0.0:1952 for same-Wi-Fi phone access.
    "epsilon_console_lan": ("bool", ()),
}


def _detect_lan_ip() -> str:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("1.1.1.1", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _apply_lan_socket(enabled: bool) -> None:
    """Write/remove epsilon.socket.d/lan.conf and reload/restart epsilon.socket."""
    import subprocess
    from pathlib import Path

    cfg_home = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    dropin_dir = cfg_home / "systemd" / "user" / "epsilon.socket.d"
    lan_conf = dropin_dir / "lan.conf"
    if enabled:
        dropin_dir.mkdir(parents=True, exist_ok=True)
        lan_conf.write_text("[Socket]\nListenStream=\nListenStream=0.0.0.0:1952\n", encoding="utf-8")
    elif lan_conf.exists():
        lan_conf.unlink()

    def _restart():
        time.sleep(0.35)
        try:
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, timeout=5)
            subprocess.run(["systemctl", "--user", "restart", "epsilon.socket"], capture_output=True, timeout=8)
        except Exception as exc:
            logger.debug("Failed restarting epsilon.socket for LAN change: %s", exc)

    threading.Thread(target=_restart, daemon=True).start()

_FAIL_WINDOW = 60.0
_FAIL_LIMIT = 8
_LOCKOUT = 60.0
_fail_lock = threading.Lock()
_fail_state = {"count": 0, "first": 0.0, "blocked_until": 0.0}

# An upgrade starts with the token in the old file and a fresh canonical one.
# Copy it once so the canonical file is self-sufficient; the flag stops a
# read-only Decky settings dir from retrying a failing write on every request.
_heal_lock = threading.Lock()
_heal_attempted: set[str] = set()


def is_console_path(route_path: str) -> bool:
    return route_path == "/v1" or route_path.startswith("/v1/")


# ---------------------------------------------------------------- token

def console_enabled(settings) -> bool:
    try:
        return bool(settings.get(ENABLED_SETTING, True))
    except Exception:  # noqa: BLE001 - a broken settings file must not open the API
        return True


def ensure_console_token(settings) -> str:
    """Return the console token, creating and persisting one on first use.

    Uran and Epsilon can each own a copy of the settings file during an
    upgrade, and ASSella may rotate the token in either one. The newest copy
    wins (the same rule the Hubcap key uses), so a rotation in ASSella takes
    effect without restarting the bridge.
    """
    try:
        token = str(settings.shared_secret(TOKEN_SETTING) or "").strip()
    except Exception:  # noqa: BLE001 - a broken settings file must not open the API
        token = ""
    if token:
        _adopt_into_canonical(settings, token)
        return token

    token = TOKEN_PREFIX + os.urandom(32).hex()
    try:
        settings.set(TOKEN_SETTING, token)
        logger.info("Generated a new AT0-M console token")
    except Exception as exc:  # noqa: BLE001
        # Still usable this session; ASSella just cannot show it until the
        # settings file is writable again.
        logger.error("Could not persist the AT0-M console token: %s", exc)
    return token


def _adopt_into_canonical(settings, token: str) -> None:
    """Copy a token found only in an older companion file into the canonical one."""
    canonical = str(getattr(settings, "path", ""))
    with _heal_lock:
        if canonical in _heal_attempted:
            return
        _heal_attempted.add(canonical)
    try:
        if str(settings.local_value(TOKEN_SETTING) or "").strip() == token:
            return
        settings.set(TOKEN_SETTING, token)
        logger.info("Adopted the existing AT0-M console token into %s", getattr(settings, "path", ""))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not adopt the console token: %s", exc)


def _presented_token(headers: dict) -> str:
    auth = str(headers.get("authorization", "") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return str(headers.get("x-at0m-token", "") or "").strip()


def _rate_limited() -> float:
    with _fail_lock:
        now = time.time()
        if _fail_state["blocked_until"] > now:
            return _fail_state["blocked_until"] - now
        return 0.0


def _note_failure() -> None:
    with _fail_lock:
        now = time.time()
        if now - _fail_state["first"] > _FAIL_WINDOW:
            _fail_state["first"] = now
            _fail_state["count"] = 0
        _fail_state["count"] += 1
        if _fail_state["count"] >= _FAIL_LIMIT:
            _fail_state["blocked_until"] = now + _LOCKOUT


def _note_success() -> None:
    with _fail_lock:
        _fail_state["count"] = 0
        _fail_state["first"] = 0.0


def authorize(settings, headers: dict) -> tuple[bool, int, str]:
    """Check the bearer token. Returns ``(ok, http_status, message)``."""
    wait = _rate_limited()
    if wait > 0:
        return False, 429, f"Too many failed attempts; retry in {int(wait) + 1}s."

    expected = ensure_console_token(settings)
    presented = _presented_token(headers)
    if presented and hmac.compare_digest(presented, expected):
        _note_success()
        return True, 200, ""

    _note_failure()
    return False, 401, "Console token missing or invalid. Pair the console again from ASSella."


# ---------------------------------------------------------------- sanitizers

def _clean_depot(item: Any) -> dict:
    item = item if isinstance(item, dict) else {}
    return {
        "id": str(item.get("id", "")),
        "name": str(item.get("name", "")),
        "in_config": bool(item.get("in_config")),
        "has_key": bool(item.get("has_key")),
        "is_dlc": bool(item.get("is_dlc")),
        "dlc_id": str(item.get("dlc_id", "")),
        "os": str(item.get("os", "")),
        "size_str": str(item.get("size_str", "")),
    }


def _clean_dlc(item: Any) -> dict:
    item = item if isinstance(item, dict) else {}
    out = {
        "id": str(item.get("id", "")),
        "name": str(item.get("name", "")),
        "in_config": bool(item.get("in_config")),
        "selected": bool(item.get("selected", item.get("in_config"))),
    }
    if item.get("depot_count") is not None:
        out["depot_count"] = item.get("depot_count")
    return out


def _clean_key(item: Any) -> dict:
    """A key entry without the key.

    ``inspect()`` hands the Decky frontend full keys so its key list can copy
    them; the console has no reason to see them, so only presence and a mask.
    """
    item = item if isinstance(item, dict) else {}
    return {
        "id": str(item.get("id", "")),
        "name": str(item.get("name", "")),
        "masked_key": str(item.get("masked_key", "")),
        "is_appkey": bool(item.get("is_appkey")),
        "in_config": bool(item.get("in_config")),
        "in_local": bool(item.get("in_local")),
    }


def _clean_game(item: Any) -> dict:
    item = item if isinstance(item, dict) else {}
    return {
        "app_id": str(item.get("app_id", "")),
        "name": str(item.get("name", "")),
        "state": str(item.get("state", "")),
        "installed": bool(item.get("installed")),
        "downloading": bool(item.get("downloading")),
        "buildid": str(item.get("buildid", "")),
        "size_on_disk": item.get("size_on_disk", 0),
        "depots": [str(d) for d in (item.get("depots") or [])],
        "key_count": item.get("key_count", 0),
        "dlc_only": bool(item.get("dlc_only")),
        "dlc_appids": [str(d) for d in (item.get("dlc_appids") or [])],
        # `source` is how the console tells an AT0-M registration from a Steam
        # licence; dropping it flattened every tile to the same state.
        "source": str(item.get("source", "")),
        "owned": bool(item.get("owned")),
        "updated_at": item.get("updated_at", 0),
        "issues": item.get("issues") or [],
    }


def _clean_detail(detail: dict) -> dict:
    return {
        "ok": bool(detail.get("ok")),
        "app_id": str(detail.get("app_id", "")),
        "name": str(detail.get("name", "")),
        "registered": bool(detail.get("registered")),
        "installed": bool(detail.get("installed")),
        "size_on_disk": detail.get("size_on_disk", 0),
        "buildid": str(detail.get("buildid", "")),
        "depots": [str(d) for d in (detail.get("depots") or [])],
        "key_count": detail.get("key_count", 0),
        "dlc_only": bool(detail.get("dlc_only")),
        "depots_detail": [_clean_depot(d) for d in (detail.get("depots_detail") or [])],
        "dlcs_detail": [_clean_dlc(d) for d in (detail.get("dlcs_detail") or [])],
        "dlcs_injected": bool(detail.get("dlcs_injected")),
        "keys_detail": [_clean_key(k) for k in (detail.get("keys_detail") or [])],
    }


def _clean_queue(items: Any) -> list[dict]:
    """Recent injections, without the depot-key maps the injector keeps."""
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        out.append({
            "app_id": str(item.get("app_id", "")),
            "name": str(item.get("name", "")),
            "done": bool(item.get("done")),
            "running": bool(item.get("running")),
            "registered": bool(item.get("registered")),
            "error": item.get("error") or "",
            "blocked": item.get("blocked") or "",
            "depots_resolved": [str(d) for d in (item.get("depots_resolved") or [])],
            "manifests": item.get("manifests"),
        })
    return out


def _clean_hubcap_status(status: dict) -> dict:
    """Key provenance without the key itself."""
    status = status if isinstance(status, dict) else {}
    return {
        "ok": bool(status.get("ok")),
        "source": str(status.get("source", "")),
        "masked": str(status.get("masked", "")),
        "is_override": bool(status.get("is_override")),
    }


# ---------------------------------------------------------------- payloads

def _json_body(body: bytes) -> tuple[dict | None, str]:
    if not body:
        return {}, ""
    if len(body) > MAX_BODY_BYTES:
        return None, "Request body too large."
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, f"Malformed JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "Expected a JSON object."
    return payload, ""


def _body_appid(payload: dict) -> str:
    raw = payload.get("appid", payload.get("app_id", ""))
    return sanitize_id(str(raw).strip())


def _first(query: dict, key: str, default: str = "") -> str:
    values = query.get(key) or []
    return str(values[0]).strip() if values else default


def _settings_payload(settings) -> dict:
    return {key: settings.get(key, None) for key in SETTINGS_SCHEMA}


# ---------------------------------------------------------------- router

def route(services, method: str, route_path: str, query: dict, body: bytes,
          headers: dict) -> tuple[int, dict, dict]:
    """Dispatch a ``/v1`` request. Host and Origin are checked by the caller."""
    settings = services.ctx.settings

    if not console_enabled(settings):
        return 403, {"ok": False, "error": "The AT0-M console API is disabled in Epsilon."}, {}

    ok, status, message = authorize(settings, headers)
    if not ok:
        extra = {"WWW-Authenticate": "Bearer"} if status == 401 else {"Retry-After": "60"}
        return status, {"ok": False, "error": message}, extra

    # Writes additionally require a custom header, which forces a CORS preflight
    # so a plain cross-site form POST can never reach them.
    if method == "POST" and not str(headers.get(CLIENT_HEADER, "")).strip():
        return 403, {"ok": False, "error": "Missing X-At0m-Client header."}, {}

    try:
        return _route_authorized(services, method, route_path, query, body)
    except Exception as exc:  # noqa: BLE001 - never leak a traceback to the page
        logger.error("Console API %s %s failed: %s", method, route_path, exc, exc_info=True)
        return 500, {"ok": False, "error": "Epsilon hit an unexpected error; see the service log."}, {}


def _route_authorized(services, method: str, route_path: str, query: dict,
                      body: bytes) -> tuple[int, dict, dict]:
    from .updates import epsilon_version

    ctx = services.ctx

    # --- session ---------------------------------------------------------
    if method == "GET" and route_path == "/v1/session":
        sls_active = False
        steam_running = False
        try:
            readiness = services.guards.check_system_readiness()
            sls_active = bool(readiness.get("sls_active") or readiness.get("ready"))
            steam_running = bool(readiness.get("steam_running", sls_active))
        except Exception:  # noqa: BLE001
            pass
        return 200, {
            "ok": True,
            "service": "epsilon",
            "version": epsilon_version(ctx),
            "console": True,
            "write_scope": True,
            "hubcap_key": bool(ctx.hubcap_key.current()),
            "library_count": len(services.guards.get_added_app_ids()),
            "sls_active": sls_active,
            "steam_running": steam_running,
        }, {}

    # --- library ---------------------------------------------------------
    if method == "GET" and route_path == "/v1/library":
        games = [_clean_game(g) for g in services.atom.list_games()]
        return 200, {"ok": True, "games": games}, {}

    # --- search ----------------------------------------------------------
    if method == "GET" and route_path == "/v1/search":
        term = _first(query, "q")
        if not term:
            return 400, {"ok": False, "error": "Missing 'q' query parameter."}, {}
        if len(term) > 120:
            return 400, {"ok": False, "error": "Search term too long."}, {}
        try:
            limit = max(1, min(int(_first(query, "limit", "20") or 20), 50))
        except ValueError:
            limit = 20
        results = services.steam.search(term, limit, appid=term.isdigit())
        rows = [r for r in (results.get("results") or []) if isinstance(r, dict)]

        # Label each result once from local state: the console shows installed
        # and already-registered titles differently, and it should not have to
        # ask again per tile.
        installed: set[str] = set()
        registered: set[str] = set()
        if rows:
            try:
                installed = services.steam.installed_ids()
            except Exception:  # noqa: BLE001 - labels are optional
                installed = set()
            try:
                registered = set(services.guards.get_added_app_ids())
            except Exception:  # noqa: BLE001
                registered = set()

        items = []
        for row in rows:
            aid = str(row.get("app_id", ""))
            entry = {"app_id": aid, "title": str(row.get("title", ""))}
            for extra in ("thumb", "developer", "year"):
                if row.get(extra):
                    entry[extra] = row[extra]
            entry["installed"] = aid in installed
            entry["registered"] = aid in registered
            items.append(entry)

        return 200, {"ok": True, "query": term, "results": items}, {}

    # --- one app ---------------------------------------------------------
    if method == "GET" and route_path.startswith("/v1/app/"):
        aid = sanitize_id(route_path[len("/v1/app/"):].split("/")[0])
        if not aid:
            return 400, {"ok": False, "error": "Invalid AppID."}, {}
        network = _first(query, "network", "0") in ("1", "true", "yes")
        detail = services.atom.detail(aid, allow_network=network)
        if not detail.get("ok"):
            return 404, {"ok": False, "error": detail.get("error", "Unknown AppID.")}, {}
        payload = _clean_detail(detail)
        payload["inject_status"] = services.injector.status(aid)
        payload["registered"] = bool(payload["registered"] or services.guards.is_app_added(aid))
        return 200, payload, {}

    # --- queue -----------------------------------------------------------
    if method == "GET" and route_path == "/v1/queue":
        return 200, {"ok": True, "items": _clean_queue(services.injector.recent())}, {}

    # --- updates ---------------------------------------------------------
    if method == "GET" and route_path == "/v1/updates":
        res = services.atom.check_all_updates(use_cache=True)
        return 200, {"ok": True, **(res if isinstance(res, dict) else {})}, {}

    if method == "POST" and route_path == "/v1/updates/check":
        payload, err = _json_body(body) if body else ({}, "")
        if err:
            return 400, {"ok": False, "error": err}, {}
        aid = _body_appid(payload) if payload.get("appid") or payload.get("app_id") else ""
        if aid:
            res = services.atom.check_updates(aid, use_cache=False)
            return 200, {"ok": True, "appid": aid, "update": res}, {}
        res = services.atom.check_all_updates(use_cache=False)
        return 200, {"ok": True, **(res if isinstance(res, dict) else {})}, {}

    # --- store patch -----------------------------------------------------
    if method == "GET" and route_path == "/v1/store":
        try:
            cef = services.store_debugger.status()
        except Exception:  # noqa: BLE001 - a probe failure is a state, not an error
            cef = {"available": False, "message": "CEF debugging could not be probed."}
        # The patch itself runs inside Uran's process, so its trace comes from
        # the shared file rather than this process's buffer.
        try:
            recent = services.store_debugger.recent_logs()
        except Exception:  # noqa: BLE001
            recent = []
        sentinel = False
        try:
            steam_path = getattr(services.ctx, "steam_path", None)
            if steam_path:
                from pathlib import Path
                sentinel = (Path(steam_path) / ".cef-enable-remote-debugging").exists()
        except Exception:  # noqa: BLE001
            sentinel = False
        return 200, {
            "ok": True,
            "enabled": bool(services.ctx.settings.get("steam_store_enabled", True)),
            "cef": {
                "available": bool(cef.get("available")),
                "port": cef.get("port"),
                "store_tab": bool(cef.get("store_tab")),
                "url": str(cef.get("url") or ""),
                "message": str(cef.get("message") or ""),
                "sentinel": sentinel,
            },
            "patched_by": "uran",
            "requires": ".cef-enable-remote-debugging",
            "recent": recent,
        }, {}

    if method == "POST" and route_path == "/v1/store/cef":
        payload, err = _json_body(body)
        if err:
            return 400, {"ok": False, "error": err}, {}
        enable = bool(payload.get("enabled", True))
        steam_path = getattr(services.ctx, "steam_path", None)
        if not steam_path:
            return 400, {"ok": False, "error": "Steam path not found."}, {}
        from pathlib import Path
        sentinel_path = Path(steam_path) / ".cef-enable-remote-debugging"
        try:
            if enable:
                sentinel_path.touch(exist_ok=True)
            elif sentinel_path.exists():
                sentinel_path.unlink()
            return 200, {
                "ok": True,
                "sentinel": sentinel_path.exists(),
                "message": (
                    "Created .cef-enable-remote-debugging — restart Steam if running."
                    if enable
                    else "Removed .cef-enable-remote-debugging — restart Steam to close port."
                ),
            }, {}
        except OSError as exc:
            return 500, {"ok": False, "error": f"Failed to update CEF sentinel: {exc}"}, {}

    # --- hubcap ----------------------------------------------------------
    if method == "GET" and route_path == "/v1/hubcap":
        payload = _clean_hubcap_status(services.keycare.key_status())
        payload["guide_url"] = guide_url(None if payload["ok"] else "401")
        return 200, payload, {}

    if method == "POST" and route_path == "/v1/hubcap":
        payload, err = _json_body(body)
        if err:
            return 400, {"ok": False, "error": err}, {}
        key = str(payload.get("key", "")).strip()
        if not key:
            return 400, {"ok": False, "error": "Missing 'key'."}, {}
        ok, message = services.keycare.save(key)
        return (200 if ok else 400), {"ok": ok, "message": message}, {}

    # --- register / unregister / refresh / refetch ------------------------
    if method == "POST" and route_path in (
        "/v1/register", "/v1/unregister", "/v1/refresh", "/v1/refetch"
    ):
        payload, err = _json_body(body)
        if err:
            return 400, {"ok": False, "error": err}, {}
        aid = _body_appid(payload)
        if not aid:
            return 400, {"ok": False, "error": "Invalid AppID."}, {}

        if route_path == "/v1/register":
            status, response = inject_response(services.injector.inject(aid))
            return status, response, {}

        if route_path == "/v1/unregister":
            removed = bool(services.library.unregister(aid))
            if removed:
                return 200, {"ok": True, "appid": aid, "removed": True}, {}
            return 404, {
                "ok": False,
                "appid": aid,
                "removed": False,
                "error": f"{aid} is not in the AT0-M library.",
            }, {}

        if route_path == "/v1/refresh":
            result = services.injector.refresh(aid)
            ok = bool(result.get("ok", True))
            return (200 if ok else 400), {"ok": ok, "result": result}, {}

        result = services.injector.refetch_game(aid)
        ok = bool(result.get("ok", False))
        return (200 if ok else 400), {"ok": ok, "result": result}, {}

    # --- uninstall & steam install ---------------------------------------
    if method == "POST" and route_path == "/v1/uninstall":
        payload, err = _json_body(body)
        if err:
            return 400, {"ok": False, "error": err}, {}
        aid = _body_appid(payload)
        if not aid:
            return 400, {"ok": False, "error": "Invalid AppID."}, {}
        result = services.uninstaller.uninstall(aid)
        ok = bool(result.get("ok", False))
        return (200 if ok else 400), {"ok": ok, **(result if isinstance(result, dict) else {})}, {}

    if method == "POST" and route_path == "/v1/steam/install":
        payload, err = _json_body(body)
        if err:
            return 400, {"ok": False, "error": err}, {}
        aid = _body_appid(payload)
        if not aid:
            return 400, {"ok": False, "error": "Invalid AppID."}, {}
        try:
            lib_idx = max(0, int(payload.get("library_index", 0) or 0))
        except (TypeError, ValueError):
            lib_idx = 0
        from .sls_config import signal_api
        sent = bool(signal_api(f"install|{aid}|{lib_idx}"))
        return (200 if sent else 503), {
            "ok": sent,
            "appid": aid,
            "library_index": lib_idx,
            "error": "" if sent else "SLSsteam API pipe unavailable — ensure Steam is running with SLSsteam.",
        }, {}

    # --- settings --------------------------------------------------------
    if method == "GET" and route_path == "/v1/settings":
        payload = _settings_payload(services.ctx.settings)
        lan_on = bool(services.ctx.settings.get("epsilon_console_lan", False))
        lan_ip = _detect_lan_ip()
        payload["epsilon_console_lan"] = lan_on
        payload["lan_ip"] = lan_ip
        payload["lan_url"] = f"http://{lan_ip}:1952/"
        return 200, {"ok": True, "settings": payload}, {}

    if method == "POST" and route_path == "/v1/settings":
        payload, err = _json_body(body)
        if err:
            return 400, {"ok": False, "error": err}, {}
        changes: dict[str, Any] = {}
        for key, value in payload.items():
            schema = SETTINGS_SCHEMA.get(str(key))
            if not schema:
                return 400, {
                    "ok": False,
                    "error": f"Setting '{key}' is not writable from the console.",
                }, {}
            kind, allowed = schema
            if kind == "bool" and not isinstance(value, bool):
                return 400, {"ok": False, "error": f"'{key}' must be true or false."}, {}
            if kind == "enum" and value not in allowed:
                return 400, {
                    "ok": False,
                    "error": f"'{key}' must be one of: {', '.join(allowed)}.",
                }, {}
            changes[str(key)] = value
        if not changes:
            return 400, {"ok": False, "error": "No settings supplied."}, {}
        for key, value in changes.items():
            services.ctx.write_setting(key, value)
        if "epsilon_console_lan" in changes:
            _apply_lan_socket(bool(changes["epsilon_console_lan"]))
        payload_out = _settings_payload(services.ctx.settings)
        lan_on = bool(services.ctx.settings.get("epsilon_console_lan", False))
        lan_ip = _detect_lan_ip()
        payload_out["epsilon_console_lan"] = lan_on
        payload_out["lan_ip"] = lan_ip
        payload_out["lan_url"] = f"http://{lan_ip}:1952/"
        return 200, {"ok": True, "settings": payload_out}, {}

    return 404, {
        "ok": False,
        "error": f"Unknown console route: {method} {route_path}",
    }, {}

