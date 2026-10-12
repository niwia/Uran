"""Hubcap manifest API client.

Speaks to the public Hubcap API (hubcapmanifest.com) that ASSella also uses.

Some ISPs block the API host. A Cloudflare Worker fronting the same API can be
reached instead. Which route is used is controlled by the `hubcap_gateway`
setting:

  auto     try direct first, fall back to the proxy only on a blocked route
  direct   direct only, never fall back (fails loudly if the route is blocked)
  proxy    proxy only (use when the direct route is known to be blocked)

The fallback is deliberately narrow: it fires only on transport-level failures
that genuinely indicate a blocked route (DNS failure, connection refused/reset,
TLS handshake failure). Rate limits, auth failures and every other HTTP-level
problem are returned to the caller untouched, because retrying those through a
second host would burn quota or mask a real error.
"""

import json
import logging
import threading
import time

from .http import ConnectionError_, Timeout, requests

logger = logging.getLogger("Uran")

HUBCAP_BASE_URL = "https://hubcapmanifest.com/api/v1"
WIRECUTTER_ENDPOINT = "https://rapid-thunder-fba1wirecutter.7ucking.workers.dev"

GATEWAY_MODES = ("auto", "direct", "proxy")
GATEWAY_DEFAULT = "auto"
GATEWAY_LABELS = {
    "auto": "Automatic — try direct, fall back to the edge proxy if blocked",
    "direct": "Direct only — never use the proxy",
    "proxy": "Edge proxy only",
}

# Minimum spacing between Hubcap requests, in seconds.
#
# /manifest/{id}/contents is free of generation quota, but it is still a public
# endpoint on someone else's machine, and a batch check over a large library
# would otherwise fire dozens of requests back to back. This is a *shared* gate
# rather than a per-thread sleep: the lock covers the wait, so N worker threads
# are still spaced by MIN_REQUEST_INTERVAL instead of all sleeping in parallel
# and then firing together.
MIN_REQUEST_INTERVAL = 0.25

_request_lock = threading.Lock()
_last_request_at = 0.0


