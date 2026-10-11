"""
Uran plugin — main.py

Backend for Uran Companion.
Searches Steam games, injects AppIDs, depots, and decryption keys into SLSsteam config.yaml,
and manages manifests & depot decryption keys via the Hubcap API (hubcapmanifest.com).

Fully public: No private ticket servers, no private vaults.
Works hand-in-hand with ASSella Canary.
"""

import os
import sys

# Bundle path: third-party packages live in defaults/python
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
_BUNDLE = os.path.join(_HERE, "defaults", "python")
if os.path.isdir(_BUNDLE):
    sys.path.insert(0, _BUNDLE)

import re
import io
import json
import time
import shutil
import asyncio
import bisect
import hashlib
import logging
import zipfile
import threading
import subprocess
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("Uran")

BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# HTTP client: use requests if bundled, otherwise fallback to urllib shim
# ---------------------------------------------------------------------------
try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

if not _HAS_REQUESTS:
    import ssl
    import json as _json
    import urllib.error
    import urllib.parse
    import urllib.request

    class _RequestException(Exception):
        """Stand-in for requests.RequestException."""

    class _UrllibResponse:
        def __init__(self, status: int, headers: dict, content: bytes):
            self.status_code = status
            self.headers = headers
            self.content = content
            self.text = content.decode("utf-8", errors="replace")

        @property
        def ok(self) -> bool:
            return 200 <= self.status_code < 300

        def json(self):
            return _json.loads(self.text)

        def raise_for_status(self) -> None:
            if not self.ok:
                raise _RequestException(f"HTTP {self.status_code}")

    def _build_ssl_context():
        for cafile in (
            "/etc/ssl/certs/ca-certificates.crt",
            "/etc/pki/tls/certs/ca-bundle.crt",
            "/etc/ssl/cert.pem",
        ):
            if os.path.exists(cafile):
                try:
                    return ssl.create_default_context(cafile=cafile)
                except Exception:
                    pass
        try:
            return ssl.create_default_context()
        except Exception:
            return None

    _SSL_CTX = _build_ssl_context()

    class _RequestsShim:
        RequestException = _RequestException

        @staticmethod
        def get(url, params=None, headers=None, timeout=10, stream=False):
            if params:
                query = urllib.parse.urlencode(params)
                url = f"{url}?{query}" if "?" not in url else f"{url}&{query}"
            req = urllib.request.Request(url, headers=headers or {})
            if "User-Agent" not in (headers or {}):
                req.add_header("User-Agent", BROWSER_UA)
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
                    return _UrllibResponse(resp.status, dict(resp.headers), resp.read())
            except urllib.error.HTTPError as e:
                return _UrllibResponse(e.code, dict(e.headers), e.read())
            except Exception as e:
                raise _RequestException(str(e)) from e

        @staticmethod
        def post(url, data=None, json=None, headers=None, timeout=10):
            req_headers = dict(headers or {})
            body = None
            if json is not None:
                body = _json.dumps(json).encode("utf-8")
                req_headers["Content-Type"] = "application/json"
            elif data is not None:
                if isinstance(data, dict):
                    body = urllib.parse.urlencode(data).encode("utf-8")
                    req_headers["Content-Type"] = "application/x-www-form-urlencoded"
                elif isinstance(data, bytes):
                    body = data
                elif isinstance(data, str):
                    body = data.encode("utf-8")
            if "User-Agent" not in req_headers:
                req_headers["User-Agent"] = BROWSER_UA
            req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
                    return _UrllibResponse(resp.status, dict(resp.headers), resp.read())
            except urllib.error.HTTPError as e:
                return _UrllibResponse(e.code, dict(e.headers), e.read())
            except Exception as e:
                raise _RequestException(str(e)) from e

    requests = _RequestsShim()

# ---------------------------------------------------------------------------
# Decky environment detection
# ---------------------------------------------------------------------------
try:
    import decky_plugin as decky
except ImportError:
    decky = None

APP_CONFIG_DIR = "assella-decky"
SLSSTEAM_API_PIPE = "/tmp/SLSsteam.API"

# ---------------------------------------------------------------------------
# SLSsteam config constants — kept in lockstep with ASSella (utils/yaml/constants.py)
# ---------------------------------------------------------------------------
# Steamworks redistributable depots. These are shared across every game, so
# ASSella force-tags them with a magic comment that marks them exempt from
# uninstall cleanup. We mirror that exactly so both tools agree on ownership.
SHARED_REDISTS: set[str] = {
    "228980", "1034630", "228981", "228982", "228983", "228984", "228985",
    "228986", "228987", "228988", "228989", "228990", "229000", "229001",
    "229002", "229003", "229004", "229005", "229006", "229007", "229010",
    "229011", "229012", "229020", "229030", "229031", "229032",
}
# Magic ownership marker read back by ASSella's cleanup heuristics.
SHARED_COMMENT = "Steamworks Shared"

_HEX_64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_NUMERIC_ID_RE = re.compile(r"^\d+$")
_TOP_LEVEL_KEY_RE = re.compile(r"^['\"]?[A-Za-z0-9_]+['\"]?[ \t]*:", re.MULTILINE)

# Default settings
SETTINGS_DEFAULTS = {
    "show_restart_button": False,
    "fetch_dlcs_on_inject": False,
    "manifestid_pinning": False,
    "steam_store_enabled": True,
    "manifest_api_key": "",
    "notification_mode": "auto",
}

# ---------------------------------------------------------------------------
# State & Locks
# ---------------------------------------------------------------------------
_sls_write_lock = threading.Lock()
# RLock (not Lock): _load_settings + _save_settings are sometimes called as a
# pair while already holding this, and a plain Lock would self-deadlock.
_settings_write_lock = threading.RLock()
_recent_injects: list[dict] = []
_inject_status: dict[str, dict] = {}
_store_details_cache: dict[str, dict] = {}
_steamcmd_details_cache: dict[str, dict] = {}
_depot_name_cache: dict[str, str] = {}

# ---------------------------------------------------------------------------
# Settings Management & ASSella Canary Auto-Detection
# ---------------------------------------------------------------------------
def _settings_dir() -> Path:
    if decky and hasattr(decky, "DECKY_SETTINGS_DIR"):
        d = Path(decky.DECKY_SETTINGS_DIR)
    elif decky and hasattr(decky, "DECKY_PLUGIN_SETTINGS_DIR"):
        d = Path(decky.DECKY_PLUGIN_SETTINGS_DIR)
    else:
        d = Path.home() / ".config" / APP_CONFIG_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d

def _settings_path() -> Path:
    return _settings_dir() / "settings.json"

def _load_settings() -> dict:
    p = _settings_path()
    cfg = dict(SETTINGS_DEFAULTS)
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text()))
        except Exception as e:
            logger.warning("failed loading settings.json: %s", e)

    # If no Hubcap key is configured yet, attempt auto-detection from ACCELA.
    # NOTE: _detect_assella_canary_hubcap_key reads settings.json directly (not
    # via _load_settings) so this does not recurse.
    if not cfg.get("manifest_api_key"):
        detected = _detect_assella_canary_hubcap_key()
        if detected:
            cfg["manifest_api_key"] = detected

    return cfg

def _save_settings(s: dict) -> None:
    with _settings_write_lock:
        try:
            p = _settings_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(s, indent=2))
            tmp.replace(p)
        except Exception as e:
            logger.error("failed saving settings: %s", e)

def _get_setting(key: str, default=None):
    s = _load_settings()
    return s.get(key, default if default is not None else SETTINGS_DEFAULTS.get(key))

def _set_setting(key: str, value) -> None:
    s = _load_settings()
    s[key] = value
    _save_settings(s)

# ---------------------------------------------------------------------------
# Path Resolvers (Steam & SLSsteam)
# ---------------------------------------------------------------------------
def _user_home() -> Path:
    """Resolve the real active user home directory even when running under Decky's daemon."""
    if decky and hasattr(decky, "DECKY_USER_HOME") and decky.DECKY_USER_HOME:
        return Path(decky.DECKY_USER_HOME)
    decky_user = os.environ.get("DECKY_USER")
    if decky_user:
        user_p = Path(f"/home/{decky_user}")
        if user_p.is_dir():
            return user_p
    # Steam Deck standard user fallback
    deck_home = Path("/home/deck")
    if deck_home.is_dir():
        return deck_home
    return Path.home()

def _write_accela_api_key(key: str) -> tuple[bool, str]:
    """Write morrenus_api_key into ASSella's ACCELA.conf so BOTH apps share it.

    ASSella reads it with QSettings("Tachibana Labs", "ACCELA"), which on Linux
    is exactly this INI file. Writing here means ASSella picks the key up with
    no configuration on its side - that is what "hand in hand" requires.

    This file contains QVariant blobs (last_cached_user_stats) whose escaped
    form configparser would mangle, so we do a targeted line edit instead of a
    parse-and-rewrite: every other byte of the file is preserved verbatim.

    Returns (ok, message).
    """
    key = str(key or "").strip()
    if not key:
        return False, "No key to write."
    # A key must never contain a newline or '=' - that would corrupt the INI.
    if "\n" in key or "\r" in key or "=" in key:
        return False, "Key contains illegal characters."

    for path in _accela_conf_candidates():
        try:
            if not path.exists():
                continue
            original = path.read_text(encoding="utf-8", errors="replace")
            # Qt writes unquoted for simple token characters.
            entry = f"morrenus_api_key={key}"

            # Already correct -> nothing to do.
            if _read_ini_value(path, "morrenus_api_key") == key:
                return True, f"Key already present in {path}"

            # Replace an existing line (anywhere, any section) in place so we
            # keep the file's alphabetical ordering.
            pattern = re.compile(r"^[ \t]*morrenus_api_key[ \t]*=.*$", re.MULTILINE)
            if pattern.search(original):
                new_text = pattern.sub(lambda _m: entry, original, count=1)
            else:
                # Insert into [General] in alphabetical order, like Qt would.
                lines = original.splitlines()
                start = None
                for i, ln in enumerate(lines):
                    if ln.strip().lower() == "[general]":
                        start = i
                        break
                if start is None:
                    lines.insert(0, f"[General]\n{entry}")
                else:
                    end = len(lines)
                    for i in range(start + 1, len(lines)):
                        if lines[i].startswith("["):
                            end = i
                            break
                    pos = end
                    for i in range(start + 1, end):
                        k = lines[i].split("=", 1)[0].strip().lower()
                        if k and k > "morrenus_api_key":
                            pos = i
                            break
                    lines.insert(pos, entry)
                new_text = "\n".join(lines) + ("\n" if original.endswith("\n") else "")

            if new_text == original:
                return True, f"No change needed in {path}"

            # Back up before touching another application's config.
            try:
                shutil.copy2(path, path.with_suffix(f".conf.decky-backup-{int(time.time())}"))
            except OSError as e:
                logger.debug("Could not back up ACCELA.conf: %s", e)

            # Preserve permissions; write in place to keep any hardlinks/inode.
            with open(path, "r+", encoding="utf-8") as f:
                f.seek(0)
                f.write(new_text)
                f.truncate()
                f.flush()
                os.fsync(f.fileno())
            logger.info("Wrote morrenus_api_key into ACCELA config: %s", path)
            return True, f"Key saved to {path} (shared with ASSella)"

        except Exception as e:
            logger.error("Failed writing ACCELA key to %s: %s", path, e)
            continue

    try:
        primary = _user_home() / ".config" / "Tachibana Labs" / "ACCELA.conf"
        primary.parent.mkdir(parents=True, exist_ok=True)
        primary.write_text(f"[General]\nmorrenus_api_key={key}\n", encoding="utf-8")
        logger.info("Created ACCELA config at %s and saved morrenus_api_key", primary)
        return True, f"Key saved to {primary} (shared with ASSella)"
    except Exception as e:
        logger.error("Failed creating ACCELA.conf: %s", e)
    return False, "Could not locate or create a writable ACCELA.conf."

def _accela_conf_candidates() -> list[Path]:
    """Config files ACCELA may store morrenus_api_key in, newest layout first.

    ACCELA Canary writes an INI file at `Tachibana Labs/ACCELA.conf`; older
    builds used `~/.config/ACCELA/Settings.conf`.
    """
    home = _user_home()
    cands = []
    for h in (home, Path.home(), Path("/home/deck")):
        if not h:
            continue
        cands.extend([
            h / ".config" / "Tachibana Labs" / "ACCELA.conf",
            h / ".var" / "app" / "com.valvesoftware.Steam" / "config" / "Tachibana Labs" / "ACCELA.conf",
            h / ".var" / "app" / "com.tachibanalabs.accela" / "config" / "Tachibana Labs" / "ACCELA.conf",
            h / ".config" / "ACCELA" / "Settings.conf",
            h / ".config" / "ACCELA" / "ACCELA.conf",
            h / ".config" / "ACCELA" / "ASSella.conf",
        ])
    seen, out = set(), []
    for p in cands:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out

