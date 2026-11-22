"""Shared HTTP response shapes for the Epsilon bridge.

The Photar routes and the AT0-M console routes both drive ``Injector.inject()``,
so the mapping from its result dict to an HTTP response lives here once. Photar
clients parse these fields (``error_code``, ``blocked``, ``already_added``,
``guide_url``), so this module is a contract: change it only with the userscript
and the console in the same release.
"""

from __future__ import annotations

GUIDE_BASE = "https://assella.niwia.top/epsilon"

# Why: `blocked` comes from the preflight guards and is the authoritative
# reason; the free-text error is only a fallback for worker-thread failures.
_BLOCKED_CODES = {
    "no_api_key": "401",
    "no_sls_config": "504",
    "sls_not_installed": "501",
    "sls_inactive": "501",
    "plugins_disabled": "503",
    "no_lua_plugins": "502",
}


def guide_url(error_code: str | None) -> str:
    """Deep link into the docs troubleshooting entry for a 3-digit code."""
    return f"{GUIDE_BASE}#err-{error_code}" if error_code else GUIDE_BASE


def inject_error_code(result: dict) -> str:
    """Pick the troubleshooting code for a failed injection."""
    error_text = str(result.get("error", ""))
    blocked = result.get("blocked")

    if blocked in _BLOCKED_CODES:
        return _BLOCKED_CODES[blocked]
    if "401" in error_text or "Invalid Hubcap API key" in error_text:
        return "401"
    if "404" in error_text or "No Hubcap bundle" in error_text:
        return "404"
    if "429" in error_text or "rate limit" in error_text.lower():
        return "429"
    if "no keys" in error_text.lower():
        return "701"
    return "707"


def inject_response(result: dict) -> tuple[int, dict]:
    """Map an ``Injector.inject()`` result to ``(status, body)``.

    "Already registered" is not an error for the browser: it is a 200 that the
    userscript turns into the "In Library" state, so it carries no error code.
    """
    if not result.get("error"):
        return 200, {
            "ok": True,
            "name": result.get("name"),
            "depots": result.get("depots", []),
            "fetching": result.get("fetching", True),
        }

    already_added = bool(result.get("already_added"))
    code = inject_error_code(result)
    return (
        200 if already_added else 400,
        {
            "ok": False,
            "error": result["error"],
            "error_code": None if already_added else code,
            "already_added": already_added,
            "blocked": result.get("blocked"),
            # Nothing is wrong when the app is already there, so do not deep
            # link a troubleshooting entry for it.
            "guide_url": guide_url(None if already_added else code),
        },
    )
