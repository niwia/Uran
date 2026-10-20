"""Guard services and environment verification for SLSsteam and Uran operations."""

import logging
import os
import re
import sys
import time
from pathlib import Path

from . import paths

logger = logging.getLogger(__name__)

_proc_cache = {
    "last_check": 0.0,
    "steam_running": False,
    "sls_active": False,
}
_PROC_CACHE_TTL = 2.0


def _update_proc_cache_if_needed():
    """Scan /proc for Steam and SLSsteam.so at most once every TTL seconds."""
    now = time.time()
    if now - _proc_cache["last_check"] < _PROC_CACHE_TTL:
        return

    _proc_cache["last_check"] = now
    _proc_cache["steam_running"] = False
    _proc_cache["sls_active"] = False

    if sys.platform != "linux":
        return

    # 1. Quick check: /tmp/SLSsteam.API pipe
    if Path(paths.SLSSTEAM_API_PIPE).exists():
        _proc_cache["sls_active"] = True

    try:
        steam_pids = []
        for pid_dir in os.listdir("/proc"):
            if not pid_dir.isdigit():
                continue
            try:
                comm_path = os.path.join("/proc", pid_dir, "comm")
                with open(comm_path, "r", encoding="utf-8", errors="ignore") as f:
                    if f.read().strip() == "steam":
                        steam_pids.append(pid_dir)
            except OSError:
                continue

        if steam_pids:
            _proc_cache["steam_running"] = True
            if not _proc_cache["sls_active"]:
                for pid in steam_pids:
                    maps_path = os.path.join("/proc", pid, "maps")
                    try:
                        if os.path.exists(maps_path):
                            with open(maps_path, "r", encoding="utf-8", errors="ignore") as f:
                                for line in f:
                                    if "SLSsteam.so" in line:
                                        _proc_cache["sls_active"] = True
                                        return
                    except OSError:
                        continue
    except OSError:
        pass


def is_sls_active() -> bool:
    """Return True if SLSsteam.so is loaded into Steam or the API pipe exists."""
    _update_proc_cache_if_needed()
    return _proc_cache["sls_active"]


def is_steam_running() -> bool:
    """Return True if the steam process is currently running."""
    _update_proc_cache_if_needed()
    return _proc_cache["steam_running"]


def get_sls_plugins_dirs(home: Path) -> list[Path]:
    """Resolve the plugin directory for this user's selected Steam install."""
    return paths.sls_plugins_dirs(home)


def find_lua_plugins(home: Path) -> tuple[Path | None, list[str]]:
    """Find installed .lua plugins across candidate directories."""
    for p_dir in get_sls_plugins_dirs(home):
        if p_dir.is_dir():
            lua_files = [f.name for f in p_dir.glob("*.lua") if f.is_file()]
            if lua_files:
                return p_dir, sorted(lua_files)
    return None, []


def is_plugins_toggle_enabled(config_path: Path) -> bool:
    """Check if 'Plugins: yes' (or true/1) is active in config.yaml."""
    if not config_path or not config_path.exists():
        return False
    try:
        content = config_path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"^([ \t]*)Plugins[ \t]*:[ \t]*([^\r\n#]+)", content, re.MULTILINE | re.IGNORECASE)
        if match:
            return match.group(2).strip().lower() in ("yes", "true", "1", "on")
    except Exception as e:
        logger.debug("Failed reading Plugins toggle from %s: %s", config_path, e)
    return False