def _read_ini_value(path: Path, key: str) -> str:
    """Read a scalar from an INI file, ignoring section headers and comments.

    Handles `key=value` and `key = value` (ACCELA writes the spaced form inside
    a [General] section), plus quoted values and inline `;` comments.
    """
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith((";", "#", "[")):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip().lower() != key.lower():
                continue
            v = v.strip()
            if ";" in v and not v.startswith(("\"", "'")):
                v = v.split(";", 1)[0].strip()
            v = v.strip().strip('"').strip("'").strip()
            if v:
                return v
    except Exception as e:
        logger.debug(f"Failed reading {key} from {path}: {e}")
    return ""

def _stored_hubcap_key() -> str:
    """Read the plugin's own key override straight from settings.json.

    Deliberately bypasses _load_settings(): the key detector is called *from*
    _load_settings, so going through it here would recurse.
    """
    p = _settings_path()
    if not p.exists():
        return ""
    try:
        data = json.loads(p.read_text())
        if isinstance(data, dict):
            return str(data.get("manifest_api_key") or "").strip()
    except Exception:
        pass
    return ""

_last_detected_hubcap_key_path = None

def _detect_assella_canary_hubcap_key() -> str:
    """Read the Hubcap (morrenus) API key from ACCELA's own settings.

    Same source and setting name ASSella uses, so the Decky plugin and ASSella
    always talk to Hubcap with the same key. An explicit override set in the
    plugin's own settings still wins.
    """
    global _last_detected_hubcap_key_path
    override = _stored_hubcap_key()
    if override:
        return override

    for p in _accela_conf_candidates():
        if not p.is_file():
            continue
        key = _read_ini_value(p, "morrenus_api_key")
        if key:
            if _last_detected_hubcap_key_path != str(p):
                _last_detected_hubcap_key_path = str(p)
                logger.info("Auto-detected Hubcap API key from ACCELA config (%s)", p)
            return key
    return ""

