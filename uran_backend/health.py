"""Minimal system-health checks, ported from ASSella's Health tab.

Read-only by design: plugin presence, SLSsteam binary freshness and config
diagnostics. Nothing here writes to disk — the config check reports issues
only; repair lives in ASSella for now.
"""

import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .context import Context
from .http import requests
from . import paths

logger = logging.getLogger("Uran")

# Plugins ASSella treats as required (plugin_manager.FALLBACK_REQUIRED_PLUGINS).
# Uran only lists what is actually in the folder; see check_plugins.
SLS_PLUGIN_SUFFIX = ".lua"

SLS_RELEASES_URL = "https://api.github.com/repos/AceSLS/SLSsteam/releases/latest"
CONFIG_TEMPLATE_URL = "https://raw.githubusercontent.com/AceSLS/SLSsteam/main/res/config.yaml"

_VERSION_TOLERANCE_SEC = 120.0
_VERSION_CACHE_TTL = 120.0
_TEMPLATE_TIMEOUT = 15
_MAX_LINE_ISSUES = 10

_TOP_KEY_RE = re.compile(r"^['\"]?([A-Za-z0-9_]+)['\"]?(?=[ \t]*:)", re.MULTILINE)

# Keys that never appear in the upstream template but are legitimate: the
# plugin-added sections (mirrors ASSella's assfixer.KNOWN_PLUGIN_KEYS) and the
# IdleStatus sub-map. Without this exemption the checker flags every AT0-M
# setup, since AdditionalDepots/DecryptionKeys are how games get registered.
TEMPLATE_EXEMPT_KEYS = frozenset({"AdditionalDepots", "DecryptionKeys", "IdleStatus"})


def compare_sls_version(local_mtime: float | None, release_time: float) -> str:
    """Pure version-freshness decision: 'up_to_date' or 'outdated'."""
    if not local_mtime or not release_time:
        return "up_to_date" if local_mtime else "outdated"
    if release_time > 0 and local_mtime < (release_time - _VERSION_TOLERANCE_SEC):
        return "outdated"
    return "up_to_date"


def top_level_keys(text: str) -> set[str]:
    """Top-level YAML keys, without parsing (comments/order agnostic)."""
    return set(_TOP_KEY_RE.findall(text or ""))


def local_config_issues(text: str) -> list[str]:
    """Whitespace/structural issues detectable without the upstream template."""
    issues: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if line != line.rstrip():
            issues.append(f"Line {lineno}: trailing whitespace")
        elif "  #" in line:
            before, _, _ = line.partition("  #")
            if before.rstrip() != before:
                issues.append(f"Line {lineno}: extra spaces before inline comment")
        if len(issues) >= _MAX_LINE_ISSUES:
            break
    keys = _TOP_KEY_RE.findall(text)
    seen: set[str] = set()
    dupes: set[str] = set()
    for key in keys:
        if key in seen:
            dupes.add(key)
        seen.add(key)
    for key in sorted(dupes):
        issues.append(f"Duplicate top-level key: {key}")
    return issues