def _throttle() -> None:
    """Block until MIN_REQUEST_INTERVAL has passed since the previous request."""
    global _last_request_at
    with _request_lock:
        wait = _last_request_at + MIN_REQUEST_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def is_blocked_transport_error(exc: BaseException) -> bool:
    """True only for failures that mean "this host is unreachable from here".

    Deliberately excludes HTTP status errors entirely: a 401/404/429 came back
    over a working connection, so the route is fine and retrying elsewhere is
    wrong.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return False

    # Timeouts and connection errors are the transport-layer signature of a
    # blocked or silently dropped route.
    if isinstance(exc, _blocked_exceptions()):
        return True

    text = str(exc).lower()
    blocked_markers = (
        "name or service not known",      # DNS NXDOMAIN
        "temporary failure in name resolution",
        "nodename nor servname",
        "getaddrinfo failed",
        "connection refused",
        "connection reset",
        "network is unreachable",
        "no route to host",
        "host is unreachable",
        "failed to establish a new connection",
        "ssl",                             # handshake / certificate interception
        "certificate verify failed",
    )
    return any(marker in text for marker in blocked_markers)


def _blocked_exceptions() -> tuple:
    """Transport exceptions, from both the real library and our own shim.

    `requests` may be present or replaced by the urllib shim at import time, and
    the shim defines its own classes, so both sets are collected here rather
    than assumed.
    """
    candidates = [ConnectionError_, Timeout]
    exceptions_ns = getattr(requests, "exceptions", None)
    for name in ("ConnectionError", "Timeout"):
        candidate = getattr(exceptions_ns, name, None)
        if isinstance(candidate, type) and issubclass(candidate, BaseException):
            candidates.append(candidate)
    return tuple(candidates)


def _proxy_url(url: str) -> str:
    return url.replace(HUBCAP_BASE_URL, WIRECUTTER_ENDPOINT)


# ---------------------------------------------------------------------------
# Route health
#
# The Settings panel reports whether the direct route works and whether the
# proxy fallback rescued it, so a user on a blocked ISP can see why requests
# are slow instead of guessing.
# ---------------------------------------------------------------------------
_route_health = {
    "direct": "unknown",   # unknown | ok | blocked
    "proxy": "unknown",    # unknown | ok | failed
    "fallback_used": False,
    "last_error": "",
    "last_checked": 0,
}


def route_health() -> dict:
    """Current view of both routes, for the Settings panel."""
    return {
        "mode": GATEWAY_DEFAULT,
        "direct": _route_health["direct"],
        "proxy": _route_health["proxy"],
        "fallback_used": _route_health["fallback_used"],
        "last_error": _route_health["last_error"],
        "last_checked": _route_health["last_checked"],
        "labels": GATEWAY_LABELS,
    }


def _mark(route: str, state: str, error: str = "") -> None:
    _route_health[route] = state
    _route_health["last_error"] = error[:300]
    _route_health["last_checked"] = int(time.time())


def _get(url: str, headers: dict | None, timeout: int, stream: bool):
    _throttle()
    try:
        response = requests.get(url, headers=headers, timeout=timeout, stream=stream)
    except Exception as exc:  # noqa: BLE001 - classified by the caller
        if is_blocked_transport_error(exc):
            _mark("direct", "blocked", str(exc))
        else:
            # A working connection that returned an error status: the route is
            # reachable, which is all this state tracks.
            _mark("direct", "ok")
        raise
    _mark("direct", "ok")
    return response


def request(
    url: str,
    headers: dict | None = None,
    timeout: int = 20,
    stream: bool = False,
    mode: str | None = None,
):
    """GET a Hubcap URL, honouring the configured gateway mode."""
    mode = mode if mode in GATEWAY_MODES else GATEWAY_DEFAULT

    if mode == "direct":
        return _get(url, headers, timeout, stream)

    if mode == "proxy":
        return _proxy_get(url, headers, timeout, stream, reason="proxy-only mode")

    # auto
    try:
        return _get(url, headers, timeout, stream)
    except Exception as exc:  # noqa: BLE001
        if not is_blocked_transport_error(exc):
            # Quota, auth, TLS-config or programming errors: surface them as-is
            # so the caller reports the real reason instead of "network error".
            raise
        logger.warning(
            "Direct request to Hubcap failed (%s); retrying once via the proxy endpoint",
            exc,
        )
        return _proxy_get(url, headers, timeout, stream, reason=str(exc))


def _proxy_get(url: str, headers: dict | None, timeout: int, stream: bool, reason: str):
    _throttle()
    try:
        response = requests.get(
            _proxy_url(url), headers=headers, timeout=timeout, stream=stream
        )
    except Exception as exc:  # noqa: BLE001
        _mark("proxy", "failed", f"{reason} / proxy: {exc}")
        _route_health["fallback_used"] = False
        raise
    _mark("proxy", "ok", f"fallback after: {reason}")
    _route_health["fallback_used"] = True
    return response


def probe_routes(api_key: str = "") -> dict:
    """Actively test both routes so the Settings panel can show real feedback.

    Uses /user/stats: authenticated, zero quota, and it distinguishes a working
    route from a blocked one. /health is unusable for this because it is
    unauthenticated and answers 200 for any input.
    """
    headers = auth_headers(api_key) if api_key else None
    results = {}

    for name, url in (("direct", HUBCAP_BASE_URL), ("proxy", WIRECUTTER_ENDPOINT)):
        target = f"{url}/user/stats"
        entry = {"ok": False, "detail": "", "ms": 0}
        start = time.monotonic()
        _throttle()
        try:
            response = requests.get(target, headers=headers, timeout=12)
            entry["ms"] = int((time.monotonic() - start) * 1000)
            if response.status_code == 200:
                entry["ok"] = True
                entry["detail"] = "reachable"
            elif response.status_code in (401, 403):
                # Reached the server; the key is simply not accepted.
                entry["ok"] = True
                entry["detail"] = "reachable (invalid key)"
            else:
                entry["detail"] = f"HTTP {response.status_code}"
        except Exception as exc:  # noqa: BLE001
            entry["ms"] = int((time.monotonic() - start) * 1000)
            entry["detail"] = _short_error(exc)
        results[name] = entry

    _mark(
        "direct",
        "ok" if results["direct"]["ok"] else "blocked",
        results["direct"]["detail"],
    )
    _mark(
        "proxy",
        "ok" if results["proxy"]["ok"] else "failed",
        results["proxy"]["detail"],
    )

    return {
        "ok": True,
        "routes": results,
        "mode": _route_health.get("mode", GATEWAY_DEFAULT),
        "checked_at": int(time.time()),
    }


def _short_error(exc: BaseException) -> str:
    """One short line describing a transport failure."""
    text = str(exc).strip() or type(exc).__name__
    return text[:120]


def auth_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def manifest_contents(app_id: str, api_key: str, mode: str | None = None) -> dict:
    """GET /manifest/{app_id}/contents — free (zero quota) bundle preflight.

    Lets us tell "Hubcap has no bundle for this app" apart from "your key is
    wrong" before spending a bundle download.
    """
    app_id = str(app_id).strip()
    try:
        resp = request(
            f"{HUBCAP_BASE_URL}/manifest/{app_id}/contents",
            headers=auth_headers(api_key),
            timeout=15,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Could not reach Hubcap: {exc}"}

    if resp.status_code == 401:
        return {"error": "Invalid Hubcap API key (HTTP 401)"}
    if resp.status_code == 404:
        return {"zip_exists": False, "manifest_count": 0, "manifests": []}
    if resp.status_code == 429:
        return {"error": "Hubcap rate limit reached (HTTP 429)"}
    if not resp.ok:
        return {"error": f"Hubcap API HTTP {resp.status_code}"}
    try:
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Malformed Hubcap response: {exc}"}

    manifests = data.get("manifests") or []
    data["manifests"] = manifests
    data["manifest_count"] = data.get("manifest_count", len(manifests))
    data["manifest_map"] = {
        str(m.get("depot_id")): str(m.get("manifest_id"))
        for m in manifests
        if isinstance(m, dict) and m.get("depot_id")
    }
    return data


def validate_key(api_key: str, http_request=request) -> tuple[bool, str, str]:
    """Validate a key via /user/stats (same endpoint ASSella uses).

    Returns (ok, message, detail_json). /user/stats is authenticated, consumes
    no generation quota, and reports the owning account so we can confirm the
    right key was pasted. (/health cannot be used: it is unauthenticated and
    answers 200 for any input.)
    """
    api_key = str(api_key or "").strip()
    if not api_key:
        return False, "No key supplied.", ""
    try:
        resp = http_request(
            f"{HUBCAP_BASE_URL}/user/stats",
            headers=auth_headers(api_key),
            timeout=20,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"Could not reach Hubcap: {exc}", ""

    if resp.status_code == 200:
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            return True, "Key is valid.", ""
        user = data.get("username") or data.get("user_id") or "unknown"
        used = data.get("daily_usage")
        limit = data.get("daily_limit")
        can = data.get("can_make_requests", True)
        parts = [f"Key is valid — {user}"]
        if used is not None and limit:
            parts.append(f"{used}/{limit} requests today")
        if not can:
            return False, f"Key belongs to {user} but is not allowed to make requests.", ""
        return True, " · ".join(parts) + ".", json.dumps(data)
    if resp.status_code in (401, 403):
        detail = ""
        try:
            detail = (resp.json() or {}).get("detail") or ""
        except Exception:  # noqa: BLE001
            pass
        return False, detail or "Hubcap rejected this key (401).", str(resp.status_code)
    if resp.status_code == 429:
        return False, "Hubcap rate limit reached. Try again later.", str(resp.status_code)
    return False, f"Unexpected Hubcap response (HTTP {resp.status_code}).", str(resp.status_code)


def user_stats(api_key: str) -> dict:
    """Account stats for the given key (via /user/stats)."""
    ok, message, detail = validate_key(api_key)
    if not ok:
        return {"ok": False, "error": message}
    try:
        data = json.loads(detail) if detail else {}
    except Exception:  # noqa: BLE001
        data = {}
    daily = data.get("daily_usage")
    limit = data.get("daily_limit")
    remaining = None
    if isinstance(daily, int) and isinstance(limit, int):
        remaining = max(0, limit - daily)
    expires = data.get("api_key_expires_at") or ""
    if expires:
        # Trim the ISO timestamp to something readable.
        try:
            expires = expires.split(".")[0].replace("T", " ").strip()
        except Exception:  # noqa: BLE001
            pass
    return {
        "ok": True,
        "username": data.get("username") or "",
        "daily_usage": daily,
        "daily_limit": limit,
        "requests_remaining": remaining,
        "expires_at": expires,
        "can_make_requests": bool(data.get("can_make_requests", True)),
    }