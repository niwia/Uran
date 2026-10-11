"""Guard services and environment verification for SLSsteam and Uran operations."""

import logging
import os
import re
import sys
import time
from pathlib import Path

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
    if os.path.exists("/tmp/SLSsteam.API"):
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
    """Resolve potential SLS plugins directories for Native and Flatpak Steam."""
    candidates = [
        home / ".config" / "SLSsteam" / "plugins",
        home / ".var" / "app" / "com.valvesoftware.Steam" / ".config" / "SLSsteam" / "plugins",
        Path.home() / ".config" / "SLSsteam" / "plugins",
        Path("/home/deck/.config/SLSsteam/plugins"),
    ]
    seen, out = set(), []
    for d in candidates:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


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
            raw = match.group(2).strip().lower()
            return raw in ("yes", "true", "1", "on")
    except Exception as e:
        logger.debug("Failed reading Plugins toggle from %s: %s", config_path, e)
    return False


class GuardService:
    """Provides validation guards for all add/uninstall operations."""

    def __init__(self, core):
        self.core = core

    def check_sls_environment(self) -> dict:
        """Verify that SLSsteam is installed, configured, and ready for operations."""
        core = self.core
        home = core._user_home()
        cfg = core._find_sls_config()

        if not cfg or not cfg.exists():
            return {
                "ok": False,
                "reason": "no_sls_config",
                "error": "SLSsteam config.yaml not found. Please ensure SLSsteam is installed.",
            }

        # Check SLS binary or active process
        sls_active = is_sls_active()
        binary_found = False
        for b_cand in [
            home / ".local" / "share" / "SLSsteam" / "SLSsteam.so",
            home / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "SLSsteam" / "SLSsteam.so",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "SLSsteam" / "SLSsteam.so",
            Path.home() / ".local" / "share" / "SLSsteam" / "SLSsteam.so",
            Path("/home/deck/.local/share/SLSsteam/SLSsteam.so"),
        ]:
            if b_cand.is_file():
                binary_found = True
                break

        if not sls_active and not binary_found:
            return {
                "ok": False,
                "reason": "sls_not_installed",
                "error": "SLSsteam.so was not found on your system. Please install SLSsteam.",
            }

        # Check Plugins: yes toggle
        plugins_on = is_plugins_toggle_enabled(cfg)
        if not plugins_on:
            # Attempt to auto-enable it silently
            try:
                core._ensure_plugins_enabled(cfg)
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

        # Check Hubcap key
        hubcap_key = core._detect_assella_canary_hubcap_key()

        return {
            "ok": True,
            "sls_active": sls_active,
            "config_path": str(cfg),
            "plugins_enabled": True,
            "plugin_dir": str(plugin_dir) if plugin_dir else "",
            "lua_plugins": lua_files,
            "has_hubcap_key": bool(hubcap_key),
        }

    def is_app_added(self, app_id: str) -> bool:
        """Check if an AppID is already added to SLS / AT0M library."""
        core = self.core
        aid = core._sanitize_id(str(app_id))
        if not aid:
            return False

        # 1. Check ACCELA plugin_library.json
        lib = core.load_plugin_library()
        if aid in lib:
            return True

        # 2. Check FakeAppIds
        fakes = core.get_fake_app_ids().get("ids", [])
        if aid in fakes:
            return True

        # 3. Check SLS config.yaml sections directly
        cfg = core._find_sls_config()
        if cfg and cfg.exists():
            try:
                content = cfg.read_text(encoding="utf-8", errors="replace")
                for sec in ("FakeAppIds", "AppId"):
                    bounds = core._get_section_bounds(content, sec)
                    if bounds:
                        sub = content[bounds[0]:bounds[1]]
                        if sec == "FakeAppIds":
                            if aid in core._parse_key_section(sub):
                                return True
                        else:
                            if aid in core._parse_list_section(sub):
                                return True
            except Exception:
                pass

        return False

    def get_added_app_ids(self) -> list[str]:
        """Return a list of all registered AppIDs."""
        core = self.core
        added = set()

        # 1. From plugin library
        lib = core.load_plugin_library()
        for k in lib.keys():
            aid = core._sanitize_id(str(k))
            if aid:
                added.add(aid)

        # 2. From FakeAppIds
        for fid in core.get_fake_app_ids().get("ids", []):
            aid = core._sanitize_id(str(fid))
            if aid:
                added.add(aid)

        # 3. From config.yaml AppId list
        cfg = core._find_sls_config()
        if cfg and cfg.exists():
            try:
                content = cfg.read_text(encoding="utf-8", errors="replace")
                for sec in ("FakeAppIds", "AppId"):
                    bounds = core._get_section_bounds(content, sec)
                    if bounds:
                        sub = content[bounds[0]:bounds[1]]
                        items = core._parse_key_section(sub) if sec == "FakeAppIds" else core._parse_list_section(sub)
                        for item in items:
                            aid = core._sanitize_id(str(item))
                            if aid:
                                added.add(aid)
            except Exception:
                pass

        return sorted(list(added))