class Health:
    """Read-only health checks: plugins, SLS binary, config diagnostics."""

    def __init__(self, ctx: Context, sls):
        self.ctx = ctx
        self.sls = sls
        self._ver_cache: dict = {}
        self._ver_lock = threading.Lock()

    # -- plugins -----------------------------------------------------------
    def plugins_dirs(self) -> list[Path]:
        return paths.sls_plugins_dirs(self.ctx.home)

    def check_plugins(self) -> dict:
        """List the active SLSsteam Lua plugins found on disk.

        Informational only: returns the actual `.lua` file names present in
        the plugins dirs (e.g. versioned builds like
        `download-1.4.0-spacetest.lua`), not a hardcoded required set.
        """
        names: set[str] = set()
        searched: list[str] = []
        for directory in self.plugins_dirs():
            searched.append(str(directory))
            try:
                if not directory.is_dir():
                    continue
                for entry in directory.iterdir():
                    if entry.is_file() and entry.suffix.lower() == SLS_PLUGIN_SUFFIX:
                        names.add(entry.name)
            except OSError as exc:
                logger.debug("Plugin dir scan failed for %s: %s", directory, exc)
        return {
            "ok": True,
            "plugins_enabled": self._plugins_flag(),
            "plugins": sorted(names),
            "searched": searched,
        }

    def _plugins_flag(self) -> bool:
        try:
            content = self.sls.read()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not read config for Plugins flag: %s", exc)
            return False
        match = re.search(
            r"^[ \t]*['\"]?Plugins['\"]?[ \t]*:[ \t]*([^#\r\n]*)",
            content,
            re.MULTILINE | re.IGNORECASE,
        )
        if not match:
            return False
        return match.group(1).strip().lower() in ("yes", "true", "1", "on")

    # -- SLS version -------------------------------------------------------
    def sls_binary(self) -> Path | None:
        for candidate in paths.sls_binary_candidates(self.ctx.home):
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                continue
        return None

    def check_sls_version(self, force_refresh: bool = False) -> dict:
        now = time.time()
        if not force_refresh:
            with self._ver_lock:
                cached = self._ver_cache
                if cached and (now - cached.get("at", 0) < _VERSION_CACHE_TTL):
                    return dict(cached["data"])

        result: dict = {
            "status": "error",
            "release_tag": None,
            "error": None,
        }
        binary = self.sls_binary()
        if binary is None:
            result["status"] = "no_local"
            result["error"] = "SLSsteam.so not found"
            return result
        try:
            local_mtime = os.path.getmtime(binary)
        except OSError as exc:
            result["error"] = f"Could not inspect SLSsteam.so: {exc}"
            return result
        result["local_mtime"] = local_mtime

        try:
            resp = requests.get(
                SLS_RELEASES_URL,
                headers={"User-Agent": "Uran-Decky-Plugin"},
                timeout=10,
            )
            if resp.status_code != 200:
                raise ValueError(f"GitHub API HTTP {resp.status_code}")
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"GitHub API error: {exc}"
            return result

        release_tag = data.get("tag_name")
        result["release_tag"] = release_tag
        release_time = 0.0
        pub_str = data.get("published_at") or data.get("created_at")
        if pub_str:
            try:
                release_time = datetime.fromisoformat(
                    str(pub_str).replace("Z", "+00:00")
                ).timestamp()
            except ValueError:
                pass
        if not release_time and release_tag:
            try:
                release_time = datetime.strptime(
                    str(release_tag)[:14], "%Y%m%d%H%M%S"
                ).replace(tzinfo=timezone.utc).timestamp()
            except ValueError:
                pass

        # Exact-match shortcut via the version tracker ASSella maintains.
        version_file = binary.parent / "version"
        try:
            if version_file.is_file() and release_tag:
                local_ver = version_file.read_text(encoding="utf-8").strip()
                if local_ver and local_ver == release_tag:
                    result["status"] = "up_to_date"
                    with self._ver_lock:
                        self._ver_cache = {"at": time.time(), "data": dict(result)}
                    return result
        except OSError as exc:
            logger.debug("Could not read SLS version file: %s", exc)

        result["status"] = compare_sls_version(local_mtime, release_time)
        with self._ver_lock:
            self._ver_cache = {"at": time.time(), "data": dict(result)}
        return result

    # -- config check (read-only) ------------------------------------------
    def check_config(self, online: bool = True) -> dict:
        cfg = self.sls.config_path
        if cfg is None or not cfg.exists():
            return {
                "ok": False,
                "needs_attention": False,
                "summary": "SLSsteam config.yaml not found",
                "details": [f"Config not found (looked for {cfg})" if cfg else "No SLSsteam config location detected"],
            }
        try:
            text = cfg.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {
                "ok": False,
                "needs_attention": True,
                "summary": f"Could not read config: {exc}",
                "details": [str(exc)],
            }

        details = local_config_issues(text)
        template_note = ""
        if online:
            try:
                resp = requests.get(
                    CONFIG_TEMPLATE_URL,
                    headers={"User-Agent": "Uran-Decky-Plugin"},
                    timeout=_TEMPLATE_TIMEOUT,
                )
                if resp.status_code == 200 and resp.text.strip():
                    template_keys = top_level_keys(resp.text)
                    local_keys = top_level_keys(text)
                    missing = sorted(template_keys - local_keys)
                    unknown = sorted(
                        (local_keys - template_keys) - TEMPLATE_EXEMPT_KEYS
                    )
                    if missing:
                        details.append(
                            f"Missing {len(missing)} upstream setting(s): {', '.join(missing)}"
                        )
                    for key in unknown:
                        details.append(
                            f"Key '{key}' not in upstream template (may have been removed)"
                        )
                else:
                    template_note = f"Upstream template HTTP {resp.status_code}; local checks only."
            except Exception as exc:  # noqa: BLE001
                template_note = f"Upstream template unreachable ({exc}); local checks only."
                logger.debug("Config template fetch failed: %s", exc)

        if template_note:
            details.append(template_note)
        if details:
            return {
                "ok": True,
                "needs_attention": True,
                "summary": f"{len(details)} issue(s) found in config.yaml",
                "details": details,
            }
        return {
            "ok": True,
            "needs_attention": False,
            "summary": "Config looks healthy.",
            "details": [],
        }

    # -- combined ----------------------------------------------------------
    def status(self) -> dict:
        plugins = self.check_plugins()
        try:
            sls = self.check_sls_version()
        except Exception as exc:  # noqa: BLE001
            sls = {"status": "error", "release_tag": None, "error": str(exc)}
        return {"ok": True, "plugins": plugins, "sls": sls}
