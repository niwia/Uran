"""sls_lua_config.py
=================
Utilities to inspect, generate, and synchronize Lua configuration files for
SLSsteam plugins:
  - spacebunny.conf.lua: SpaceBunny interceptor and Hubcap auto-fetch settings

Acts as the shared bridge between Uran (Decky), ASSella (desktop), and SLSsteam.
"""

import logging
import os
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("Uran")

DEFAULT_SPACEBUNNY_CONFIG: dict[str, Any] = {
    "standalone": False,
    "hubcap": {
        "enabled": True,
        "base_url": "https://hubcapmanifest.com/api/v1",
        "api_key": "",
        "api_key_timestamp": 0,
        "timeout_sec": 5,
        "write_config": True,
        "notify": True,
        "preflight": "contents",
        "depot_index": False,
        "write_depot_comments": False,
    },
}


def _parse_bool(val_str: str) -> bool | None:
    s = val_str.strip().lower()
    if s.startswith("true") or s == "1" or s == "yes":
        return True
    if s.startswith("false") or s == "0" or s == "no":
        return False
    return None


def escape_lua_string(val: str) -> str:
    """Escape special characters for Lua double-quoted string literals."""
    if not isinstance(val, str):
        val = str(val)
    return (
        val.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        .replace("\0", "\\0")
    )


def _unescape_lua_string(s: str) -> str:
    """Unescape special characters from a Lua string literal."""
    def _repl(match):
        ch = match.group(1)
        if ch in ('"', "'", "\\"):
            return ch
        if ch == "n":
            return "\n"
        if ch == "r":
            return "\r"
        if ch == "t":
            return "\t"
        if ch == "0":
            return "\0"
        return ch

    return re.sub(r'\\(.)', _repl, s)


def _parse_string(val_str: str) -> str | None:
    m = re.search(r'"((?:\\.|[^"\\])*)"|\'((?:\\.|[^\'\\])*)\'', val_str)
    if m:
        raw = m.group(1) if m.group(1) is not None else m.group(2)
        return _unescape_lua_string(raw)
    return None


def _parse_int(val_str: str) -> int | None:
    m = re.search(r'(\d+)', val_str)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Timestamp & Key Validation (matching ASSella standard)
# ---------------------------------------------------------------------------

def generate_hubcap_timestamp() -> int:
    """Generate timestamp in the format minute-hour-day-year (e.g. 4518242026)."""
    now = time.localtime()
    # mm (0-59), hh (0-23), dd (1-31), yyyy (4-digit)
    return int(f"{now.tm_min:02d}{now.tm_hour:02d}{now.tm_mday:02d}{now.tm_year:04d}")


def _timestamp_to_sort_key(ts: int) -> int:
    """Convert timestamp to a chronologically sortable integer YYYYMMDDHHMM or epoch."""
    if ts <= 0:
        return 0
    s = str(ts).strip()
    if len(s) == 10 and any(s.endswith(str(y)) for y in range(2020, 2040)):
        try:
            minute = int(s[0:2])
            hour = int(s[2:4])
            day = int(s[4:6])
            year = int(s[6:10])
            return (year * 100000000) + (day * 1000000) + (hour * 10000) + minute
        except ValueError:
            pass
    elif len(s) == 14:  # Legacy YYYYMMDDHHMMSS format support
        try:
            return int(s[:12])
        except ValueError:
            pass
    return ts


def is_valid_hubcap_key(key: str) -> bool:
    """Basic validation guard for Hubcap API key. Must be alphanumeric/hyphens/underscores, >= 8 chars."""
    if not key or not isinstance(key, str):
        return False
    k = key.strip()
    if len(k) < 8 or any(c.isspace() for c in k):
        return False
    return bool(re.match(r'^[a-zA-Z0-9_\-]+$', k))


# ---------------------------------------------------------------------------
# SpaceBunny Configuration Reader & Writer
# ---------------------------------------------------------------------------

