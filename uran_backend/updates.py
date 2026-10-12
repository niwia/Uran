"""Release update check.

Uran does not install updates itself. Decky Loader already tracks a plugin's
GitHub releases and updates it from the plugin browser or the Decky menu, so
Uran only surfaces "a newer release exists" and links out to it. One less
code path that writes to its own install directory.
"""

import json
import logging
import re

from .context import Context
from .http import requests

logger = logging.getLogger("Uran")

GITHUB_REPO = "niwia/Uran"


def plugin_version(ctx: Context) -> str:
    """Current version, read from plugin.json — the single source of truth."""
    path = ctx.plugin_dir / "plugin.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("version") or "0.0.0")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not read version from plugin.json: %s", exc)
        return "0.0.0"


def plugin_info(ctx: Context) -> dict:
    """Name and version for the settings panel."""
    path = ctx.plugin_dir / "plugin.json"
    name = "Uran"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        name = str(data.get("name") or name)
    except Exception:  # noqa: BLE001
        pass
    return {"name": name, "version": plugin_version(ctx)}


def _parse_version(value: str) -> tuple:
    parts = re.findall(r"\d+", str(value or ""))
    return tuple(int(p) for p in parts[:4]) or (0,)


def check_for_updates(ctx: Context) -> dict:
    """Report whether a newer release exists. Never installs anything."""
    current = plugin_version(ctx)
    base = {"ok": True, "current_version": current, "latest_version": current,
            "has_update": False, "notes": "", "release_url": "",
            "published_at": ""}

    try:
        resp = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers={"User-Agent": "Uran-Decky-Plugin"},
            timeout=8,
        )
    except Exception as exc:  # noqa: BLE001
        return {**base, "ok": False, "error": str(exc)}

    if resp.status_code == 404:
        return {**base, "notes": "No published releases found yet."}
    if resp.status_code != 200:
        return {**base, "ok": False, "error": f"GitHub API HTTP {resp.status_code}"}

    try:
        release = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {**base, "ok": False, "error": f"Malformed GitHub response: {exc}"}

    latest = str(release.get("tag_name", "")).lstrip("v")
    has_update = bool(latest) and _parse_version(latest) > _parse_version(current)
    return {
        **base,
        "latest_version": latest or current,
        "has_update": has_update,
        "notes": release.get("body", ""),
        "release_url": release.get("html_url", ""),
        "published_at": release.get("published_at", ""),
    }