class GuardService:
    """Provides validation guards for all add/uninstall operations."""

    def __init__(self, core):
        self.core = core

    def check_sls_environment(self) -> dict:
        """Verify that SLSsteam is installed, configured, and ready for operations."""
        from .sls_config import ensure_plugins_enabled

        core = self.core
        ctx = core.ctx
        home = ctx.home
        cfg = ctx.sls_config()

        if not cfg or not cfg.exists():
            return {
                "ok": False,
                "reason": "no_sls_config",
                "error": "SLSsteam config.yaml not found. Please ensure SLSsteam is installed.",
            }

        # Check SLS binary or active process
        sls_active = is_sls_active()
        binary_found = False
        for b_cand in paths.sls_binary_candidates(home):
            if b_cand.is_file():
                binary_found = True
                break

        if not sls_active and not binary_found:
            return {
                "ok": False,
                "reason": "sls_not_installed",
                "error": "SLSsteam.so was not found on your system. Please install SLSsteam.",
            }

        # Check Plugins: yes toggle — attempt silent auto-enable
        plugins_on = is_plugins_toggle_enabled(cfg)
        if not plugins_on:
            try:
                content = cfg.read_text(encoding="utf-8", errors="replace")
                updated = ensure_plugins_enabled(content)
                if updated != content:
                    core.sls.write(updated)
                plugins_on = is_plugins_toggle_enabled(cfg)
            except Exception as e:
                logger.warning("Could not auto-enable Plugins toggle: %s", e)

        if not plugins_on:
            return {
                "ok": False,
                "reason": "plugins_disabled",
                "error": "SLSsteam 'Plugins: yes' toggle is disabled in config.yaml. Enable it to run operations.",
            }

        # Check presence of Lua plugin in plugins directory
        plugin_dir, lua_files = find_lua_plugins(home)
        if not lua_files:
            return {
                "ok": False,
                "reason": "no_lua_plugins",
                "error": "No Lua download plugin found in your SLSsteam plugins folder. Please add the required Lua plugin.",
            }

        return {
            "ok": True,
            "sls_active": sls_active,
            "config_path": str(cfg),
            "plugins_enabled": True,
            "plugin_dir": str(plugin_dir) if plugin_dir else "",
            "lua_plugins": lua_files,
            "has_hubcap_key": bool(ctx.hubcap_key.current()),
        }

    def is_app_added(self, app_id: str) -> bool:
        """Check if an AppID is already added to SLS / AT0M library."""
        from .sls_config import parse_key_section, parse_list_section, sanitize_id, section_bounds

        ctx = self.core.ctx
        aid = sanitize_id(str(app_id))
        if not aid:
            return False

        # 1. Check plugin_library.json
        if aid in self.core.library.load():
            return True

        # 2. Check FakeAppIds
        if aid in self.core.integrations.list_fake_app_ids().get("ids", []):
            return True

        # 3. Check config.yaml sections directly
        cfg = ctx.sls_config()
        if cfg and cfg.exists():
            try:
                content = cfg.read_text(encoding="utf-8", errors="replace")
                for sec in ("FakeAppIds", "AppId"):
                    bounds = section_bounds(content, sec)
                    if bounds:
                        sub = content[bounds[0]:bounds[1]]
                        if sec == "FakeAppIds":
                            if aid in parse_key_section(sub, "FakeAppIds")[0]:
                                return True
                        elif aid in parse_list_section(sub, "AppId"):
                            return True
            except Exception:
                pass

        return False

    def get_added_app_ids(self) -> list[str]:
        """Return a list of all registered AppIDs."""
        from .sls_config import parse_key_section, parse_list_section, sanitize_id, section_bounds

        ctx = self.core.ctx
        added = set()

        for key in self.core.library.load().keys():
            aid = sanitize_id(str(key))
            if aid:
                added.add(aid)

        for fid in self.core.integrations.list_fake_app_ids().get("ids", []):
            aid = sanitize_id(str(fid))
            if aid:
                added.add(aid)

        cfg = ctx.sls_config()
        if cfg and cfg.exists():
            try:
                content = cfg.read_text(encoding="utf-8", errors="replace")
                for sec in ("FakeAppIds", "AppId"):
                    bounds = section_bounds(content, sec)
                    if bounds:
                        sub = content[bounds[0]:bounds[1]]
                        items = parse_key_section(sub, "FakeAppIds")[0] if sec == "FakeAppIds" else parse_list_section(sub, "AppId")
                        for item in items:
                            aid = sanitize_id(str(item))
                            if aid:
                                added.add(aid)
            except Exception:
                pass

        return sorted(added)