def read_spacebunny_conf(conf_path: Path | None) -> dict[str, Any]:
    """Read spacebunny.conf.lua, returning dict containing standalone and hubcap sub-dict."""
    res: dict[str, Any] = {
        "standalone": False,
        "hubcap": dict(DEFAULT_SPACEBUNNY_CONFIG["hubcap"]),
    }
    if conf_path is None or not conf_path.is_file():
        return res

    try:
        content = conf_path.read_text(encoding="utf-8", errors="ignore")

        # Outer standalone
        m_st = re.search(r'\bstandalone\s*=\s*([^,\n\r]+)', content)
        if m_st:
            b = _parse_bool(m_st.group(1))
            if b is not None:
                res["standalone"] = b

        # Extract hubcap table block
        m_hub = re.search(r'\bhubcap\s*=\s*\{([^}]+)\}', content, re.DOTALL)
        if m_hub:
            hub_content = m_hub.group(1)
            h = res["hubcap"]

            m = re.search(r'\benabled\s*=\s*([^,\n\r]+)', hub_content)
            if m:
                b = _parse_bool(m.group(1))
                if b is not None:
                    h["enabled"] = b

            m = re.search(r'\bapi_key\s*=\s*([^,\n\r]+)', hub_content)
            if m:
                s = _parse_string(m.group(1))
                if s is not None:
                    h["api_key"] = s

            m = re.search(r'\bapi_key_timestamp\s*=\s*([^,\n\r]+)', hub_content)
            if m:
                ts = _parse_int(m.group(1))
                if ts is not None:
                    h["api_key_timestamp"] = ts

            m = re.search(r'\bbase_url\s*=\s*([^,\n\r]+)', hub_content)
            if m:
                s = _parse_string(m.group(1))
                if s is not None:
                    h["base_url"] = s

            for key in ("write_config", "notify", "depot_index", "write_depot_comments"):
                m = re.search(rf'\b{key}\s*=\s*([^,\n\r]+)', hub_content)
                if m:
                    b = _parse_bool(m.group(1))
                    if b is not None:
                        h[key] = b

            m = re.search(r'\btimeout_sec\s*=\s*([^,\n\r]+)', hub_content)
            if m:
                num = _parse_int(m.group(1))
                if num is not None:
                    h["timeout_sec"] = num

            m = re.search(r'\bpreflight\s*=\s*([^,\n\r]+)', hub_content)
            if m:
                s = _parse_string(m.group(1))
                if s is not None:
                    h["preflight"] = s
    except Exception as exc:
        logger.error("Failed to read %s: %s", conf_path, exc)

    return res


def write_spacebunny_conf(cfg: dict[str, Any], conf_path: Path | None) -> bool:
    """Write spacebunny.conf.lua atomically, setting 0o600 permissions."""
    if conf_path is None:
        return False
    try:
        conf_path.parent.mkdir(parents=True, exist_ok=True)
        standalone = "true" if cfg.get("standalone", False) else "false"
        hub = cfg.get("hubcap", {})

        h_enabled = "true" if hub.get("enabled", True) else "false"
        h_api_key = str(hub.get("api_key", "")).strip()
        h_ts = int(hub.get("api_key_timestamp", 0) or 0)
        h_base_url = str(hub.get("base_url", "https://hubcapmanifest.com/api/v1")).strip()
        h_timeout = int(hub.get("timeout_sec", 5) or 5)
        h_write_config = "true" if hub.get("write_config", True) else "false"
        h_notify = "true" if hub.get("notify", True) else "false"
        h_preflight = str(hub.get("preflight", "contents")).strip()
        h_depot_index = "true" if hub.get("depot_index", False) else "false"
        h_comments = "true" if hub.get("write_depot_comments", False) else "false"

        lua_code = (
            "-- spacebunny.conf.lua\n"
            "-- Configuration for spacebunny.lua and hubcap.lua (Hubcap key resolver)\n"
            "return {\n"
            f"    standalone = {standalone},\n"
            "    hubcap = {\n"
            f"        enabled = {h_enabled},\n"
            f'        api_key = "{escape_lua_string(h_api_key)}",\n'
            f"        api_key_timestamp = {h_ts},\n"
            f'        base_url = "{escape_lua_string(h_base_url)}",\n'
            f"        timeout_sec = {h_timeout},\n"
            f"        write_config = {h_write_config},\n"
            f"        notify = {h_notify},\n"
            f'        preflight = "{escape_lua_string(h_preflight)}",\n'
            f"        depot_index = {h_depot_index},\n"
            f"        write_depot_comments = {h_comments},\n"
            "    },\n"
            "}\n"
        )
        tmp = conf_path.with_suffix(".tmp")
        tmp.write_text(lua_code, encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, conf_path)
        return True
    except Exception as exc:
        logger.error("Failed to write %s: %s", conf_path, exc)
        return False