def _find_sls_config() -> Path | None:
    """Find active SLSsteam config.yaml."""
    home = _user_home()
    candidates = [
        home / ".config" / "SLSsteam" / "config.yaml",
        home / ".var/app/com.valvesoftware.Steam/.config/SLSsteam/config.yaml",
        home / ".local/share/SLSsteam/config.yaml",
        Path("/home/deck/.config/SLSsteam/config.yaml"),
        Path.home() / ".config" / "SLSsteam" / "config.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p
    # Default to standard path if it exists as directory
    standard_dir = home / ".config" / "SLSsteam"
    if standard_dir.is_dir():
        return standard_dir / "config.yaml"
    return None

def _steam_root_dir() -> Path | None:
    home = _user_home()
    candidates = [
        home / ".steam" / "steam",
        home / ".local/share/Steam",
        home / ".var/app/com.valvesoftware.Steam/data/Steam",
        Path("/home/deck/.steam/steam"),
        Path("/home/deck/.local/share/Steam"),
        Path.home() / ".steam" / "steam",
        Path.home() / ".local/share/Steam",
    ]
    for p in candidates:
        if p.is_dir():
            return p
    return None
    return None

def _depotcache_dir() -> Path | None:
    root = _steam_root_dir()
    if root is None:
        return None
    cache = root / "depotcache"
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return cache

def _manifest_cache_dir() -> Path:
    if decky and hasattr(decky, "DECKY_PLUGIN_RUNTIME_DIR"):
        base = Path(decky.DECKY_PLUGIN_RUNTIME_DIR)
    else:
        base = Path.home() / ".config" / APP_CONFIG_DIR
    cache = base / "manifests"
    cache.mkdir(parents=True, exist_ok=True)
    return cache

def _manifest_zip_path(app_id: str) -> Path:
    return _manifest_cache_dir() / f"{app_id}.zip"

# ---------------------------------------------------------------------------
# ACCELA plugin_library.json (AT0M game registry)
#
# ASSella's AT0M mode registers every native-Steam game here
# (utils/plugin_games.py). If we inject into config.yaml without writing this
# record, ASSella does not see the game as AT0M-managed: it will not offer
# AT0M updates, and its cleanup cannot tell which depots belong to the game.
# So we write the same file, in the same location, with the same schema.
# ---------------------------------------------------------------------------
PLUGIN_LIBRARY_FILENAME = "plugin_library.json"

def _accela_base_path() -> Path:
    """ACCELA's XDG data dir, matching ASSella's utils.helpers.get_base_path()."""
    home = _user_home()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg and Path(xdg).is_absolute():
        return Path(xdg) / "ACCELA"
    return home / ".local" / "share" / "ACCELA"

def _accela_db_candidates(db_name: str) -> list[Path]:
    """Return prioritized candidate paths for an ACCELA SQLite database."""
    home = _user_home()
    candidates = [
        _accela_base_path() / "db" / db_name,
        _accela_base_path() / db_name,
        home / ".local" / "share" / "ACCELA" / "db" / db_name,
        home / ".local" / "share" / "ACCELA" / db_name,
        home / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "ACCELA" / "db" / db_name,
        home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "ACCELA" / "db" / db_name,
        Path("/home/deck/.local/share/ACCELA/db") / db_name,
    ]
    seen = set()
    deduped = []
    for c in candidates:
        s = str(c.resolve()) if c.exists() else str(c)
        if s not in seen:
            seen.add(s)
            deduped.append(c)
    return deduped

def _get_local_depot_keys(app_id: str, candidate_depots: set | None = None) -> dict[str, str]:
    """Retrieve cached depot keys from local depot_keys.db for an AppID and optional candidate depots."""
    aid = _sanitize_id(app_id)
    if not aid:
        return {}
    keys: dict[str, str] = {}
    for db_path in _accela_db_candidates("depot_keys.db"):
        if not db_path.exists():
            continue
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                rows = cur.execute(
                    "SELECT depot_id, aes_key FROM depot_keys WHERE appid = ? OR depot_id = ?",
                    (aid, aid)
                ).fetchall()
                for did, k in rows:
                    if did and k:
                        keys[str(did)] = str(k).strip()
                if candidate_depots:
                    for did in candidate_depots:
                        sd = _sanitize_id(did)
                        if sd and sd not in keys:
                            r = cur.execute(
                                "SELECT aes_key FROM depot_keys WHERE depot_id = ? LIMIT 1",
                                (sd,)
                            ).fetchone()
                            if r and r[0]:
                                keys[sd] = str(r[0]).strip()
            if keys:
                break
        except Exception as e:
            logger.debug("depot_keys.db query on %s failed: %s", db_path, e)
    return keys

def _save_local_depot_keys(app_id: str, keys: dict[str, str]) -> None:
    """Cache newly harvested depot keys into local depot_keys.db."""
    aid = _sanitize_id(app_id)
    if not aid or not keys:
        return
    for db_path in _accela_db_candidates("depot_keys.db"):
        if db_path.exists():
            try:
                now = int(time.time())
                with sqlite3.connect(db_path) as conn:
                    cur = conn.cursor()
                    for did, k in keys.items():
                        sd = _sanitize_id(did)
                        sk = str(k).strip()
                        if sd and sk:
                            cur.execute(
                                "INSERT OR REPLACE INTO depot_keys (appid, depot_id, aes_key, updated_at) VALUES (?, ?, ?, ?)",
                                (aid, sd, sk, now)
                            )
                    conn.commit()
                break
            except Exception as e:
                logger.debug("Failed saving keys to %s: %s", db_path, e)

def plugin_library_path() -> Path:
    """Path to ACCELA's plugin_library.json (db/ dir, with legacy fallback)."""
    base = _accela_base_path()
    target = base / "db" / PLUGIN_LIBRARY_FILENAME
    if target.exists():
        return target
    legacy = base / PLUGIN_LIBRARY_FILENAME
    if legacy.exists():
        return legacy
    return target

def load_plugin_library() -> dict:
    """Load ACCELA's plugin library. Returns {} when missing or corrupt."""
    path = plugin_library_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.error("Failed reading %s: %s", path, e)
        return {}

def save_plugin_library(data: dict) -> bool:
    """Persist the plugin library atomically (tmp + replace, sorted keys).

    Matches ASSella's save_plugin_library so the file stays byte-compatible
    with what ASSella writes and reads.
    """
    path = plugin_library_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except Exception as e:
        logger.error("Failed saving %s: %s", path, e)
        return False

def _register_plugin_game(
    appid: str,
    name: str,
    depot_ids: list,
    decryption_keys: dict,
    installdir: str = "",
    depot_names: dict | None = None,
    dlc_appids: list | None = None,
) -> bool:
    """Register a game in ACCELA's plugin_library.json (AT0M registry).

    Schema is taken verbatim from ASSella's register_plugin_game so ASSella
    treats games injected here identically to games it injected itself.
    """
    appid_str = str(appid).strip()
    if not appid_str.isdigit() or appid_str in ("0", "N/A", "unknown"):
        logger.warning("Invalid AppID '%s' for plugin registration", appid)
        return False

    clean_dlc = [str(d).strip() for d in (dlc_appids or []) if str(d).strip().isdigit()]
    clean_depots = [
        str(d).strip() for d in (depot_ids or [])
        if str(d).strip().isdigit() and str(d).strip() != appid_str and str(d).strip() not in clean_dlc
    ]

    clean_keys = {}
    for did, key in (decryption_keys or {}).items():
        did_str, key_str = str(did).strip(), str(key).strip()
        if did_str.isdigit() and _HEX_64_RE.match(key_str):
            clean_keys[did_str] = key_str

    # Only depots that have a key (or are shared redists) are safe to register;
    # otherwise Steam fails the download with DepotWithoutKey.
    valid = set(clean_keys) | SHARED_REDISTS
    excluded = [d for d in clean_depots if d not in valid]
    if excluded:
        logger.warning("Excluded %d unkeyed depot(s) for %s: %s", len(excluded), appid_str, excluded)
        clean_depots = [d for d in clean_depots if d in valid]

    clean_names = {}
    for did, dname in (depot_names or {}).items():
        did_str = str(did).strip()
        if did_str.isdigit() and dname and did_str != appid_str:
            clean_names[did_str] = str(dname).strip()

    lib = load_plugin_library()
    lib[appid_str] = {
        "appid": appid_str,
        "name": name,
        "installdir": installdir,
        "depots": clean_depots,
        "keys": clean_keys,
        "depot_names": clean_names,
        "dlc_only": bool(clean_dlc),
        "dlc_appids": clean_dlc,
        "updated_at": int(time.time()),
        "source": "plugin_native",
    }
    return save_plugin_library(lib)

def get_plugin_game(appid: str) -> dict | None:
    """Return an AT0M library record for this appid, if registered."""
    return load_plugin_library().get(str(appid).strip())

def list_plugin_games() -> dict:
    return load_plugin_library()

def unregister_plugin_game(appid: str, keep_in_additional_apps: bool = False) -> bool:
    """Remove a game from the AT0M library and clean every config trace.

    Mirrors ASSella's unregister_plugin_game: removes the AppID and its DLC
    AppIDs from AdditionalApps, drops FakeAppIds / LaunchOptions / DlcData /
    AppTokens, strips the secondary sections, and removes depots + keys that
    no other game still needs. Shared redistributables are never removed.

    All edits land in ONE batched write so SLSsteam never observes a
    half-purged config.
    """
    appid_str = str(appid).strip()
    lib = load_plugin_library()
    rec = lib.get(appid_str)
    if rec is None:
        return False

    dlc_appids = {str(d) for d in (rec.get("dlc_appids") or [])}
    target_depots = {str(d) for d in (rec.get("depots") or [])}
    target_keys = {str(d) for d in (rec.get("keys") or {})}
    target_keys.add(appid_str)  # the root AppKey lives under the AppID

    # Ownership comment scan: pick up entries ASSella attributed to this game.
    cfg = _find_sls_config()
    if cfg and cfg.exists():
        try:
            content = cfg.read_text(encoding="utf-8", errors="replace")
            gname = _sanitize_comment(rec.get("name") or "")
            for sec in ("AdditionalDepots", "DecryptionKeys"):
                bounds = _get_section_bounds(content, sec)
                if not bounds:
                    continue
                for line in content[bounds[1]:bounds[2]].splitlines():
                    m = re.match(
                        r"^[ \t]*-[ \t]*['\"]?(\d+)['\"]?[ \t]*(?:#[ \t]*(.*))?$", line
                    ) or re.match(
                        r"^[ \t]*['\"]?(\d+)['\"]?[ \t]*:[ \t]*[^#\r\n]*#[ \t]*(.*)$", line
                    )
                    if not m:
                        continue
                    item_id, comment = m.group(1), (m.group(2) or "").lower()
                    if item_id in SHARED_REDISTS:
                        continue
                    if appid_str in comment or (gname and len(gname) > 3 and gname in comment):
                        (target_depots if sec == "AdditionalDepots" else target_keys).add(item_id)
        except Exception as e:
            logger.debug("ownership scan failed for %s: %s", appid_str, e)

    # Depots/keys still referenced by the OTHER registered games.
    remaining_depots: set[str] = set()
    remaining_keys: set[str] = set()
    for other_id, other in lib.items():
        if other_id == appid_str:
            continue
        remaining_depots |= {str(d) for d in (other.get("depots") or [])}
        remaining_keys |= {str(d) for d in (other.get("keys") or {})}

    secondary_sections = (
        "GameTitles", "ManifestIds", "DepotBlacklist", "CDKeys",
        "FakeOffline", "SubscriptionTimestamps", "DenuvoGames",
    )

    with _batch_config_edit() as editor:
        if keep_in_additional_apps:
            # AT0-M -> ACCELA conversion: keep the AppID, drop DLCs we own.
            editor.add_app(appid_str, comment=_sanitize_comment(rec.get("name") or ""))
            for dlc_id in dlc_appids:
                editor.remove_app(dlc_id)
                editor.remove_fake_app_id(dlc_id)
                editor.remove_launch_option(dlc_id)
        else:
            for dlc_id in dlc_appids:
                editor.remove_app(dlc_id)
                editor.remove_fake_app_id(dlc_id)
                editor.remove_launch_option(dlc_id)
            if not rec.get("dlc_only"):
                editor.remove_app(appid_str)

            editor.remove_fake_app_id(appid_str)
            editor.remove_launch_option(appid_str)
            editor.remove_dlc(appid_str)

        # Secondary sections for the app, its DLCs and its depots.
        ids = [appid_str] + sorted(dlc_appids) + sorted(target_depots)
        for sec in secondary_sections:
            for item in ids:
                editor._apply(*_remove_in_memory(editor.content, sec, item, is_list=None))

        for did in sorted(target_depots):
            if did in SHARED_REDISTS or did in remaining_depots:
                continue
            editor.remove_depot(did)
        for did in sorted(target_keys):
            if did in SHARED_REDISTS or did in remaining_keys:
                continue
            editor.remove_key(did)

    if not editor.committed_successfully:
        logger.error("Failed to clean SLSsteam config while unregistering %s", appid_str)
        return False

    lib.pop(appid_str, None)
    if not save_plugin_library(lib):
        return False
    _signal_slssteam_api("RELOAD")
    return True

def _remove_dlc_block(content: str, app_id: str) -> str | None:
    """Remove a game's whole nested DlcData block (and its child lines).

    Returns the new content, or None when nothing matched.
    """
    bounds = _get_section_bounds(content, "DlcData")
    if not bounds:
        return None
    _, c_start, s_end = bounds
    sec = content[c_start:s_end]
    pattern = re.compile(
        rf"^[ \t]{{1,4}}['\"]?{re.escape(app_id)}['\"]?[ \t]*:[^\r\n]*(?:\r?\n(?:^[ \t]+[^\r\n]*\r?\n)*)?",
        re.MULTILINE,
    )
    new_sec, n = pattern.subn("", sec, count=1)
    if not n:
        return None
    return content[:c_start] + new_sec + content[s_end:]

def _signal_slssteam_api(command: str = "RELOAD") -> bool:
    """Signal /tmp/SLSsteam.API pipe for zero-restart instant hot reload."""
    pipe = Path(SLSSTEAM_API_PIPE)
    if not pipe.exists():
        return False
    try:
        with open(pipe, "w") as f:
            f.write(command.strip() + "\n")
            f.flush()
        logger.info(f"Signaled SLSsteam.API: {command}")
        return True
    except OSError as e:
        logger.debug(f"Could not signal SLSsteam.API: {e}")
        return False

# ---------------------------------------------------------------------------
# FakeAppIds Management
# ---------------------------------------------------------------------------
def get_fake_app_ids() -> dict:
    cfg = _find_sls_config()
    if not cfg or not cfg.exists():
        return {"ok": True, "ids": []}
    ids = []
    in_sec = False
    for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        st = line.strip()
        if st == "FakeAppIds:":
            in_sec = True
            continue
        if not in_sec:
            continue
        if not line.startswith((" ", "\t")):
            break
        if ":" in st and not st.startswith("#"):
            k = st.split(":", 1)[0].strip()
            if k.isdigit():
                ids.append(k)
    return {"ok": True, "ids": ids}

def add_fake_app_id(app_id: str) -> dict:
    with _batch_config_edit() as editor:
        inserted = editor.add_fake_app_id(app_id, "480")
    return {"ok": editor.committed_successfully, "message": "Updated" if inserted else "Already up to date"}

def remove_fake_app_id(app_id: str) -> dict:
    with _batch_config_edit() as editor:
        removed = editor._apply(*_remove_in_memory(editor.content, "FakeAppIds", app_id, is_list=False))
    return {"ok": editor.committed_successfully, "message": "Removed" if removed else "Not found"}

# ---------------------------------------------------------------------------
# DecryptionKeys Management
# ---------------------------------------------------------------------------
def get_configured_depot_keys() -> dict:
    cfg = _find_sls_config()
    if not cfg or not cfg.exists():
        return {"ok": True, "keys": {}}
    keys = {}
    in_sec = False
    for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        st = line.strip()
        if st == "DecryptionKeys:":
            in_sec = True
            continue
        if not in_sec:
            continue
        if not line.startswith((" ", "\t")):
            break
        if ":" in st and not st.startswith("#") and not st.startswith("-"):
            did, _, val = st.partition(":")
            if did.strip().isdigit():
                keys[did.strip()] = val.split("#")[0].strip()
    return {"ok": True, "keys": keys}

# ---------------------------------------------------------------------------
# AT0M game manager
#
# Reads ACCELA's plugin_library.json (the same registry ASSella's AT0M mode
# writes) plus Steam's appmanifest files, and exposes the per-game toggles:
#   SLSonline -> FakeAppIds section
#   NetSock   -> LaunchOptions section (env LD_AUDIT=...)
#   EOS Proxy -> filesystem swap of EOSSDK-Win64-Shipping.dll/.yes
# Semantics (guards, cascades, comment suffixes) follow ASSella so both tools
# operate on identical config.
# ---------------------------------------------------------------------------
_EOS_DLL = "eossdk-win64-shipping.dll"
_EOS_YES = "eossdk-win64-shipping.yes"
_EOS_PROXY_URL = "https://github.com/yesyes0649/eos-proxy/releases/download/v1.0.0/EOSSDK-Win64-Shipping.dll"
_NETSOCK_URL = "https://github.com/yesyes0649/steamnetsock-patch/releases/download/latest/fix.so"
_EOS_PRUNE_DIRS = {
    ".depotdownloader", "__pycache__", "content", "paks", "pak", "assets",
    "sound", "sounds", "audio", "music", "media", "video", "videos", "movies",
    "textures", "cache", "saves", "screenshots", "shadercache",
    "streamingassets", "node_modules", ".git",
}

def _steam_libraries() -> list[Path]:
    """Steam library folders from libraryfolders.vdf, plus native fallbacks."""
    libs: list[Path] = []
    root = _steam_root_dir()
    if root:
        vdf = root / "steamapps" / "libraryfolders.vdf"
        try:
            if vdf.is_file():
                content = vdf.read_text(encoding="utf-8", errors="replace")
                # "path"  "/mnt/games/SteamLibrary"
                for m in re.finditer(r'"path"\s+"([^"]+)"', content):
                    p = Path(m.group(1).replace("\\\\", "\\"))
                    if p.is_dir() and p not in libs:
                        libs.append(p)
        except Exception as e:
            logger.debug("libraryfolders.vdf parse failed: %s", e)

    home = _user_home()
    for fb in (
        home / ".local/share/Steam",
        home / ".steam/steam",
        home / ".var/app/com.valvesoftware.Steam/data/Steam",
    ):
        if fb.is_dir() and fb not in libs:
            libs.append(fb)
    return libs

def _parse_acf(path: Path) -> dict:
    """Pull the useful fields out of a Steam appmanifest_<appid>.acf file."""
    out: dict = {}
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return out
    for field, key in (
        (r'"installdir"\s+"([^"]*)"', "installdir"),
        (r'"name"\s+"([^"]*)"', "name"),
        (r'"StateFlags"\s+"(\d+)"', "StateFlags"),
        (r'"buildid"\s+"(\d+)"', "buildid"),
        (r'"LastUpdated"\s+"(\d+)"', "LastUpdated"),
        (r'"SizeOnDisk"\s+"(\d+)"', "SizeOnDisk"),
        (r'"LastOwner"\s+"(\d+)"', "LastOwner"),
    ):
        m = re.search(field, content)
        if m:
            out[key] = m.group(1)
    try:
        out["SizeOnDisk"] = int(out.get("SizeOnDisk") or 0)
    except ValueError:
        out["SizeOnDisk"] = 0
    try:
        out["StateFlags"] = int(out.get("StateFlags") or 0)
    except ValueError:
        out["StateFlags"] = 0
    return out

def _atom_install_info(app_id: str) -> dict:
    """Locate an AT0M game's install dir across every Steam library.

    Mirrors ASSella's get_atom_game_install_info: appmanifest_<appid>.acf's
    "installdir" under steamapps/common, plus staged download folders.
    """
    info = {
        "installed": False, "install_path": "", "library_path": "",
        "install_dir": "", "game_name": "", "buildid": "",
        "size_on_disk": 0, "downloading": False, "state_flags": 0,
    }
    for lib in _steam_libraries():
        steamapps = lib / "steamapps"
        if not steamapps.is_dir():
            continue
        acf = steamapps / f"appmanifest_{app_id}.acf"
        if not acf.is_file():
            continue
        acf_data = _parse_acf(acf)
        installdir = acf_data.get("installdir") or ""
        info.update({
            "installed": True,
            "library_path": str(lib),
            "install_dir": installdir,
            "install_path": str(steamapps / "common" / installdir) if installdir else "",
            "game_name": acf_data.get("name") or "",
            "buildid": acf_data.get("buildid") or "",
            "size_on_disk": acf_data.get("SizeOnDisk", 0),
            "state_flags": acf_data.get("StateFlags", 0),
            "acf_path": str(acf),
        })
        break

    if not info["installed"]:
        # Might still be mid-download (no appmanifest written yet).
        for lib in _steam_libraries():
            dl = lib / "steamapps" / "downloading" / app_id
            if dl.is_dir():
                info.update({"downloading": True, "install_path": str(dl),
                             "library_path": str(lib)})
                break
    return info

def list_atom_games() -> list[dict]:
    """All AT0M-registered games with their install state.

    Registry comes from ACCELA's plugin_library.json (written by ASSella or by
    this plugin); install state from Steam's appmanifest files.
    """
    games = []
    for app_id, rec in (load_plugin_library() or {}).items():
        if not isinstance(rec, dict):
            continue
        aid = _sanitize_id(app_id)
        if not aid:
            continue
        install = _atom_install_info(aid)
        games.append({
            "app_id": aid,
            "name": rec.get("name") or install.get("game_name") or f"App {aid}",
            "installed": bool(install.get("installed")),
            "downloading": bool(install.get("downloading")),
            "install_path": install.get("install_path", ""),
            "install_dir": install.get("install_dir", ""),
            "size_on_disk": install.get("size_on_disk", 0),
            "buildid": install.get("buildid", ""),
            "depots": rec.get("depots", []),
            "key_count": len(rec.get("keys", {}) or {}),
            "dlc_only": bool(rec.get("dlc_only")),
            "dlc_appids": rec.get("dlc_appids", []),
            "updated_at": rec.get("updated_at", 0),
            "source": rec.get("source", "plugin_native"),
        })
    games.sort(key=lambda g: (not g["installed"], g["name"].lower()))
    return games

def _inspect_game_depots_and_dlcs(aid: str, rec: dict) -> tuple[list[dict], list[dict], bool]:
    """Inspect and cross-reference depots and DLCs for a specific AT0-M game."""
    rec_depots = {str(d) for d in rec.get("depots", [])}
    rec_keys = {str(d): str(k) for d, k in (rec.get("keys", {}) or {}).items()}
    rec_names = {str(d): str(n) for d, n in (rec.get("depot_names", {}) or {}).items()}
    rec_dlcs = [str(d) for d in rec.get("dlc_appids", [])]

    sqlite_depots: dict[str, dict] = {}
    db_path = _accela_base_path() / "db" / "steam_headers.db"
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                rows = cur.execute(
                    "SELECT depot_id, name, is_dlc, oslist FROM depot_enrichments WHERE appid = ?",
                    (aid,)
                ).fetchall()
                for row in rows:
                    did = str(row[0])
                    sqlite_depots[did] = {
                        "name": str(row[1] or ""),
                        "is_dlc": bool(row[2]),
                        "oslist": str(row[3] or ""),
                    }
        except Exception as e:
            logger.debug("depot_enrichments error: %s", e)

    db_keys_path = _accela_base_path() / "db" / "depot_keys.db"
    if db_keys_path.exists():
        try:
            with sqlite3.connect(db_keys_path) as conn:
                cur = conn.cursor()
                rows = cur.execute(
                    "SELECT depot_id, aes_key FROM depot_keys WHERE appid = ?",
                    (aid,)
                ).fetchall()
                for did, k in rows:
                    rec_keys.setdefault(str(did), str(k))
        except Exception as e:
            logger.debug("depot_keys.db error: %s", e)

    cfg = _find_sls_config()
    live_apps: set[str] = set()
    live_depots: set[str] = set()
    live_keys: set[str] = set()
    if cfg and cfg.exists():
        try:
            content = cfg.read_text(encoding="utf-8", errors="ignore")
            live_apps = set(_parse_list_section(content, "AdditionalApps").keys())
            live_depots = set(_parse_list_section(content, "AdditionalDepots").keys())
            lkeys, _ = _parse_key_section(content, "DecryptionKeys")
            live_keys = set(lkeys.keys())
        except Exception as e:
            logger.debug("SLS config parse error: %s", e)

    if not rec_dlcs:
        try:
            details = get_app_details(aid)
            rec_dlcs = [str(d) for d in details.get("dlc", [])]
        except Exception:
            pass
    for did, info in sqlite_depots.items():
        if info.get("is_dlc") and did not in rec_dlcs:
            rec_dlcs.append(did)

    dlc_ids: set[str] = set(rec_dlcs)

    dlcs_list: list[dict] = []
    for did in sorted(dlc_ids, key=lambda x: int(x) if x.isdigit() else 0):
        raw_name = sqlite_depots.get(did, {}).get("name") or rec_names.get(did) or f"DLC {did}"
        dname = re.sub(r"^\[DLC\s*\d+\]\s*", "", raw_name)
        dlcs_list.append({
            "id": did,
            "name": dname,
            "in_config": did in live_apps,
        })

    all_depots = (rec_depots | set(sqlite_depots.keys()) | set(rec_keys.keys())) - {aid}
    depots_list: list[dict] = []
    for did in sorted(all_depots, key=lambda x: int(x) if x.isdigit() else 0):
        enrich = sqlite_depots.get(did, {})
        dname = enrich.get("name") or rec_names.get(did) or _depot_name_cache.get(did) or f"Depot {did}"
        in_config = did in live_depots
        has_key = did in live_keys or did in rec_keys
        is_dlc = enrich.get("is_dlc", False) or "[dlc" in dname.lower()
        is_shared = did in SHARED_REDISTS
        oslist = enrich.get("oslist", "")

        depots_list.append({
            "id": did,
            "name": dname,
            "in_config": in_config,
            "has_key": has_key,
            "is_dlc": is_dlc,
            "is_shared": is_shared,
            "os": oslist,
        })

    dlcs_injected = bool(dlcs_list and all(d["in_config"] for d in dlcs_list))
    return depots_list, dlcs_list, dlcs_injected

def toggle_game_dlcs(app_id: str, enable: bool) -> dict:
    """Add or remove a game's DLC AppIDs in AdditionalApps and sync keyed depots."""
    aid = _sanitize_id(app_id)
    if not aid:
        return {"ok": False, "error": "Invalid AppID"}

    if enable:
        details = get_app_details(aid)
        dlc_ids = [_sanitize_id(d) for d in details.get("dlc", [])]
        dlc_ids = [d for d in dlc_ids if d]

        rec = load_plugin_library().get(aid) or {}
        for d in rec.get("dlc_appids", []):
            sd = _sanitize_id(d)
            if sd and sd not in dlc_ids:
                dlc_ids.append(sd)

        manifest_res = fetch_manifests(aid, persist_config=False)
        for d in manifest_res.get("dlc_appids", []) if manifest_res.get("ok") else []:
            sd = _sanitize_id(d)
            if sd and sd not in dlc_ids:
                dlc_ids.append(sd)

        if not dlc_ids:
            return {"ok": False, "error": f"No DLCs found for AppID {aid}"}

        cfg = _find_sls_config()
        if cfg is None:
            return {"ok": False, "error": "SLSsteam config not found"}

        # DLC AppIDs and depot IDs are different namespaces. Use the database's
        # depot classification to select DLC depots, then take their keys from
        # the app bundle/library/database without registering base-game depots.
        dlc_depot_ids: set[str] = set()
        db_path = _accela_base_path() / "db" / "steam_headers.db"
        if db_path.exists():
            try:
                with sqlite3.connect(db_path) as conn:
                    rows = conn.cursor().execute(
                        "SELECT depot_id FROM depot_enrichments WHERE appid = ? AND (is_dlc = 1 OR name LIKE '%[DLC%')",
                        (aid,),
                    ).fetchall()
                dlc_depot_ids = {str(row[0]) for row in rows}
            except Exception as e:
                logger.debug("DLC depot lookup failed for %s: %s", aid, e)

        all_keys = dict(manifest_res.get("depot_keys", {})) if manifest_res.get("ok") else {}
        for did, key in (rec.get("keys") or {}).items():
            all_keys.setdefault(str(did), str(key))
        keys_db_path = _accela_base_path() / "db" / "depot_keys.db"
        if keys_db_path.exists():
            try:
                with sqlite3.connect(keys_db_path) as conn:
                    rows = conn.cursor().execute(
                        "SELECT depot_id, aes_key FROM depot_keys WHERE appid = ?", (aid,)
                    ).fetchall()
                for did, key in rows:
                    all_keys.setdefault(str(did), str(key))
            except Exception as e:
                logger.debug("DLC depot key lookup failed for %s: %s", aid, e)
        depot_keys = {did: key for did, key in all_keys.items() if did in dlc_depot_ids}

        marker = f"uran:dlc:{aid}"

        with _batch_config_edit() as editor:
            editor.content = _ensure_plugins_enabled(editor.content)
            editor.has_changes = True
            existing_apps = _parse_list_section(editor.content, "AdditionalApps")
            existing_depots = _parse_list_section(editor.content, "AdditionalDepots")
            existing_keys, _ = _parse_key_section(editor.content, "DecryptionKeys")
            for dlc_id in dlc_ids:
                # Only claim entries this feature creates. Existing user entries
                # retain their comments and are never removed by the off toggle.
                if dlc_id not in existing_apps:
                    editor.add_app(dlc_id, comment=marker)
            for did, key in (depot_keys or {}).items():
                if did != aid and did not in existing_depots:
                    editor.add_depot(did, comment=marker)
                if did != aid and did not in existing_keys:
                    editor.add_key(did, key, comment=marker)

        if not editor.committed_successfully:
            return {"ok": False, "error": "Failed to write SLSsteam config"}

        lib = load_plugin_library()
        if aid in lib:
            lib[aid]["dlc_appids"] = dlc_ids
            lib[aid]["dlcs_injected"] = True
            save_plugin_library(lib)

        return {"ok": True, "count": len(dlc_ids), "dlc_ids": dlc_ids}

    else:
        with _batch_config_edit() as editor:
            apps = _parse_list_section(editor.content, "AdditionalApps")
            depots = _parse_list_section(editor.content, "AdditionalDepots")
            _, key_comments = _parse_key_section(editor.content, "DecryptionKeys")
            marker = f"uran:dlc:{aid}"
            removed_apps = 0
            for entry_id, comment in apps.items():
                if comment == marker:
                    removed_apps += editor.remove_app(entry_id)
            for entry_id, comment in depots.items():
                if comment == marker:
                    editor.remove_depot(entry_id)
            for entry_id, comment in key_comments.items():
                if comment == marker:
                    editor.remove_key(entry_id)

        if not editor.committed_successfully:
            return {"ok": False, "error": "Failed to write SLSsteam config"}

        lib = load_plugin_library()
        if aid in lib:
            lib[aid]["dlcs_injected"] = False
            save_plugin_library(lib)

        return {"ok": True, "count": removed_apps}

def toggle_additional_app(app_id: str, dlc_appid: str, enable: bool) -> dict:
    """Add or remove a single AdditionalAppID (DLC) in config.yaml and manage its depot keys."""
    aid = _sanitize_id(app_id)
    dlc_id = _sanitize_id(dlc_appid)
    if not aid or not dlc_id:
        return {"ok": False, "error": "Invalid AppID"}

    cfg = _find_sls_config()
    if cfg is None:
        return {"ok": False, "error": "SLSsteam config not found"}

    marker = f"uran:dlc:{aid}"

    if enable:
        dlc_keys = _get_local_depot_keys(dlc_id)
        if not dlc_keys:
            parent_keys = _get_local_depot_keys(aid)
            if dlc_id in parent_keys:
                dlc_keys[dlc_id] = parent_keys[dlc_id]

        db_path = _accela_base_path() / "db" / "steam_headers.db"
        dlc_depots: set[str] = set()
        if db_path.exists():
            try:
                with sqlite3.connect(db_path) as conn:
                    rows = conn.cursor().execute(
                        "SELECT depot_id FROM depot_enrichments WHERE appid = ? AND (is_dlc = 1 OR depot_id = ?)",
                        (aid, dlc_id),
                    ).fetchall()
                    for row in rows:
                        if str(row[0]) == dlc_id:
                            dlc_depots.add(str(row[0]))
            except Exception as e:
                logger.debug("Enrichment lookup error for %s: %s", dlc_id, e)

        with _batch_config_edit() as editor:
            editor.content = _ensure_plugins_enabled(editor.content)
            editor.has_changes = True
            existing_apps = _parse_list_section(editor.content, "AdditionalApps")
            existing_depots = _parse_list_section(editor.content, "AdditionalDepots")
            existing_keys, _ = _parse_key_section(editor.content, "DecryptionKeys")

            if dlc_id not in existing_apps:
                editor.add_app(dlc_id, comment=marker)

            for did in dlc_depots:
                if did != aid and did not in existing_depots:
                    editor.add_depot(did, comment=marker)

            for did, key in dlc_keys.items():
                if did != aid and did not in existing_depots:
                    editor.add_depot(did, comment=marker)
                if did != aid and did not in existing_keys:
                    editor.add_key(did, key, comment=marker)

        if not editor.committed_successfully:
            return {"ok": False, "error": "Failed to write SLSsteam config"}

        lib = load_plugin_library()
        if aid in lib:
            dlcs = set(str(d) for d in lib[aid].get("dlc_appids", []))
            dlcs.add(dlc_id)
            lib[aid]["dlc_appids"] = sorted(list(dlcs), key=lambda x: int(x) if x.isdigit() else 0)
            save_plugin_library(lib)

        _signal_sls_api("RELOAD")
        return {"ok": True, "dlc_id": dlc_id, "enabled": True}

    else:
        with _batch_config_edit() as editor:
            apps = _parse_list_section(editor.content, "AdditionalApps")
            if dlc_id in apps:
                editor.content, changed = _remove_in_memory(editor.content, "AdditionalApps", dlc_id, is_list=True)
                if changed:
                    editor.has_changes = True

            depots = _parse_list_section(editor.content, "AdditionalDepots")
            if dlc_id in depots and marker in (depots.get(dlc_id) or ""):
                editor.content, changed = _remove_in_memory(editor.content, "AdditionalDepots", dlc_id, is_list=True)
                if changed:
                    editor.has_changes = True

            _, key_comments = _parse_key_section(editor.content, "DecryptionKeys")
            if dlc_id in key_comments and marker in (key_comments.get(dlc_id) or ""):
                editor.content, changed = _remove_in_memory(editor.content, "DecryptionKeys", dlc_id, is_list=False)
                if changed:
                    editor.has_changes = True

        lib = load_plugin_library()
        if aid in lib:
            dlcs = [str(d) for d in lib[aid].get("dlc_appids", []) if str(d) != dlc_id]
            lib[aid]["dlc_appids"] = dlcs
            save_plugin_library(lib)

        _signal_sls_api("RELOAD")
        return {"ok": True, "dlc_id": dlc_id, "enabled": False}

def get_atom_game_detail(app_id: str) -> dict:
    """Per-game state for the detail page: toggles, depots, DLCs, and install info."""
    aid = _sanitize_id(app_id)
    if not aid:
        return {"ok": False, "error": "Invalid AppID"}
    rec = load_plugin_library().get(aid) or {}
    install = _atom_install_info(aid)
    game_dir = Path(install.get("install_path") or "")

    global_online = is_global_slsonline_enabled()
    fake = get_fake_appid(aid)
    sls_online = bool(fake) or global_online
    netsock = is_netsock_active(aid)
    eos = eos_proxy_status(game_dir) if install.get("installed") else "none"

    depots_detail, dlcs_detail, dlcs_injected = _inspect_game_depots_and_dlcs(aid, rec)

    return {
        "ok": True,
        "app_id": aid,
        "name": rec.get("name") or install.get("game_name") or f"App {aid}",
        "installed": bool(install.get("installed")),
        "install_path": install.get("install_path", ""),
        "size_on_disk": install.get("size_on_disk", 0),
        "buildid": install.get("buildid", ""),
        "depots": rec.get("depots", []),
        "key_count": len(rec.get("keys", {}) or {}),
        "dlc_only": bool(rec.get("dlc_only")),
        "slsonline": sls_online,
        "global_slsonline": global_online,
        "fake_appid": fake,
        "netsock": netsock,
        "eos": eos,
        "eos_available": eos != "none",
        "registered": bool(rec),
        "depots_detail": depots_detail,
        "dlcs_detail": dlcs_detail,
        "dlcs_injected": dlcs_injected,
    }

def _sls_config_dir() -> Path:
    cfg = _find_sls_config()
    if cfg is not None:
        return cfg.parent
    return _user_home() / ".config" / "SLSsteam"

# --- FakeAppIds (SLSonline) ---------------------------------------------------
def get_fake_appid(app_id: str) -> str:
    """Read the FakeAppIds target for an AppID ("" when not mapped)."""
    cfg = _find_sls_config()
    if not cfg or not cfg.exists():
        return ""
    try:
        content = cfg.read_text(encoding="utf-8", errors="replace")
        bounds = _get_section_bounds(content, "FakeAppIds")
        if not bounds:
            return ""
        sec = content[bounds[1]:bounds[2]]
        m = re.search(rf"^[ \t]*['\"]?{re.escape(app_id)}['\"]?[ \t]*:[ \t]*(\d+)", sec, re.MULTILINE)
        return m.group(1) if m else ""
    except Exception as e:
        logger.debug("get_fake_appid(%s) failed: %s", app_id, e)
        return ""

def set_fake_appid(app_id: str, fake_appid: str, game_name: str = "") -> dict:
    """Add/update/remove a FakeAppIds entry (SLSonline toggle).

    Comment suffix matches ASSella: "<name> -> Spacewar" for 480, else
    "<name> -> SLSonline". Removal when fake_appid is "".
    """
    cfg = _find_sls_config()
    if cfg is None:
        return {"ok": False, "error": "SLSsteam config not found"}
    app_id = _sanitize_id(app_id)
    if not app_id:
        return {"ok": False, "error": "Invalid AppID"}

    name = _sanitize_comment(game_name)
    with _batch_config_edit() as editor:
        if fake_appid:
            target = _sanitize_id(fake_appid)
            if not target:
                return {"ok": False, "error": "Invalid fake AppID"}
            suffix = "Spacewar" if target == "480" else "SLSonline"
            comment = f"{name} -> {suffix}" if name else ""
            editor.add_fake_app_id(app_id, target, comment=comment)
        else:
            editor.remove_fake_app_id(app_id)
    if not editor.committed_successfully:
        return {"ok": False, "error": "Failed to write config"}
    return {"ok": True, "fake_appid": fake_appid}

def is_global_slsonline_enabled() -> bool:
    """Return True if 0: 480 is mapped in FakeAppIds."""
    return get_fake_appid("0") == "480"

def set_global_slsonline(enabled: bool) -> dict:
    """Toggle global SLSonline (mapping AppID 0 to Spacewar 480 for all games)."""
    if enabled:
        res = set_fake_appid("0", "480", game_name="Global")
    else:
        res = set_fake_appid("0", "", game_name="")
    _signal_sls_api("RELOAD")
    return {"ok": res.get("ok", False), "enabled": enabled}

# --- LaunchOptions (NetSock) --------------------------------------------------
def _netsock_tools_dir() -> Path:
    return _sls_config_dir() / "tools" / "netsock"

def _find_existing_netsock_so() -> Path | None:
    home = _user_home()
    cands = [
        _sls_config_dir() / "tools" / "netsock" / "netsock.so",
        home / ".config/SLSsteam/tools/netsock/netsock.so",
        home / ".local/share/SLSsteam/tools/netsock/netsock.so",
        home / ".var/app/com.valvesoftware.Steam/.config/SLSsteam/tools/netsock/netsock.so",
    ]
    for c in cands:
        try:
            if c.is_file() and c.stat().st_size > 0:
                return c
        except OSError:
            continue
    return None

def _netsock_launch_path() -> str:
    """Path as it must appear inside Steam launch options (Steam runtime view)."""
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    if xdg and Path(xdg).is_absolute():
        return str(Path(xdg) / "SLSsteam" / "tools" / "netsock" / "netsock.so")
    return str(Path.home() / ".config" / "SLSsteam" / "tools" / "netsock" / "netsock.so")

def ensure_netsock_binary() -> bool:
    """Ensure netsock.so exists, downloading fix.so if missing."""
    target_dir = _netsock_tools_dir()
    target_so = target_dir / "netsock.so"
    existing = _find_existing_netsock_so()
    if existing:
        if existing != target_so:
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(existing, target_so)
                os.chmod(target_so, 0o755)
            except Exception as e:
                logger.warning("Could not copy netsock.so: %s", e)
        return True
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        resp = requests.get(_NETSOCK_URL, timeout=30)
        if not resp.ok or not resp.content:
            return False
        target_so.write_bytes(resp.content)
        os.chmod(target_so, 0o755)
        # Mirror to the native config dir so Flatpak/host both resolve it.
        native = Path.home() / ".config" / "SLSsteam" / "tools" / "netsock" / "netsock.so"
        if native != target_so and not native.exists():
            try:
                native.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target_so, native)
                os.chmod(native, 0o755)
            except Exception:
                pass
        logger.info("Downloaded netsock.so (%d bytes)", len(resp.content))
        return True
    except Exception as e:
        logger.error("Failed to download netsock.so: %s", e)
        return False

