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
    """Timestamp in YYYYMMDDHHMMSS form (e.g. 20261107174500), the same as ASSella writes.

    The old minute-hour-day-year form had no month, so a key from Oct 26 looked
    newer than one from Nov 7 and the wrong key won the sync.
    """
    now = time.localtime()
    return int(
        f"{now.tm_year:04d}{now.tm_mon:02d}{now.tm_mday:02d}"
        f"{now.tm_hour:02d}{now.tm_min:02d}{now.tm_sec:02d}"
    )


def _timestamp_to_sort_key(ts: int) -> int:
    """Chronologically sortable value; identical to ASSella's ordering.

      - YYYYMMDDHHMMSS (current form): as-is, always newer than the old forms.
      - Old mmhhddyyyy form (no month): year/day/hour/minute, sorts below every
        current-form timestamp.
      - Anything else (Unix epoch): as-is.
    """
    try:
        ts = int(ts or 0)
    except (TypeError, ValueError):
        return 0
    if ts <= 0:
        return 0
    if ts >= 20200101000000:
        return ts
    s = str(ts)
    if len(s) in (9, 10) and any(s.endswith(str(y)) for y in range(2020, 2040)):
        try:
            p = s.zfill(10)
            return int(p[6:10]) * 100000000 + int(p[4:6]) * 1000000 + int(p[2:4]) * 10000 + int(p[0:2])
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

def katamari_conf_path(spacebunny_conf_path: Path | None) -> Path | None:
    """katamari.conf.lua sits next to spacebunny.conf.lua (the SLSsteam config dir)."""
    if spacebunny_conf_path is None:
        return None
    return spacebunny_conf_path.parent / "katamari.conf.lua"


def _hubcap_block(text: str) -> tuple[int, int] | None:
    """(start, end) of the hubcap = { ... } table, braces matched."""
    m = re.search(r"^\s*hubcap\s*=\s*\{", text, re.MULTILINE)
    if not m:
        return None
    start = m.end() - 1
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return start, i + 1
    return None


def read_katamari_hubcap_key(path: Path | None) -> tuple[str, int]:
    """(api_key, api_key_timestamp) from katamari.conf.lua's hubcap section."""
    if path is None or not path.is_file():
        return "", 0
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "", 0
    span = _hubcap_block(text)
    if not span:
        return "", 0
    block = text[span[0]:span[1]]
    key, ts = "", 0
    m = re.search(r"^\s*api_key\s*=\s*([^,\n\r]+)", block, re.MULTILINE)
    if m:
        key = _parse_string(m.group(1)) or ""
    m = re.search(r"^\s*api_key_timestamp\s*=\s*([^,\n\r]+)", block, re.MULTILINE)
    if m:
        ts = _parse_int(m.group(1)) or 0
    return key.strip(), ts


def write_katamari_hubcap_key(path: Path | None, api_key: str, timestamp: int) -> bool:
    """Change only hubcap.api_key / api_key_timestamp in an existing katamari.conf.lua.

    ASSella owns the file; this touches nothing else and never creates it.
    """
    if path is None or not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        span = _hubcap_block(text)
        if not span:
            return False
        block = text[span[0]:span[1]]
        for name, value in (("api_key", f'"{escape_lua_string(api_key)}"'),
                            ("api_key_timestamp", str(int(timestamp or 0)))):
            pat = re.compile(r"^(\s*" + name + r"\s*=\s*)([^,\n\r]+)(,?)", re.MULTILINE)
            if pat.search(block):
                block = pat.sub(lambda m: m.group(1) + value + m.group(3), block, count=1)
            else:
                cut = block.rfind("}")
                block = block[:cut] + f"\t\t{name} = {value},\n\t" + block[cut:]
        new_text = text[:span[0]] + block + text[span[1]:]
        if new_text != text:
            with open(path, "w", encoding="utf-8") as handle:  # in place: keeps inode and mode
                handle.write(new_text)
        return True
    except Exception as exc:
        logger.error("Failed writing Hubcap key to %s: %s", path, exc)
        return False


def sync_hubcap_key_bidirectional(settings, conf_path: Path | None, assella_home: Path | None) -> tuple[str, bool, str]:
    """Share one Hubcap API key between this companion, ASSella and the AT0-M plugins.

    Places that can hold the key: this companion's settings, ASSella's config,
    katamari.conf.lua (what the Lua plugins read) and the legacy
    spacebunny.conf.lua. The key with the newest timestamp wins and is copied
    to every place that exists and holds a different key. Nothing is created.

    Returns (active_key, was_synced, reason).
    """
    from . import paths

    def _int(v) -> int:
        try:
            return int(str(v).strip() or 0)
        except (TypeError, ValueError):
            return 0

    sources: list[tuple[str, str, int]] = []  # (where, key, ts); order breaks ties

    katamari = katamari_conf_path(conf_path)
    if katamari is not None and katamari.is_file():
        k, t = read_katamari_hubcap_key(katamari)
        sources.append(("katamari.conf.lua", k, t))

    assella_conf = None
    if assella_home:
        for p in paths.accela_conf_candidates(assella_home):
            if p.is_file():
                assella_conf = p
                sources.append(("ASSella", (paths.read_ini_value(p, "morrenus_api_key") or "").strip(),
                                _int(paths.read_ini_value(p, "morrenus_api_key_timestamp"))))
                break

    local_key = str(settings.stored_hubcap_key() or "").strip()
    sources.append(("companion", local_key, _int(settings.get("manifest_api_key_timestamp", 0))))

    if conf_path is not None and conf_path.is_file():
        hub = read_spacebunny_conf(conf_path).get("hubcap", {})
        sources.append(("spacebunny.conf.lua", str(hub.get("api_key", "")).strip(),
                        _int(hub.get("api_key_timestamp", 0))))

    valid = [s for s in sources if is_valid_hubcap_key(s[1])]
    if not valid:
        return local_key, False, "No Hubcap key anywhere"
    best = max(_timestamp_to_sort_key(s[2]) for s in valid)
    where, key, ts = next(s for s in valid if _timestamp_to_sort_key(s[2]) == best)

    updated = []
    for name, k, _t in sources:
        if k == key:
            continue
        ok = False
        if name == "companion":
            settings.set("manifest_api_key", key)
            settings.set("manifest_api_key_timestamp", ts)
            ok = True
        elif name == "ASSella" and assella_home:
            ok, _msg = paths.write_accela_api_key(key, assella_home, timestamp=ts)
        elif name == "katamari.conf.lua":
            ok = write_katamari_hubcap_key(katamari, key, ts)
        elif name == "spacebunny.conf.lua":
            ok = sync_spacebunny_key(conf_path, key, ts)
        if ok:
            updated.append(name)

    if updated:
        logger.info("Hubcap key from %s (ts %s) copied to %s", where, ts, ", ".join(updated))
        return key, True, f"Synced key from {where} to {', '.join(updated)}"
    return key, False, "Already in sync"