def sync_spacebunny_key(conf_path: Path, api_key: str, timestamp: int | None = None) -> bool:
    """Update only api_key and timestamp in spacebunny.conf.lua, preserving all other settings."""
    cfg = read_spacebunny_conf(conf_path)
    hub = cfg.get("hubcap", {})
    hub["api_key"] = api_key
    hub["api_key_timestamp"] = timestamp if timestamp is not None else generate_hubcap_timestamp()
    cfg["hubcap"] = hub
    return write_spacebunny_conf(cfg, conf_path)


# ---------------------------------------------------------------------------
# Bidirectional Hubcap Key Synchronization Bridge
# ---------------------------------------------------------------------------

def sync_hubcap_key_bidirectional(settings, conf_path: Path | None, assella_home: Path | None) -> tuple[str, bool, str]:
    """Synchronize Hubcap API key bidirectionally between Uran settings, spacebunny.conf.lua, and ASSella.

    Returns:
      (active_key, was_synced, reason)
    """
    from . import paths

    local_key = str(settings.stored_hubcap_key() or "").strip()
    try:
        raw_val = settings.get("manifest_api_key_timestamp", 0)
        local_ts = int(str(raw_val).strip() or 0)
    except (ValueError, TypeError):
        local_ts = 0

    # Also check ASSella INI if present
    assella_key = ""
    assella_ts = 0
    if assella_home:
        for p in paths.accela_conf_candidates(assella_home):
            if p.is_file():
                k = paths.read_ini_value(p, "morrenus_api_key")
                if k:
                    assella_key = k
                    try:
                        assella_ts = int(paths.read_ini_value(p, "morrenus_api_key_timestamp") or 0)
                    except (ValueError, TypeError):
                        assella_ts = 0
                    break

    # If local setting has no key but ASSella INI does, adopt ASSella's
    if not local_key and assella_key:
        local_key = assella_key
        local_ts = assella_ts or generate_hubcap_timestamp()
        settings.set("manifest_api_key", local_key)
        settings.set("manifest_api_key_timestamp", local_ts)

    # If spacebunny.conf.lua is not accessible, return local key
    if conf_path is None or not conf_path.is_file():
        return local_key, False, "spacebunny.conf.lua not present"

    sb_cfg = read_spacebunny_conf(conf_path)
    hub = sb_cfg.get("hubcap", {})
    lua_key = str(hub.get("api_key", "")).strip()
    lua_ts = int(hub.get("api_key_timestamp", 0) or 0)

    lua_sort = _timestamp_to_sort_key(lua_ts)
    local_sort = _timestamp_to_sort_key(local_ts)

    # 1. Lua is newer and has a valid key -> sync to Uran settings and ASSella
    if lua_sort > local_sort and is_valid_hubcap_key(lua_key):
        settings.set("manifest_api_key", lua_key)
        settings.set("manifest_api_key_timestamp", lua_ts)
        if assella_home:
            paths.write_accela_api_key(lua_key, assella_home, timestamp=lua_ts)
        logger.info("Synced newer Hubcap API key from Lua (ts: %s) to Uran", lua_ts)
        return lua_key, True, "Synced newer key from spacebunny.conf.lua bridge"

    # 2. Local is newer (or Lua has no key) and local key is valid -> sync to spacebunny.conf.lua
    elif (local_sort > lua_sort or (local_sort > 0 and lua_sort == 0) or (not lua_key and local_key)) and is_valid_hubcap_key(local_key):
        sync_spacebunny_key(conf_path, local_key, local_ts or generate_hubcap_timestamp())
        logger.info("Synced newer Hubcap API key from Uran (ts: %s) to Lua", local_ts)
        return local_key, True, "Synced key to spacebunny.conf.lua bridge"

    # 3. If Lua has a key but local doesn't have any timestamp -> initial adoption
    elif is_valid_hubcap_key(lua_key) and not local_key:
        settings.set("manifest_api_key", lua_key)
        settings.set("manifest_api_key_timestamp", lua_ts or generate_hubcap_timestamp())
        return lua_key, True, "Adopted key from spacebunny.conf.lua"

    return local_key or lua_key, False, "Already in sync"