def get_launch_option(app_id: str) -> str:
    cfg = _find_sls_config()
    if not cfg or not cfg.exists():
        return ""
    try:
        content = cfg.read_text(encoding="utf-8", errors="replace")
        bounds = _get_section_bounds(content, "LaunchOptions")
        if not bounds:
            return ""
        sec = content[bounds[1]:bounds[2]]
        m = re.search(rf"^[ \t]*['\"]?{re.escape(app_id)}['\"]?[ \t]*:[ \t]*(.+)$", sec, re.MULTILINE)
        return m.group(1).strip() if m else ""
    except Exception:
        return ""

def is_netsock_active(app_id: str) -> bool:
    opt = get_launch_option(app_id)
    return bool(opt and "netsock.so" in opt)

def set_netsock(app_id: str, enabled: bool) -> dict:
    """Toggle the NetSock LaunchOptions entry."""
    cfg = _find_sls_config()
    if cfg is None:
        return {"ok": False, "error": "SLSsteam config not found"}
    app_id = _sanitize_id(app_id)
    if not app_id:
        return {"ok": False, "error": "Invalid AppID"}

    with _batch_config_edit() as editor:
        if enabled:
            if not ensure_netsock_binary():
                return {"ok": False, "error": "Could not obtain netsock.so"}
            launch_path = _netsock_launch_path()
            # Same shape ASSella writes: quoted, with escaped inner quotes.
            cmd = f'"env LD_AUDIT=\\"{launch_path}\\" %command%"'
            editor._apply(*_upsert_in_memory(editor.content, "LaunchOptions", app_id, value=cmd))
        else:
            editor.remove_launch_option(app_id)
    if not editor.committed_successfully:
        return {"ok": False, "error": "Failed to write config"}
    return {"ok": True, "enabled": enabled}

# --- EOS Proxy (filesystem DLL swap) ------------------------------------------
def _eos_proxy_dll() -> Path | None:
    """Locate (or download) the EOS proxy DLL."""
    deps = _accela_base_path() / "deps" / "EOSSDK-Win64-Shipping.dll"
    if deps.is_file():
        return deps
    try:
        deps.parent.mkdir(parents=True, exist_ok=True)
        resp = requests.get(_EOS_PROXY_URL, timeout=30)
        if resp.ok and resp.content:
            deps.write_bytes(resp.content)
            return deps
    except Exception as e:
        logger.error("Failed to fetch EOS proxy DLL: %s", e)
    return None

def _file_sha256(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""

def _find_eos_dlls(game_dir: Path, max_depth: int = 4) -> list[Path]:
    found: list[Path] = []
    if not game_dir.is_dir():
        return found
    base_depth = len(game_dir.parts)
    for root, dirs, files in os.walk(game_dir):
        if len(Path(root).parts) - base_depth >= max_depth:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d.lower() not in _EOS_PRUNE_DIRS and not d.startswith(".")]
        for f in files:
            if f.lower() in (_EOS_DLL, _EOS_YES):
                found.append(Path(root) / f)
    return found

def eos_proxy_status(game_dir: Path) -> str:
    """none | inactive | stale | active — mirrors ASSella's EOSDetector."""
    dlls = _find_eos_dlls(game_dir)
    if not dlls:
        return "none"
    by_dir: dict[Path, dict[str, Path]] = {}
    for p in dlls:
        slot = "yes" if p.suffix.lower() == ".yes" else "dll"
        by_dir.setdefault(p.parent, {})[slot] = p
    if not any("yes" in v for v in by_dir.values()):
        return "inactive" if any("dll" in v for v in by_dir.values()) else "none"
    proxy = _eos_proxy_dll()
    proxy_hash = _file_sha256(proxy) if proxy else ""
    for parent, slots in by_dir.items():
        if "yes" in slots:
            dll = slots.get("dll")
            if not dll or not dll.exists():
                return "stale"
            if proxy_hash and _file_sha256(dll) != proxy_hash:
                return "stale"
    return "active"

def apply_eos_proxy(game_dir: Path) -> bool:
    proxy = _eos_proxy_dll()
    if not proxy or not game_dir.is_dir():
        return False
    applied = False
    try:
        for root, _dirs, files in os.walk(game_dir):
            if ".DepotDownloader" in Path(root).parts:
                continue
            dll_src = None
            yes_present = None
            for f in files:
                fl = f.lower()
                if fl == _EOS_DLL:
                    dll_src = Path(root) / f
                elif fl == _EOS_YES:
                    yes_present = Path(root) / f
            dll_target = Path(root) / "EOSSDK-Win64-Shipping.dll"
            yes_target = Path(root) / "EOSSDK-Win64-Shipping.yes"
            if dll_src:
                if yes_present and yes_present.exists():
                    try:
                        yes_present.unlink()
                    except OSError:
                        pass
                dll_src.rename(yes_target)
                shutil.copy2(proxy, dll_target)
                applied = True
            elif yes_present and not dll_src:
                shutil.copy2(proxy, dll_target)
                applied = True
    except Exception as e:
        logger.error("apply_eos_proxy failed: %s", e, exc_info=True)
        return False
    return applied

def remove_eos_proxy(game_dir: Path) -> bool:
    if not game_dir.is_dir():
        return False
    removed = False
    try:
        for root, _dirs, files in os.walk(game_dir):
            if ".DepotDownloader" in Path(root).parts:
                continue
            yes_present = None
            dll_present = None
            for f in files:
                fl = f.lower()
                if fl == _EOS_YES:
                    yes_present = Path(root) / f
                elif fl == _EOS_DLL:
                    dll_present = Path(root) / f
            if yes_present:
                if dll_present and dll_present.exists():
                    try:
                        dll_present.unlink()
                    except OSError:
                        pass
                yes_present.rename(Path(root) / "EOSSDK-Win64-Shipping.dll")
                removed = True
    except Exception as e:
        logger.error("remove_eos_proxy failed: %s", e, exc_info=True)
        return False
    return removed

def set_eos_proxy(app_id: str, enabled: bool) -> dict:
    app_id = _sanitize_id(app_id)
    if not app_id:
        return {"ok": False, "error": "Invalid AppID"}
    install = _atom_install_info(app_id)
    game_dir = Path(install.get("install_path") or "")
    if not install.get("installed") or not game_dir.is_dir():
        return {"ok": False, "error": "Game is not installed locally"}
    try:
        if enabled:
            if not apply_eos_proxy(game_dir):
                return {"ok": False, "error": "Could not apply the EOS proxy (no EOS binaries found?)"}
        else:
            if not remove_eos_proxy(game_dir):
                return {"ok": False, "error": "No EOS proxy was applied"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "status": eos_proxy_status(game_dir)}

# ---------------------------------------------------------------------------
# ManifestIds Management
# ---------------------------------------------------------------------------
def get_configured_manifest_ids() -> dict:
    cfg = _find_sls_config()
    if not cfg or not cfg.exists():
        return {"ok": True, "manifest_ids": {}}
    mids = {}
    in_sec = False
    for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        st = line.strip()
        if st == "ManifestIds:":
            in_sec = True
            continue
        if not in_sec:
            continue
        if not line.startswith((" ", "\t")):
            break
        if ":" in st and not st.startswith("#") and not st.startswith("-"):
            did, _, val = st.partition(":")
            if did.strip().isdigit():
                mids[did.strip()] = val.split("#")[0].strip()
    return {"ok": True, "manifest_ids": mids}

def add_manifest_id(depot_id: str, manifest_id: str) -> dict:
    with _batch_config_edit() as editor:
        inserted = editor.add_manifest_id(depot_id, manifest_id)
    return {"ok": editor.committed_successfully, "message": "Updated" if inserted else "Already up to date"}

def _manifest_pin_depots(app_id: str) -> list[str]:
    """Depot IDs for which this app's cached bundle carries manifest files."""
    zip_path = _manifest_zip_path(app_id)
    depots = []
    if zip_path.exists():
        try:
            with zipfile.ZipFile(zip_path) as zf:
                for name in zf.namelist():
                    base = Path(name).name
                    if base.endswith(".manifest") and "_" in base:
                        did = base.split("_")[0]
                        if did.isdigit():
                            depots.append(did)
        except Exception:
            pass
    return depots

def _drop_manifest_pins(depots: list[str]) -> list[str]:
    """Remove ManifestIds entries in one batched write."""
    removed = []
    if not depots:
        return removed
    with _batch_config_edit() as editor:
        for did in depots:
            if editor._apply(*_remove_in_memory(editor.content, "ManifestIds", did, is_list=False)):
                removed.append(did)
    return removed if editor.committed_successfully else []

def remove_manifest_id_pins(app_id: str) -> dict:
    app_id = str(app_id)
    removed_pins = _drop_manifest_pins(_manifest_pin_depots(app_id))
    return {"ok": True, "app_id": app_id, "removed_pins": removed_pins}

def remove_manifests(app_id: str) -> dict:
    app_id = str(app_id)
    zip_path = _manifest_zip_path(app_id)
    removed_files = []
    depotcache = _depotcache_dir()

    # Collect the pin list BEFORE deleting the bundle, otherwise there is
    # nothing left to read and the pins would silently be orphaned.
    pinned_depots = _manifest_pin_depots(app_id)

    if zip_path.exists():
        try:
            with zipfile.ZipFile(zip_path) as zf:
                for name in zf.namelist():
                    base = Path(name).name
                    if base.endswith(".manifest") and depotcache:
                        target = depotcache / base
                        if target.exists():
                            target.unlink(missing_ok=True)
                            removed_files.append(base)
            zip_path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Error removing manifest for {app_id}: {e}")

    removed_pins = _drop_manifest_pins(pinned_depots)
    return {
        "ok": True,
        "app_id": app_id,
        "removed_files": removed_files,
        "removed_pins": removed_pins,
    }

# ---------------------------------------------------------------------------
# Lua manifest parsing (mirrors ASSella utils/lua_parsing.py)
#
# Hubcap's Lua mixes live statements with commented-out ones. Commented entries
# are how the generator disables depots it cannot serve:
#
#     -- addappid(5136471, 1, "MISSING_KEY") -- no key available
#     -- addappid(1042553)                   -- empty depot
#
# A naive finditer matches those too, which injects dead depots into
# AdditionalApps/AdditionalDepots and (worse) treats a keyless `addappid(<id>)`
# as a license-only DLC. Every scan here is therefore comment-aware.
# ---------------------------------------------------------------------------
MISSING_KEY_SENTINEL = "MISSING_KEY"
_PLACEHOLDER_KEYS = {MISSING_KEY_SENTINEL, "", "0", "NULL", "NONE", "UNKNOWN"}
_DEPOT_ID_RE = re.compile(r"^[0-9]{1,12}$")
_MANIFEST_GID_RE = re.compile(r"^[0-9]{1,24}$")

def _lua_comment_spans(content: str) -> list[tuple[int, int]]:
    """(start, end) index pairs for every Lua `--` line comment.

    String-aware, so a `--` inside a quoted key is not treated as a comment.
    """
    spans = []
    length = len(content)
    index = 0
    quote = None
    while index < length:
        char = content[index]
        if quote is not None:
            if char == "\\" and quote == '"':
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char == "-" and content.startswith("--", index):
            end = content.find("\n", index)
            if end == -1:
                end = length
            spans.append((index, end))
            index = end
            continue
        index += 1
    return spans

def _iter_live_matches(content: str, pattern: re.Pattern, flags: int = 0):
    """Yield matches that are NOT inside a Lua line comment."""
    spans = _lua_comment_spans(content)
    if not spans:
        yield from re.finditer(pattern, content, flags)
        return
    starts = [s for s, _ in spans]
    for match in re.finditer(pattern, content, flags):
        pos = match.start()
        slot = bisect.bisect_right(starts, pos) - 1
        if slot >= 0 and pos < spans[slot][1]:
            continue
        yield match

def _is_placeholder_key(value: str) -> bool:
    """True when a generator sentinel was used instead of a real AES key."""
    text = str(value).strip().strip("\"'")
    if not text:
        return True
    return text.upper() in _PLACEHOLDER_KEYS

def _coerce_depot_id(value) -> str | None:
    """Clean numeric AppID/DepotID, or None. Guards against path injection.

    Remote Lua identifiers get interpolated into depotcache filenames and config
    values, so anything non-numeric is rejected here.
    """
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text if _DEPOT_ID_RE.match(text) else None

def _coerce_manifest_gid(value) -> str | None:
    text = str(value).strip() if isinstance(value, (str, int)) else ""
    return text if _MANIFEST_GID_RE.match(text) else None

_LIVE_APPID_RE = re.compile(
    r'addappid\(\s*(\d+)\s*(?:,\s*(\d+))?(?:\s*,\s*["\']([^"\']*)["\'])?\s*\)(.*)',
    re.IGNORECASE,
)
_LIVE_SETMANIFEST_RE = re.compile(r'setManifestid\(\s*(\d+)\s*,\s*["\']([^"\']+)["\']', re.IGNORECASE)

def _parse_lua_manifest(lua_text: str) -> dict:
    """Parse a Hubcap Lua into {appid, name, app_key, keys, dlcs, manifests, depots}.

    Mirrors ASSella's `ProcessZipTask._parse_lua` semantics:
      - only live (non-commented) addappid() statements count
      - the FIRST live addappid is the main application (its 3rd arg is the AppKey)
      - an addappid with no key is a DLC (license-only), not a depot
      - MISSING_KEY / placeholder values are never treated as keys
    """
    result = {
        "appid": None,
        "name": None,
        "app_key": None,
        "keys": {},
        "dlcs": [],
        "manifests": {},
        "depots": [],
    }
    if not lua_text:
        return result

    first = True
    for m in _iter_live_matches(lua_text, _LIVE_APPID_RE):
        did = _coerce_depot_id(m.group(1))
        if not did:
            continue
        key = (m.group(3) or "").strip()
        tail = m.group(4) or ""

        if first:
            first = False
            result["appid"] = did
            gm = re.search(r"--\s*(.*)", tail)
            if gm and gm.group(1).strip():
                result["name"] = gm.group(1).strip()
            if key and not _is_placeholder_key(key):
                result["app_key"] = key
                result["keys"][did] = key
                result["depots"].append(did)
            continue

        if key and not _is_placeholder_key(key):
            # A real depot with a usable key.
            clean = _sanitize_key(key)
            if clean:
                result["keys"][did] = clean
                result["depots"].append(did)
                continue
        if not key:
            # No key argument => license-only DLC entry.
            result["dlcs"].append(did)

    for m in _iter_live_matches(lua_text, _LIVE_SETMANIFEST_RE):
        did = _coerce_depot_id(m.group(1))
        gid = _coerce_manifest_gid(m.group(2))
        if did and gid:
            result["manifests"][did] = gid

    return result

def _harvest_depot_names(lua_text: str) -> int:
    """Cache depot descriptions from live setManifestid/addappid comments."""
    found = 0
    for m in _iter_live_matches(lua_text, _LIVE_APPID_RE):
        did = _coerce_depot_id(m.group(1))
        if not did:
            continue
        tail = (m.group(4) or "").strip()
        if not tail:
            continue
        gm = re.search(r"--\s*(.*)", tail)
        label = (gm.group(1).strip() if gm else "").strip()
        if not label:
            continue
        # Hubcap writes either "-- <Name> - Depot <id>" or "-- Depot <id>".
        label = re.sub(r"\s*-\s*Depot\s*\d+\s*$", "", label).strip()
        if label and label.lower() != "depot":
            _depot_name_cache[did] = label
            found += 1
    return found

# ---------------------------------------------------------------------------
# Hubcap API Engine (Direct Manifest & Depot Decryption Keys Fetching)
#
# BASE_URL is fixed to ASSella's endpoint (core/morrenus_api.py BASE_URL); the
# user-configurable URL is intentionally gone so both tools always target the
# same service with the same key.
# ---------------------------------------------------------------------------
HUBCAP_BASE_URL = "https://hubcapmanifest.com/api/v1"

def _hubcap_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}

def hubcap_manifest_contents(app_id: str) -> dict:
    """GET /manifest/{app_id}/contents — free (zero quota) bundle preflight.

    Mirrors ASSella's `get_manifest_contents`. Used as a guard so we can tell
    "Hubcap has no bundle for this app" apart from "your key is wrong" before
    spending a bundle download.
    """
    app_id = str(app_id).strip()
    api_key = _detect_assella_canary_hubcap_key()
    if not api_key:
        return {"error": "Hubcap API key is not set in ACCELA settings"}
    try:
        resp = requests.get(
            f"{HUBCAP_BASE_URL}/manifest/{app_id}/contents",
            headers=_hubcap_headers(api_key),
            timeout=15,
        )
        if resp.status_code == 401:
            return {"error": "Invalid Hubcap API key (HTTP 401)"}
        if resp.status_code == 404:
            return {"zip_exists": False, "manifest_count": 0, "manifests": []}
        if resp.status_code == 429:
            return {"error": "Hubcap rate limit reached (HTTP 429)"}
        if not resp.ok:
            return {"error": f"Hubcap API HTTP {resp.status_code}"}
        data = resp.json()
        manifests = data.get("manifests") or []
        data["manifests"] = manifests
        data["manifest_count"] = data.get("manifest_count", len(manifests))
        data["manifest_map"] = {
            str(m.get("depot_id")): str(m.get("manifest_id"))
            for m in manifests
            if isinstance(m, dict) and m.get("depot_id")
        }
        return data
    except Exception as e:
        return {"error": f"Hubcap preflight failed: {e}"}

def fetch_manifests(app_id: str, persist_config: bool = True) -> dict:
    """Download the Hubcap manifest bundle and harvest depot keys.

    By default the harvested keys/pins are persisted in one batched pass. Pass
    ``persist_config=False`` when the caller wants to fold them into a larger
    atomic write (e.g. game injection).
    """
    app_id = str(app_id).strip()
    api_key = _detect_assella_canary_hubcap_key()

    if not api_key:
        return {"ok": False, "app_id": app_id, "error": "Hubcap API key is not configured"}

    headers = _hubcap_headers(api_key)

    data = None
    # ASSella tries force_update first, then transparently retries the standard
    # endpoint. Mirror that so a server-side refresh error is not fatal.
    last_error = None
    for force in (True, False):
        url = f"{HUBCAP_BASE_URL}/manifest/{app_id}"
        if force:
            url += "?force_update=true"
        logger.info(f"Hubcap: fetching bundle for AppID {app_id} from {url}")
        try:
            resp = requests.get(url, headers=headers, timeout=60)
        except Exception as e:
            last_error = f"Hubcap download failed: {e}"
            continue

        if resp.status_code == 401:
            return {"ok": False, "app_id": app_id, "error": "Invalid Hubcap API key (HTTP 401)"}
        if resp.status_code == 404:
            return {"ok": False, "app_id": app_id,
                    "error": f"No Hubcap bundle available for {app_id}"}
        if resp.status_code == 429:
            return {"ok": False, "app_id": app_id,
                    "error": "Hubcap API daily rate limit exceeded (HTTP 429)"}
        if not resp.ok:
            last_error = f"Hubcap API HTTP {resp.status_code}"
            continue

        data = resp.content
        break

    if data is None:
        return {"ok": False, "app_id": app_id,
                "error": last_error or "Hubcap download failed"}

    depotcache = _depotcache_dir()
    if depotcache is not None:
        try:
            depotcache.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("Could not create depotcache %s: %s", depotcache, e)
            depotcache = None
    zip_path = _manifest_zip_path(app_id)
    try:
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        zip_path.write_bytes(data)
    except OSError as e:
        logger.warning("Could not cache Hubcap bundle to %s: %s", zip_path, e)

    extracted_manifests = []
    written_count = 0
    depot_keys: dict[str, str] = {}
    manifest_ids: dict[str, str] = {}
    pinned_manifests: dict[str, str] = {}
    dlc_appids: list[str] = []
    game_name = ""
    should_pin = bool(_get_setting("manifestid_pinning"))

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                base = Path(name).name
                if base.endswith(".manifest"):
                    # Sanitize before this name becomes a depotcache path.
                    stem = base[:-len(".manifest")]
                    parts = stem.split("_", 1)
                    did = _coerce_depot_id(parts[0]) if len(parts) == 2 else None
                    mid = _coerce_manifest_gid(parts[1]) if len(parts) == 2 else None
                    if not (did and mid):
                        logger.warning("Skipping malformed manifest name: %s", base)
                        continue
                    extracted_manifests.append(base)
                    # Write to depotcache
                    if depotcache:
                        dst = depotcache / base
                        try:
                            dst.write_bytes(zf.read(name))
                            written_count += 1
                        except OSError as e:
                            logger.warning(f"Failed writing manifest {base}: {e}")
                    manifest_ids[did] = mid
                    if should_pin:
                        pinned_manifests[did] = mid
                elif base.endswith(".lua"):
                    try:
                        lua_content = zf.read(name).decode("utf-8", errors="replace")
                        _harvest_depot_names(lua_content)
                        parsed = _parse_lua_manifest(lua_content)
                        depot_keys.update(parsed["keys"])
                        manifest_ids.update(parsed["manifests"])
                        for d in parsed["manifests"]:
                            if should_pin:
                                pinned_manifests.setdefault(d, parsed["manifests"][d])
                        for d in parsed["dlcs"]:
                            if d not in dlc_appids:
                                dlc_appids.append(d)
                        if parsed.get("name"):
                            game_name = parsed["name"]
                    except Exception as e:
                        logger.warning(f"Error parsing .lua in bundle: {e}")
    except zipfile.BadZipFile:
        return {"ok": False, "app_id": app_id, "error": "Invalid zip file returned by Hubcap"}

    # Guard: a bundle with no usable keys cannot drive an AT0M injection.
    # Registering depots without keys makes Steam fail with DepotWithoutKey,
    # so refuse rather than write a config that cannot download.
    if not depot_keys:
        return {
            "ok": False,
            "app_id": app_id,
            "error": "Hubcap bundle contains no depot decryption keys",
        }

    # Keys/manifest pins are written by the caller in a single batched pass, so
    # that one inject never rewrites the config once per depot.
    if persist_config:
        _persist_manifest_keys(app_id, depot_keys, pinned_manifests)

    logger.info(
        f"Hubcap: AppID {app_id} processed. Manifests: {written_count}, Keys harvested: {len(depot_keys)}"
    )

    return {
        "ok": True,
        "app_id": app_id,
        "manifests": extracted_manifests,
        "written": written_count,
        "depot_keys": depot_keys,
        "manifest_ids": manifest_ids,
        "pinned_manifests": pinned_manifests,
        "dlc_appids": dlc_appids,
        "game_name": game_name,
        # Back-compat: callers still read `keys_added` as a list of depot ids.
        "keys_added": sorted(depot_keys.keys(), key=lambda x: int(x) if x.isdigit() else 0),
    }

def _persist_manifest_keys(app_id: str, depot_keys: dict, manifest_ids: dict) -> dict:
    """Write harvested depot keys + manifest pins in one batched pass."""
    app_id = str(app_id).strip()
    name = f"App {app_id}"
    try:
        details = get_app_details(app_id)
        name = _sanitize_comment(details.get("name") or name)
    except Exception:
        name = "App " + app_id

    with _batch_config_edit() as editor:
        editor.content = _ensure_plugins_enabled(editor.content)
        editor.has_changes = True
        for did, key in (depot_keys or {}).items():
            editor.add_key(did, key, comment=_depot_name_cache.get(did, ""))
        for did, mid in (manifest_ids or {}).items():
            editor.add_manifest_id(did, mid)
    return {"ok": editor.committed_successfully, "keys": list((depot_keys or {}).keys())}

def refetch_manifests(app_id: str) -> dict:
    remove_manifest_id_pins(app_id)
    return fetch_manifests(app_id)


# ---------------------------------------------------------------------------
# Steam API & Game Details
# ---------------------------------------------------------------------------
def _fetch_store_details(app_id: str) -> dict:
    cached = _store_details_cache.get(app_id)
    if cached and time.time() - cached["fetchedAt"] < 300:
        return cached["data"]
    try:
        url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=english&cc=US"
        resp = requests.get(url, timeout=10)
        if resp.ok:
            data = resp.json().get(app_id, {}).get("data", {})
            _store_details_cache[app_id] = {"data": data, "fetchedAt": time.time()}
            return data
    except Exception as e:
        logger.debug(f"Store details failed for {app_id}: {e}")
    return {}

def _fetch_steamcmd_details(app_id: str) -> dict:
    cached = _steamcmd_details_cache.get(app_id)
    if cached and time.time() - cached["fetchedAt"] < 3600:
        return cached["data"]
    try:
        url = f"https://api.steamcmd.net/v1/info/{app_id}"
        resp = requests.get(url, timeout=10)
        if resp.ok:
            data = resp.json().get("data", {}).get(app_id, {})
            _steamcmd_details_cache[app_id] = {"data": data, "fetchedAt": time.time()}
            return data
    except Exception as e:
        logger.debug(f"SteamCMD details failed for {app_id}: {e}")
    return {}

def get_app_details(app_id: str) -> dict:
    store = _fetch_store_details(app_id)
    cmd = _fetch_steamcmd_details(app_id)
    packages = []
    depots = []

    # Store packages
    for pkg in store.get("packages", []):
        packages.append(str(pkg))

    # SteamCMD depots
    depot_dict = cmd.get("depots", {})
    if isinstance(depot_dict, dict):
        for k in depot_dict.keys():
            if k.isdigit():
                depots.append(k)

    return {
        "app_id": app_id,
        "name": store.get("name", cmd.get("common", {}).get("name", f"App {app_id}")),
        "packages": list(set(packages)),
        "depots": list(set(depots)),
        "dlc": [str(d) for d in store.get("dlc", [])],
    }

# ---------------------------------------------------------------------------
# Game Search
# ---------------------------------------------------------------------------
def search_games(query: str, limit: int = 20, appid: bool = False) -> dict:
    q = query.strip()
    if not q:
        return {"results": []}

    results = []
    if appid or q.isdigit():
        details = _fetch_store_details(q)
        name = details.get("name")
        if not name:
            cmd = _fetch_steamcmd_details(q)
            name = cmd.get("common", {}).get("name")
        if name:
            results.append({"app_id": q, "title": name})

    # Store search
    try:
        url = "https://store.steampowered.com/api/storesearch/"
        resp = requests.get(url, params={"term": q, "l": "english", "cc": "US"}, timeout=10)
        if resp.ok:
            for item in resp.json().get("items", []):
                aid = str(item.get("id"))
                if not any(r["app_id"] == aid for r in results):
                    results.append({
                        "app_id": aid,
                        "title": item.get("name", f"App {aid}"),
                    })
    except Exception as e:
        logger.error(f"Search API error: {e}")

    return {"results": results[:limit]}

# ---------------------------------------------------------------------------
# DLC Fetching via Hubcap
# ---------------------------------------------------------------------------
def fetch_dlcs_for_app(app_id: str) -> dict:
    """Register a game's DLC AppIDs in AdditionalApps, in a single batched write.

    DLCs are added as AdditionalApps entries only — never AdditionalDepots.
    ASSella permits a DLC AppID in AdditionalDepots (Steam stores DLC as
    appid==depotid), but mixing them in here would also drag in unrelated
    depots, so we keep DLC handling to AdditionalApps.
    """
    details = get_app_details(app_id)
    dlc_ids = [_sanitize_id(d) for d in details.get("dlc", [])]
    dlc_ids = [d for d in dlc_ids if d]
    if not dlc_ids:
        return {"ok": True, "count": 0, "message": "No DLCs found"}

    if _find_sls_config() is None:
        return {"ok": False, "error": "SLSsteam config not found"}

    game_name = _sanitize_comment(details.get("name") or f"App {app_id}")

    # Harvest from the Hubcap bundle of the base game (it usually carries DLC keys).
    # persist_config=False: we write everything in one pass below.
    manifest_res = fetch_manifests(app_id, persist_config=False)
    depot_keys = manifest_res.get("depot_keys", {}) if manifest_res.get("ok") else {}
    if not manifest_res.get("ok"):
        logger.warning("DLC fetch for %s: no Hubcap bundle (%s)", app_id, manifest_res.get("error"))

    keys_added = []
    with _batch_config_edit() as editor:
        editor.content = _ensure_plugins_enabled(editor.content)
        editor.has_changes = True
        for dlc_id in dlc_ids:
            editor.add_app(dlc_id, comment=f"{game_name} DLC ({dlc_id})")
        for did, key in (depot_keys or {}).items():
            if editor.add_key(did, key, comment=_depot_name_cache.get(did, "")):
                keys_added.append(did)

    if not editor.committed_successfully:
        return {"ok": False, "error": "Failed to write SLSsteam config"}

    return {
        "ok": True,
        "count": len(dlc_ids),
        "dlc_ids": dlc_ids,
        "apps_added": dlc_ids,
        "depots_added": [],
        "keys_added": sorted(keys_added, key=lambda x: int(x) if x.isdigit() else 0),
    }

# ---------------------------------------------------------------------------
# Game Injection Engine
# ---------------------------------------------------------------------------
def _inject_sls_config(
    app_id: str,
    name: str,
    depot_keys: dict,
    manifest_ids: dict | None = None,
    dlc_appids: set | None = None,
    candidate_depots: set | None = None,
) -> dict:
    """Inject one game into SLSsteam config.yaml in a SINGLE atomic pass.

    Mirrors ASSella's `_patch_config` (NativeSteamDownloadTask) semantics:

      1. Plugins: yes              (required by the library-inject plugin loader)
      2. AdditionalApps:           `  - {appid} # {game_name}`
      3. AdditionalDepots:         `  - {depot} # {game} [{desc}] ({appid})`, rebuilt
                                   sorted, ONLY depots that have keys (or are
                                   shared redists). Never an AppID.
      4. DecryptionKeys:           `  {depot}: {key} # ...`, rebuilt sorted. The root
                                   AppKey IS allowed here and is tagged `[AppKey]`.
      5. SmartTickets: 0x1

    Only depots that actually have a decryption key are registered: Steam fails
    the download with DepotWithoutKey otherwise. DLC AppIDs are excluded from
    AdditionalDepots/DecryptionKeys so they don't clobber the parent game's data.
    """
    app_id = _sanitize_id(app_id)
    if not app_id:
        return {"ok": False, "error": "Invalid AppID"}

    cfg = _find_sls_config()
    if cfg is None:
        return {"ok": False, "error": "SLSsteam config not found"}

    # Guard: refuse to register a game with no usable keys. Without an AppKey
    # Steam cannot download the game at all, and depots without keys abort the
    # download with DepotWithoutKey — a half-registered game is worse than none.
    if not depot_keys:
        return {
            "ok": False,
            "error": "No depot decryption keys available for this game — cannot register it.",
            "reason": "no_keys",
        }

    game_name = _sanitize_comment(name) or f"App {app_id}"
    dlc_appids = {d for d in (_sanitize_id(x) for x in (dlc_appids or ())) if d}

    content = cfg.read_text(encoding="utf-8", errors="ignore") if cfg.exists() else "Plugins: yes\nAdditionalApps:\n"

    # 1. Plugins: yes
    content = _ensure_plugins_enabled(content)

    # 2. AdditionalApps
    content, _ = _upsert_in_memory(content, "AdditionalApps", app_id, comment=game_name)

    # 3. AdditionalDepots — rebuild sorted, keyed/shared only, never an AppID.
    # Candidates are the depots we know belong to this game: any depot we hold a
    # key for, plus any shared redistributable the game actually reported. We
    # never blanket-add the whole SHARED_REDISTS set — that would claim every
    # shared depot in existence and take ownership of them on cleanup.
    # Sanitize: only well-formed 64-hex AES keys are ever written.
    keyed = {}
    for raw_id, raw_key in (depot_keys or {}).items():
        clean_id = _sanitize_id(raw_id)
        clean_key = _sanitize_key(raw_key)
        if clean_id and clean_key:
            keyed[clean_id] = clean_key
        elif raw_key:
            logger.warning("Skipping malformed key for %s", raw_id)
    candidates = set(keyed)
    candidates |= {d for d in (_sanitize_id(x) for x in (candidate_depots or ())) if d and d in SHARED_REDISTS}
    depot_ids = [
        d for d in _sort_ids(candidates)
        if d != app_id and d not in dlc_appids and (d in SHARED_REDISTS or d in keyed)
    ]

    existing_depot_comments = {
        d: cm for d, cm in _parse_list_section(content, "AdditionalDepots").items()
        # never keep base AppIDs in AdditionalDepots
        if d != app_id and d not in dlc_appids
    }
    for d in depot_ids:
        if d in SHARED_REDISTS:
            # Magic marker: marks these exempt from uninstall cleanup.
            existing_depot_comments[d] = SHARED_COMMENT
        else:
            desc = _sanitize_comment(_depot_name_cache.get(d, ""))
            existing_depot_comments[d] = f"{game_name} [{desc}] ({app_id})" if desc else f"{game_name} ({app_id})"

    content = _replace_section_block(content, "AdditionalDepots", [
        f"  - {d} # {existing_depot_comments[d]}" if existing_depot_comments.get(d) else f"  - {d}"
        for d in _sort_ids(existing_depot_comments)
    ])

    # 4. DecryptionKeys — merge into existing, sorted, DLC AppIDs excluded.
    all_keys, key_comments = _parse_key_section(content, "DecryptionKeys")
    for d in dlc_appids:
        all_keys.pop(d, None)
        key_comments.pop(d, None)
    for d, k in keyed.items():
        # A DLC AppID is stored as appid==depotid in AdditionalApps, so writing
        # it into DecryptionKeys here would claim ownership of another game's
        # data. ASSella excludes these for the same reason.
        if d in dlc_appids:
            continue
        all_keys[d] = k
        if d in SHARED_REDISTS:
            key_comments[d] = SHARED_COMMENT
        elif d == app_id:
            # The root AppKey is legitimate here (unlike AdditionalDepots).
            key_comments[d] = f"{game_name} [AppKey] ({app_id})"
        else:
            desc = _sanitize_comment(_depot_name_cache.get(d, ""))
            key_comments[d] = f"{game_name} [{desc}] ({app_id})" if desc else game_name

    content = _replace_section_block(content, "DecryptionKeys", [
        f"  {d}: {all_keys[d]} # {key_comments[d]}" if key_comments.get(d) else f"  {d}: {all_keys[d]}"
        for d in _sort_ids(all_keys)
    ])

    # 5. SmartTickets
    content = _ensure_smart_tickets(content)

    # Optional manifest pinning (append, preserving the section as-is).
    if manifest_ids:
        for did, mid in (manifest_ids or {}).items():
            if _sanitize_id(did) and _sanitize_id(mid):
                content, _ = _upsert_in_memory(content, "ManifestIds", did, value=str(mid))

    if not _write_sls_config(cfg, content):
        return {"ok": False, "error": "Failed to write SLSsteam config"}

    logger.info(
        "Injected %s (%s): %d depot(s), %d key(s) in a single pass",
        game_name, app_id, len(depot_ids), len(keyed),
    )
    return {
        "ok": True,
        "app_id": app_id,
        "name": game_name,
        "depots_added": depot_ids,
        "keys_added": sorted(keyed, key=lambda x: int(x) if x.isdigit() else 0),
    }

def _merge_existing_keys(app_id: str, depot_keys: dict, candidate_depots: set) -> dict:
    """Top up `depot_keys` from keys already present in config.yaml.

    Scoped deliberately: only depots that are already attributed to THIS game
    (by name/appid in their ownership comment) or that are among its known
    depots are reused. Merging every key in the config would register other
    games' depots under this game and break cleanup on both sides.
    """
    cfg = _find_sls_config()
    if cfg is None or not cfg.exists():
        return depot_keys
    try:
        content = cfg.read_text(encoding="utf-8", errors="replace")
        keys, _ = _parse_key_section(content, "DecryptionKeys")
        depots_cm = _parse_list_section(content, "AdditionalDepots")

        owned = set()
        for did, cm in depots_cm.items():
            low = (cm or "").lower()
            if app_id in low:
                owned.add(did)
        owned |= {d for d in candidate_depots if d}

        for did, key in keys.items():
            if did in depot_keys or did not in owned:
                continue
            clean = _sanitize_key(key)
            if clean:
                depot_keys[did] = clean
    except Exception as e:
        logger.debug("Could not merge existing depot keys: %s", e)
    return depot_keys

def _background_inject_worker(app_id: str, name: str, dlc_appids: set | None = None, candidate_depots: set | None = None) -> None:
    status_entry = _inject_status.get(app_id, {})
    status_entry["running"] = True

    try:
        # 1. Harvest local depot keys from local SQLite database FIRST
        local_keys = _get_local_depot_keys(app_id, candidate_depots)
        if local_keys:
            logger.info("Local DB: Found %d cached depot key(s) in depot_keys.db for AppID %s prior to Hubcap inquiry", len(local_keys), app_id)

        # 2. Harvest Hubcap manifest bundle + depot keys WITHOUT writing config,
        #    so the whole inject lands as one atomic write below.
        manifest_res = fetch_manifests(app_id, persist_config=False)
        depot_keys = dict(local_keys)
        manifest_ids = {}
        resolved_dlcs = set(dlc_appids or ())
        resolved_name = name

        if manifest_res.get("ok"):
            hubcap_keys = dict(manifest_res.get("depot_keys", {}))
            depot_keys.update(hubcap_keys)
            if hubcap_keys:
                _save_local_depot_keys(app_id, hubcap_keys)
            status_entry["depot_keys"] = sorted(list(depot_keys.keys()), key=lambda x: int(x) if x.isdigit() else 0)
            status_entry["manifests"] = manifest_res.get("manifests", [])
            if _get_setting("manifestid_pinning"):
                manifest_ids = manifest_res.get("pinned_manifests", {})
            # The Lua carries the authoritative game name and DLC list.
            if manifest_res.get("game_name"):
                resolved_name = manifest_res["game_name"]
            resolved_dlcs |= {d for d in (manifest_res.get("dlc_appids") or []) if d}
        else:
            if local_keys:
                logger.info("Hubcap inquiry failed (%s), but proceeding with %d cached keys from local depot_keys.db", manifest_res.get("error"), len(local_keys))
                status_entry["depot_keys"] = sorted(list(depot_keys.keys()), key=lambda x: int(x) if x.isdigit() else 0)
            else:
                status_entry["manifest_error"] = manifest_res.get("error")

        # 3. Top up from keys already in config, scoped to this game.
        depot_keys = _merge_existing_keys(app_id, depot_keys, candidate_depots or set())

        # 3. Single atomic config write (Apps + Depots + Keys + SmartTickets).
        result = _inject_sls_config(app_id, resolved_name, depot_keys, manifest_ids, resolved_dlcs, candidate_depots)
        if not result.get("ok"):
            status_entry["error"] = result.get("error")
            status_entry["blocked"] = result.get("reason")
            logger.warning("Inject blocked for %s: %s", app_id, result.get("error"))
        else:
            status_entry["injected_depots"] = result.get("depots_added", [])
            status_entry["injected_keys"] = result.get("keys_added", [])

            # 4. Register in ACCELA's AT0M library so ASSella manages this game
            #    exactly as if ASSella had injected it itself.
            if _register_plugin_game(
                app_id,
                resolved_name,
                result.get("depots_added", []),
                depot_keys,
                installdir="",
                depot_names={d: _depot_name_cache.get(d, "") for d in result.get("depots_added", [])},
                # This UI injects the base game in normal AT0-M mode. The
                # resolved DLC IDs above are metadata used to keep DLC AppIDs
                # out of AdditionalDepots/DecryptionKeys; they are not a
                # DLC-only registration. ASSella only stores dlc_appids in
                # plugin_library.json for an actual DLC-only download.
                dlc_appids=[],
            ):
                status_entry["registered"] = True
                logger.info("Registered %s (%s) in ACCELA plugin_library.json", resolved_name, app_id)
            else:
                logger.warning("Config injected but plugin_library.json registration failed for %s", app_id)

            # 5. Optional DLC registration (separate, batched write)
            if _get_setting("fetch_dlcs_on_inject"):
                fetch_dlcs_for_app(app_id)

        status_entry["done"] = True
        status_entry["running"] = False
        logger.info(f"Background inject complete for {resolved_name} ({app_id})")
    except Exception as e:
        logger.error(f"Background inject failed for {app_id}: {e}", exc_info=True)
        status_entry["error"] = str(e)
        status_entry["done"] = True
        status_entry["running"] = False

def inject_game(app_id: str) -> dict:
    app_id = str(app_id).strip()
    aid = _sanitize_id(app_id)
    if not aid:
        return {"error": "Invalid AppID"}

    details = get_app_details(aid)
    name = details.get("name", f"App {aid}")
    depots = details.get("depots", [])
    dlc_ids = [_sanitize_id(d) for d in details.get("dlc", [])]

    # Preflight guard 1: check SLS environment
    env = check_sls_environment()
    if not env.get("ok"):
        return {"error": env.get("error", "SLS environment validation failed"), "blocked": env.get("reason")}

    # Preflight guard 2: game already registered
    if is_app_added(aid):
        return {"error": f"{name} is already registered in your library.", "already_added": True}

    # Preflight guard 3: Hubcap key
    if not _detect_assella_canary_hubcap_key():
        return {
            "error": "No Hubcap API key found. Set morrenus_api_key in ASSella "
                     "settings (~/.config/Tachibana Labs/ACCELA.conf) or add an "
                     "override in this plugin's settings.",
            "blocked": "no_api_key",
        }

    # Automatic safety backup
    create_backup("pre_inject")

    # Initialize inject status
    _inject_status[aid] = {
        "done": False,
        "running": True,
        "app_id": aid,
        "name": name,
    }

    # Record recent inject
    recent_entry = {
        "app_id": aid,
        "name": name,
        "depots_resolved": depots,
    }
    _recent_injects.insert(0, recent_entry)
    if len(_recent_injects) > 20:
        _recent_injects.pop()

    # Launch background worker
    threading.Thread(
        target=_background_inject_worker,
        args=(aid, name, set(dlc_ids), set(depots)),
        daemon=True,
    ).start()

    return {
        "name": name,
        "depots": depots,
        "fetching": True,
    }

def get_inject_status(app_id: str) -> dict | None:
    return _inject_status.get(str(app_id))

def get_recent_injects() -> list[dict]:
    # Merge live worker status into the recent list so the UI can show outcome,
    # guard blocks, and whether the game landed in ACCELA's AT0M library.
    out = []
    for entry in _recent_injects:
        merged = dict(entry)
        st = _inject_status.get(str(entry.get("app_id")))
        if st:
            for k in ("done", "running", "error", "blocked", "registered",
                      "depot_keys", "injected_depots", "injected_keys",
                      "manifests", "manifest_error"):
                if k in st:
                    merged[k] = st[k]
        out.append(merged)
    return out

# ---------------------------------------------------------------------------
# Diagnostics & System Helpers
# ---------------------------------------------------------------------------
def why_not_downloading(app_id: str) -> dict:
    app_id = str(app_id)
    cfg = _find_sls_config()
    if not cfg or not cfg.exists():
        return {"ok": False, "message": "SLS config.yaml not found"}
    configured_keys = get_configured_depot_keys().get("keys", {})
    configured_mids = get_configured_manifest_ids().get("manifest_ids", {})
    details = get_app_details(app_id)
    depots = details.get("depots", [])

    missing_keys = [d for d in depots if d not in configured_keys]
    msg = f"App {app_id}: {len(depots)} depot(s)."
    if missing_keys:
        msg += f" {len(missing_keys)} depot(s) lack decryption keys."
    else:
        msg += " All depots have decryption keys."

    return {"ok": True, "message": msg}

def read_clipboard() -> dict:
    """Read clipboard text using wl-paste or xclip."""
    for cmd in [["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"]]:
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=2)
            if res.returncode == 0 and res.stdout:
                return {"ok": True, "text": res.stdout.strip()}
        except Exception:
            continue
    return {"ok": False, "error": "Clipboard unavailable"}

def restart_steam() -> None:
    try:
        subprocess.run(["pkill", "-TERM", "steam"], timeout=5)
    except Exception as e:
        logger.error(f"Restart steam error: {e}")

# Feature services are separate modules; this entrypoint keeps Decky callables stable.
from uran_backend import keycare, sls_config
from uran_backend.guards import GuardService
from uran_backend.plugin_api import Plugin, bind_core
from uran_backend.steam_store import StoreDebugger
from uran_backend.uninstall import AtomUninstallService

_core = sys.modules.get(__name__)
if _core is None:
    import types

    class _CoreProxy(types.ModuleType):
        def __getattr__(self, name):
            if name in globals():
                return globals()[name]
            raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

        def __dir__(self):
            return list(globals().keys())

    _core = _CoreProxy(__name__)
    _core.__dict__.update(globals())
    sys.modules[__name__] = _core
sls_config.bind_core(_core)
_backups_dir = sls_config._backups_dir
create_backup = sls_config.create_backup
list_backups = sls_config.list_backups
restore_backup = sls_config.restore_backup
_sanitize_comment = sls_config._sanitize_comment
_sanitize_id = sls_config._sanitize_id
_sanitize_key = sls_config._sanitize_key
_validate_yaml_content = sls_config._validate_yaml_content
_write_sls_config = sls_config._write_sls_config
_get_section_bounds = sls_config._get_section_bounds
_section_insert_pos = sls_config._section_insert_pos
_upsert_in_memory = sls_config._upsert_in_memory
_remove_in_memory = sls_config._remove_in_memory
_parse_list_section = sls_config._parse_list_section
_parse_key_section = sls_config._parse_key_section
_replace_section_block = sls_config._replace_section_block
_sort_ids = sls_config._sort_ids
_ensure_plugins_enabled = sls_config._ensure_plugins_enabled
_ensure_smart_tickets = sls_config._ensure_smart_tickets
_SlsConfigEditor = sls_config._SlsConfigEditor
_batch_config_edit = sls_config._batch_config_edit

keycare.bind_core(_core)
validate_hubcap_key = keycare.validate_hubcap_key
get_hubcap_user_stats = keycare.get_hubcap_user_stats
save_hubcap_key = keycare.save_hubcap_key
stop_keycare_server = keycare.stop_keycare_server
start_keycare_server = keycare.start_keycare_server
get_keycare_status = keycare.get_keycare_status
get_hubcap_key_status = keycare.get_hubcap_key_status

_store_debugger = StoreDebugger(requests, logger)
_atom_uninstaller = AtomUninstallService(_core)
_guard_service = GuardService(_core)


def check_sls_environment() -> dict:
    return _guard_service.check_sls_environment()


def is_app_added(app_id: str) -> bool:
    return _guard_service.is_app_added(app_id)


def get_added_app_ids() -> list[str]:
    return _guard_service.get_added_app_ids()


def discover_store_tab() -> dict | None:
    return _store_debugger.discover()


def get_store_debug_status(refresh: bool = False) -> dict:
    return _store_debugger.status(refresh)


def preview_atom_uninstall(app_id: str) -> dict:
    return _atom_uninstaller.preview(app_id)


def uninstall_atom_game(app_id: str) -> dict:
    return _atom_uninstaller.uninstall(app_id)


bind_core(_core)

