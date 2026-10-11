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
import socket
import zipfile
import secrets
import threading
import subprocess
import sqlite3
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
    return False, "Could not locate a writable ACCELA.conf."

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

def _detect_assella_canary_hubcap_key() -> str:
    """Read the Hubcap (morrenus) API key from ACCELA's own settings.

    Same source and setting name ASSella uses, so the Decky plugin and ASSella
    always talk to Hubcap with the same key. An explicit override set in the
    plugin's own settings still wins.
    """
    override = _stored_hubcap_key()
    if override:
        return override

    for p in _accela_conf_candidates():
        if not p.is_file():
            continue
        key = _read_ini_value(p, "morrenus_api_key")
        if key:
            logger.info("Auto-detected Hubcap API key from ACCELA config (%s)", p)
            return key
    logger.warning(
        "No morrenus_api_key found in ACCELA config. Open ASSella settings and "
        "set your Hubcap key, or set one in this plugin's settings."
    )
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
# SLSsteam Config Backups
# ---------------------------------------------------------------------------
def _backups_dir() -> Path:
    sls = _find_sls_config()
    if sls:
        d = sls.parent / "backups"
    else:
        d = Path.home() / ".config" / "SLSsteam" / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d

def create_backup(tag: str = "sls") -> str:
    """Create timestamped backup of config.yaml."""
    cfg = _find_sls_config()
    if not cfg or not cfg.exists():
        return "SLSsteam config not found"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"{tag}.{ts}.yaml"
    dest = _backups_dir() / name
    try:
        shutil.copy2(cfg, dest)
        logger.info("Created SLS config backup: %s", name)
        return name
    except Exception as e:
        logger.error("Failed creating backup: %s", e)
        return f"Error: {e}"

def list_backups() -> list[dict]:
    b_dir = _backups_dir()
    if not b_dir.exists():
        return []
    entries = []
    for f in b_dir.glob("*.yaml"):
        if f.is_file():
            stat = f.stat()
            entries.append({
                "name": f.name,
                "stamp": f.stem,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            })
    entries.sort(key=lambda x: x["mtime"], reverse=True)
    return entries

def restore_backup(backup_name: str) -> dict:
    cfg = _find_sls_config()
    if not cfg:
        return {"error": "SLSsteam config not found"}
    src = _backups_dir() / backup_name
    if not src.exists():
        return {"error": f"Backup {backup_name} not found"}
    try:
        # Pre-restore safety snapshot
        create_backup("pre_restore")
        with _sls_write_lock:
            shutil.copy2(src, cfg)
        _signal_slssteam_api("RELOAD")
        return {"success": True, "verified": True}
    except Exception as e:
        return {"error": str(e)}

# ---------------------------------------------------------------------------
# YAML Config Engine (comment-preserving, inode-preserving)
#
# Mirrors ASSella's `utils/yaml/*` so this plugin stays hand-in-hand with it:
#   * PyYAML is never used for writes — comments and key order must survive a
#     round trip, and SLSsteam itself is a hand-rolled parser.
#   * Writes are IN-PLACE (r+ / seek / write / truncate / fsync) rather than
#     tmp+rename. A rename swaps the inode and opens a window where SLSsteam's
#     inotify FileWatcher sees the file disappear.
#   * Entries carry ownership comments (`# Game Name`). These are not
#     decoration: ASSella parses them back to decide which depots/keys belong
#     to which game when it later cleans the config up.
# ---------------------------------------------------------------------------
def _sanitize_comment(comment) -> str:
    """Strip newlines/control chars from a comment to prevent YAML line injection."""
    if not comment:
        return ""
    cleaned = str(comment).replace("\r", " ").replace("\n", " ").strip()
    return re.sub(r"[ \t]+", " ", cleaned)

def _sanitize_id(item_id) -> str | None:
    """Validate an AppID/DepotID and return it as a bare numeric string."""
    if item_id is None:
        return None
    s = str(item_id).strip()
    return s if _NUMERIC_ID_RE.match(s) else None

def _sanitize_key(key) -> str | None:
    """Validate a 64-char AES hex decryption key. Returns it VERBATIM.

    Canary rule: valid 64-hex keys must be written to DecryptionKeys 100% of
    the time and never sanitized. Hex is case-insensitive to Steam, so we
    deliberately do NOT normalize case here — the key is stored exactly as
    supplied. Only whitespace is stripped.
    """
    if not key:
        return None
    k = str(key).strip()
    return k if _HEX_64_RE.match(k) else None

def _validate_yaml_content(content: str) -> bool:
    """Refuse to write malformed YAML, or YAML with duplicate top-level keys.

    PyYAML silently keeps only the first of two duplicate keys, so a duplicate
    section makes an edit a silent no-op. It is not bundled with Decky, so the
    duplicate scan runs unconditionally and the syntax parse is best-effort.
    """
    try:
        import yaml  # type: ignore
        yaml.safe_load(content)
    except ImportError:
        logger.debug("PyYAML unavailable; skipping syntax parse before write")
    except Exception as e:
        logger.error(f"Refusing to write invalid YAML to config: {e}")
        return False

    top_keys = re.findall(r"^['\"]?([A-Za-z0-9_]+)['\"]?(?=[ \t]*:)", content, re.MULTILINE)
    seen: set[str] = set()
    dupes: set[str] = set()
    for k in top_keys:
        if k in seen:
            dupes.add(k)
        seen.add(k)
    if dupes:
        logger.error(f"Refusing to write config with duplicate top-level keys: {dupes}")
        return False
    return True

def _write_sls_config(cfg: Path, content: str, notify: bool = True) -> bool:
    """Atomically write config.yaml in place, preserving the inode.

    The inode matters: SLSsteam watches the file with inotify. A tmp+rename
    swap would emit a delete/create pair and can race a reader into seeing an
    empty config. 0600 is enforced because the file holds the user's keys.
    """
    if cfg is None:
        return False
    if not _validate_yaml_content(content):
        return False
    with _sls_write_lock:
        try:
            cfg.parent.mkdir(parents=True, exist_ok=True)
            if cfg.exists():
                with open(cfg, "r+", encoding="utf-8") as f:
                    f.seek(0)
                    f.write(content)
                    f.truncate()
                    f.flush()
                    os.fsync(f.fileno())
            else:
                with open(cfg, "w", encoding="utf-8") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
            try:
                os.chmod(cfg, 0o600)
            except OSError:
                pass
        except Exception as e:
            logger.error("Failed writing %s: %s", cfg, e)
            return False
    if notify:
        _signal_slssteam_api("RELOAD")
    return True

def _get_section_bounds(content: str, section_name: str) -> tuple[int, int, int] | None:
    """Return (header_start, content_start, section_end) for a top-level section."""
    header = re.compile(
        r"^[ \t]*['\"]?" + re.escape(section_name) + r"['\"]?[ \t]*:[ \t]*(?:\[[ \t]*\]|\{[ \t]*\})?[ \t]*(?:#[^\r\n]*)?$",
        re.MULTILINE,
    )
    m = header.search(content)
    if not m:
        return None
    h_start, c_start = m.start(), m.end()
    if c_start < len(content) and content[c_start] == "\r":
        c_start += 1
    if c_start < len(content) and content[c_start] == "\n":
        c_start += 1
    after = content[c_start:]
    nxt = _TOP_LEVEL_KEY_RE.search(after)
    return h_start, c_start, (c_start + nxt.start()) if nxt else len(content)

def _section_insert_pos(content: str, c_start: int, s_end: int) -> int:
    """Index just after the last list/map item in a section (never under a trailing comment)."""
    offset = 0
    last_item_end = 0
    for line in content[c_start:s_end].splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("-") or re.match(r"^['\"]?[A-Za-z0-9_]+['\"]?\s*:", stripped):
            last_item_end = offset + len(line)
        offset += len(line)
    return c_start + last_item_end

def _upsert_in_memory(content: str, section: str, key: str, value: str = "", comment: str = "") -> tuple[str, bool]:
    """Add/update a section entry entirely in memory. Returns (content, changed).

    value == "" -> list item:  "  - {key} # {comment}"
    value != "" -> map item:   "  {key}: {value} # {comment}"
    """
    clean = _sanitize_id(key)
    if not clean:
        return content, False
    comment = _sanitize_comment(comment)
    entry = f"  {clean}: {value} # {comment}" if value else f"  - {clean} # {comment}"

    bounds = _get_section_bounds(content, section)
    if bounds is None:
        return content.rstrip() + f"\n\n{section}:\n{entry}\n", True

    _, c_start, s_end = bounds
    sec = content[c_start:s_end]
    if value:
        pattern = re.compile(
            rf"^[ \t]*['\"]?{re.escape(clean)}['\"]?[ \t]*:[ \t]*['\"]?([^ \t#'\"]*)['\"]?[ \t]*(?:#[^\r\n]*)?$",
            re.MULTILINE,
        )
    else:
        pattern = re.compile(
            rf"^[ \t]*-[ \t]*{re.escape(clean)}[ \t]*(?:#[^\r\n]*)?$",
            re.MULTILINE,
        )

    m = pattern.search(sec)
    if m:
        # For map entries an identical value already present is a no-op, so
        # repeated injects stay idempotent instead of rewriting the file.
        if value and (m.group(1) or "").strip().lower() == value.strip().lower():
            return content, False
        # lambda avoids backslash/group expansion in the replacement
        new_sec = pattern.sub(lambda _m: entry, sec, count=1)
        return content[:c_start] + new_sec + content[s_end:], True

    pos = _section_insert_pos(content, c_start, s_end)
    return content[:pos] + entry + "\n" + content[pos:], True

def _remove_in_memory(content: str, section: str, key: str, is_list: bool | None = None) -> tuple[str, bool]:
    """Remove a section entry entirely in memory. Returns (content, removed)."""
    clean = _sanitize_id(key)
    if not clean:
        return content, False
    bounds = _get_section_bounds(content, section)
    if bounds is None:
        return content, False
    _, c_start, s_end = bounds
    sec = content[c_start:s_end]
    if is_list is None:
        is_list = bool(re.search(r"^[ \t]*-[ \t]*\d+", sec, re.MULTILINE))
    if is_list:
        pattern = re.compile(rf"^[ \t]*-[ \t]*{re.escape(clean)}[ \t]*(?:#[^\r\n]*)?\r?\n?", re.MULTILINE)
    else:
        pattern = re.compile(rf"^[ \t]*['\"]?{re.escape(clean)}['\"]?[ \t]*:[^\r\n]*\r?\n?", re.MULTILINE)
    new_sec, n = pattern.subn("", sec, count=1)
    if not n:
        return content, False
    return content[:c_start] + new_sec + content[s_end:], True

def _parse_list_section(content: str, section: str) -> dict[str, str]:
    """Parse a `  - 123 # comment` list section into {id: comment}."""
    out: dict[str, str] = {}
    bounds = _get_section_bounds(content, section)
    if not bounds:
        return out
    for line in content[bounds[1]:bounds[2]].splitlines():
        m = re.match(r"^[ \t]*-[ \t]*(\d+)(?:[ \t]*#[ \t]*(.*))?$", line)
        if m:
            out[m.group(1)] = (m.group(2) or "").strip()
    return out

def _parse_key_section(content: str, section: str) -> tuple[dict[str, str], dict[str, str]]:
    """Parse a `  123: <64hex> # comment` map section into ({id: key}, {id: comment})."""
    keys: dict[str, str] = {}
    comments: dict[str, str] = {}
    bounds = _get_section_bounds(content, section)
    if not bounds:
        return keys, comments
    for m in re.finditer(
        r"^[ \t]*['\"]?(\d+)['\"]?[ \t]*:[ \t]*['\"]?([a-fA-F0-9]{64})['\"]?(?:[ \t]*#[ \t]*(.*))?$",
        content[bounds[1]:bounds[2]],
        re.MULTILINE,
    ):
        keys[m.group(1)] = m.group(2)
        comments[m.group(1)] = (m.group(3) or "").strip()
    return keys, comments

def _replace_section_block(content: str, section: str, body_lines: list[str]) -> str:
    """Replace (or append) a whole top-level section, sorting entries numerically."""
    block = "\n".join([f"{section}:"] + body_lines) + "\n"
    bounds = _get_section_bounds(content, section)
    if bounds:
        old_block = content[bounds[0]:bounds[2]]
        # Keep the blank-line separation that followed the old section so the
        # file keeps the same visual layout it had before the rewrite.
        trailing = len(old_block) - len(old_block.rstrip("\n"))
        if trailing:
            block += "\n" * (trailing - 1)
        return content[:bounds[0]] + block + content[bounds[2]:]
    return content.rstrip() + "\n\n" + block

def _sort_ids(ids) -> list[str]:
    return sorted(ids, key=lambda x: int(x) if x.isdigit() else 0)

def _ensure_plugins_enabled(content: str) -> str:
    """Force `Plugins: yes` — the library-inject plugin loader requires it.

    Matches ASSella's `ensure_plugins_enabled` / the AT0M patch step 1.
    """
    if re.search(r"^[ \t]*Plugins[ \t]*:[ \t]*(?:yes|true)\b", content, re.MULTILINE | re.IGNORECASE):
        return content
    if re.search(r"^[ \t]*Plugins[ \t]*:", content, re.MULTILINE):
        return re.sub(r"^[ \t]*Plugins[ \t]*:.*$", "Plugins: yes", content, flags=re.MULTILINE)
    return "Plugins: yes\n" + content

def _ensure_smart_tickets(content: str) -> str:
    """Ensure `SmartTickets: 0x1` is present, mirroring ASSella's AT0M path."""
    m = re.search(r"^([ \t]*)SmartTickets[ \t]*:[ \t]*([^\r\n#]+)(.*)$", content, re.MULTILINE)
    if not m:
        return content.rstrip() + "\n\nSmartTickets: 0x1\n"
    if m.group(2).strip().lower() == "0x1":
        return content
    comment = f" {m.group(3).strip()}" if m.group(3).strip() else ""
    return re.sub(
        r"^[ \t]*SmartTickets[ \t]*:[^\r\n#]*",
        f"{m.group(1)}SmartTickets: 0x1{comment}",
        content,
        count=1,
        flags=re.MULTILINE,
    )

class _SlsConfigEditor:
    """One read -> many in-memory edits -> one validated in-place write.

    Mirrors ASSella's `batch_config_edit` context manager. Batching matters:
    per-entry writes mean a config reread+rewrite per entry, a backup per
    entry, and a reload notification per entry — SLSsteam would reload the
    whole library dozens of times for a single game.
    """

    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path if config_path is not None else _find_sls_config()
        self.content = ""
        self.has_changes = False
        self.committed_successfully = True

    def __enter__(self) -> "_SlsConfigEditor":
        if self.config_path is None:
            self.content = ""
        elif self.config_path.exists():
            self.content = self.config_path.read_text(encoding="utf-8", errors="replace")
        else:
            self.content = "Plugins: yes\nAdditionalApps:\n"
        self.has_changes = False
        self.committed_successfully = True
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.committed_successfully = False
            return False
        if self.has_changes:
            self.committed_successfully = _write_sls_config(self.config_path, self.content)
            if not self.committed_successfully:
                return False
        return True

    def _apply(self, content: str, changed: bool) -> bool:
        if changed:
            self.content = content
            self.has_changes = True
        return changed

    def add_app(self, app_id: str, comment: str = "") -> bool:
        return self._apply(*_upsert_in_memory(self.content, "AdditionalApps", app_id, comment=comment))

    def remove_app(self, app_id: str) -> bool:
        return self._apply(*_remove_in_memory(self.content, "AdditionalApps", app_id, is_list=True))

    def add_depot(self, depot_id: str, comment: str = "") -> bool:
        return self._apply(*_upsert_in_memory(self.content, "AdditionalDepots", depot_id, comment=comment))

    def remove_depot(self, depot_id: str) -> bool:
        return self._apply(*_remove_in_memory(self.content, "AdditionalDepots", depot_id, is_list=True))

    def add_key(self, depot_id: str, key: str, comment: str = "") -> bool:
        clean = _sanitize_key(key)
        if not clean:
            logger.warning(f"Refusing to write invalid AES key for depot {depot_id}")
            return False
        return self._apply(*_upsert_in_memory(self.content, "DecryptionKeys", depot_id, value=clean, comment=comment))

    def remove_key(self, depot_id: str) -> bool:
        return self._apply(*_remove_in_memory(self.content, "DecryptionKeys", depot_id, is_list=False))

    def add_manifest_id(self, depot_id: str, manifest_id: str) -> bool:
        mid = str(manifest_id).strip()
        if not mid or not _NUMERIC_ID_RE.match(mid):
            return False
        return self._apply(*_upsert_in_memory(self.content, "ManifestIds", depot_id, value=mid))

    def add_fake_app_id(self, app_id: str, target_id: str, comment: str = "") -> bool:
        return self._apply(*_upsert_in_memory(self.content, "FakeAppIds", app_id, value=str(target_id), comment=comment))

    def remove_fake_app_id(self, app_id: str) -> bool:
        return self._apply(*_remove_in_memory(self.content, "FakeAppIds", app_id, is_list=False))

    def remove_launch_option(self, app_id: str) -> bool:
        return self._apply(*_remove_in_memory(self.content, "LaunchOptions", app_id, is_list=False))

    def remove_dlc(self, app_id: str) -> bool:
        """Remove a whole nested DlcData block for this parent app."""
        before = self.content
        changed = _remove_dlc_block(self.content, app_id)
        if changed is None:
            return False
        return self._apply(changed, True)

def _batch_config_edit(config_path: Path | None = None) -> _SlsConfigEditor:
    return _SlsConfigEditor(config_path)

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

    dlc_ids: set[str] = set(rec_dlcs)

    dlcs_list: list[dict] = []
    for did in sorted(dlc_ids, key=lambda x: int(x) if x.isdigit() else 0):
        dname = sqlite_depots.get(did, {}).get("name") or rec_names.get(did) or f"DLC {did}"
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

def get_atom_game_detail(app_id: str) -> dict:
    """Per-game state for the detail page: toggles, depots, DLCs, and install info."""
    aid = _sanitize_id(app_id)
    if not aid:
        return {"ok": False, "error": "Invalid AppID"}
    rec = load_plugin_library().get(aid) or {}
    install = _atom_install_info(aid)
    game_dir = Path(install.get("install_path") or "")

    fake = get_fake_appid(aid)
    sls_online = bool(fake)
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
        "fake_appid": fake,
        "netsock": netsock,
        "eos": eos,
        "eos_available": eos != "none",
        "registered": bool(rec),
        "depots_detail": depots_detail,
        "dlcs_detail": dlcs_detail,
        "dlcs_injected": dlcs_injected,
    }

def preview_atom_uninstall(app_id: str) -> dict:
    """What an uninstall WOULD delete — used to build the confirmation text."""
    aid = _sanitize_id(app_id)
    if not aid:
        return {"ok": False, "error": "Invalid AppID"}
    install = _atom_install_info(aid)
    targets = []
    ip = install.get("install_path") or ""
    if ip and Path(ip).exists():
        targets.append(ip)
    lib = install.get("library_path") or ""
    if lib:
        for extra in (
            Path(lib) / "steamapps" / "downloading" / aid,
            Path(lib) / "steamapps" / "temp" / aid,
            Path(lib) / "steamapps" / f"appmanifest_{aid}.acf",
            Path(lib) / "steamapps" / "compatdata" / aid,
        ):
            if extra.exists():
                targets.append(str(extra))
    return {
        "ok": True,
        "app_id": aid,
        "name": (load_plugin_library().get(aid) or {}).get("name") or f"App {aid}",
        "targets": targets,
        "installed": bool(install.get("installed")),
    }

def uninstall_atom_game(app_id: str) -> dict:
    """Fully remove an AT0M game: files, Steam metadata and SLS config."""
    aid = _sanitize_id(app_id)
    if not aid:
        return {"ok": False, "error": "Invalid AppID"}

    preview = preview_atom_uninstall(aid)
    install = _atom_install_info(aid)

    # Back up config before touching it.
    create_backup("pre_uninstall")

    # Tell SLSsteam/Steam first so it does not rewrite state mid-delete.
    _signal_slssteam_api(f"uninstall|{aid}")

    removed, failed = [], []
    for target in preview.get("targets", []):
        p = Path(target)
        try:
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
            removed.append(target)
        except Exception as e:
            failed.append(f"{target}: {e}")
            logger.error("Uninstall failed on %s: %s", target, e)

    # Remove compatdata/userdata leftovers for the main app.
    for lib in _steam_libraries():
        for extra in (
            lib / "steamapps" / "compatdata" / aid,
            lib / "userdata" / aid,
        ):
            if extra.is_dir():
                try:
                    shutil.rmtree(extra)
                    removed.append(str(extra))
                except Exception as e:
                    failed.append(f"{extra}: {e}")

    # Restore any EOS proxy we applied before deleting files (safety).
    ip = install.get("install_path") or ""
    if ip and Path(ip).is_dir():
        try:
            remove_eos_proxy(Path(ip))
        except Exception:
            pass

    cfg_ok = unregister_plugin_game(aid)

    return {
        "ok": not failed,
        "app_id": aid,
        "removed": removed,
        "failed": failed,
        "config_cleaned": cfg_ok,
        "registered": aid in (load_plugin_library() or {}),
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
        # 1. Harvest Hubcap manifest bundle + depot keys WITHOUT writing config,
        #    so the whole inject lands as one atomic write below.
        manifest_res = fetch_manifests(app_id, persist_config=False)
        depot_keys = {}
        manifest_ids = {}
        resolved_dlcs = set(dlc_appids or ())
        resolved_name = name

        if manifest_res.get("ok"):
            depot_keys = dict(manifest_res.get("depot_keys", {}))
            status_entry["depot_keys"] = manifest_res.get("keys_added", [])
            status_entry["manifests"] = manifest_res.get("manifests", [])
            if _get_setting("manifestid_pinning"):
                manifest_ids = manifest_res.get("pinned_manifests", {})
            # The Lua carries the authoritative game name and DLC list.
            if manifest_res.get("game_name"):
                resolved_name = manifest_res["game_name"]
            resolved_dlcs |= {d for d in (manifest_res.get("dlc_appids") or []) if d}
        else:
            status_entry["manifest_error"] = manifest_res.get("error")

        # 2. Top up from keys already in config, scoped to this game.
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
    details = get_app_details(app_id)
    name = details.get("name", f"App {app_id}")
    depots = details.get("depots", [])
    dlc_ids = [_sanitize_id(d) for d in details.get("dlc", [])]

    cfg = _find_sls_config()
    if not cfg:
        return {"error": "SLSsteam config not found at ~/.config/SLSsteam/config.yaml"}

    # Preflight guards — fail fast and loudly rather than registering a game
    # that can never download (no key => DepotWithoutKey / no AppKey).
    if not _detect_assella_canary_hubcap_key():
        return {
            "error": "No Hubcap API key found. Set morrenus_api_key in ASSella "
                     "settings (~/.config/Tachibana Labs/ACCELA.conf) or add an "
                     "override in this plugin's settings.",
            "blocked": "no_api_key",
        }

    # Automatic safety backup
    create_backup("pre_inject")

    # The AppID registration itself now happens inside the single-pass inject in
    # the background worker, together with depots + keys, so SLSsteam reloads
    # once instead of once per entry.
    # NOTE: package IDs are deliberately NOT injected. ASSella never writes
    # AdditionalPackages either; packages are not needed for the AT0M flow.

    # Initialize inject status
    _inject_status[app_id] = {
        "done": False,
        "running": True,
        "app_id": app_id,
        "name": name,
    }

    # Record recent inject
    recent_entry = {
        "app_id": app_id,
        "name": name,
        "depots_resolved": depots,
    }
    _recent_injects.insert(0, recent_entry)
    if len(_recent_injects) > 20:
        _recent_injects.pop()

    # Launch background worker
    threading.Thread(
        target=_background_inject_worker,
        args=(app_id, name, set(dlc_ids), set(depots)),
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

# ---------------------------------------------------------------------------
# Decky Plugin Class
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Local key-capture server ("Show QR code")
#
# In Gaming Mode there is no keyboard, so pasting a 100-char API key is painful.
# This serves a one-page form on the LAN; the Decky UI shows a QR code of its
# URL, the phone scans it and posts the key back. The server is short-lived:
# it binds to one random high port, requires a per-session token in the URL,
# and shuts itself down shortly after a successful submission.
#
# The key is validated against Hubcap's /depot-keys (authenticated, zero quota)
# before being stored. /health is NOT used: it is unauthenticated and returns
# 200 for any input, so it cannot prove a key is valid.
# ---------------------------------------------------------------------------
_KEYCARE_PORT_RANGE = (38500, 38600)
_KEYCARE_TTL_SECONDS = 300

_keycare_state: dict = {
    "running": False,
    "port": None,
    "token": None,
    "started_at": None,
    "urls": [],
    "status": "idle",
    "error": None,
    "keys_added": 0,
}
_keycare_server = None
_keycare_lock = threading.Lock()

def _lan_ip_addresses() -> list[str]:
    """Best-effort LAN IPv4 addresses a phone on the same Wi-Fi can reach.

    Avoids a full netifaces dependency: connect a UDP socket (sends nothing) to
    a public address and read the local end the kernel picked.
    """
    found: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.4)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                found.append(ip)
        finally:
            s.close()
    except Exception as e:
        logger.debug("UDP route probe failed: %s", e)

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("192.168.") or ip.startswith("10.") or re.match(r"^172\.(1[6-9]|2\d|3[01])\.", ip):
                if ip not in found:
                    found.append(ip)
    except Exception as e:
        logger.debug("hostname resolution failed: %s", e)

    # Private ranges only: 127.x and docker bridges are useless to a phone.
    return [ip for ip in found if not ip.startswith("127.")]

def _keycare_page(token: str) -> str:
    """Minimal self-contained form (no external assets, works offline)."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Uran · Hubcap key</title>
<style>
 body{{margin:0;font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
   background:#0e1116;color:#e6e6e6;display:flex;min-height:100vh;align-items:center;justify-content:center}}
 .card{{width:100%;max-width:520px;padding:24px}}
 h1{{font-size:20px;margin:0 0 4px}}
 p.sub{{color:#9aa4b2;margin:0 0 20px;font-size:14px}}
 label{{display:block;font-size:13px;color:#9aa4b2;margin-bottom:6px}}
 input{{width:100%;padding:14px;font-size:16px;border-radius:10px;border:1px solid #2a313c;
   background:#161b22;color:#e6e6e6;box-sizing:border-box}}
 input:focus{{outline:2px solid #1f6feb;border-color:transparent}}
 button{{width:100%;margin-top:14px;padding:14px;font-size:16px;font-weight:600;border:0;border-radius:10px;
   background:#1f6feb;color:#fff;cursor:pointer}}
 button:disabled{{opacity:.55}}
 .msg{{margin-top:16px;padding:12px;border-radius:10px;font-size:14px;display:none}}
 .ok{{display:block;background:#12331f;color:#7ee2a8;border:1px solid #1d5c37}}
 .err{{display:block;background:#3a1a1a;color:#ff9a9a;border:1px solid #6b2b2b}}
 .note{{color:#6b7684;font-size:12px;margin-top:18px}}
 code{{background:#161b22;padding:2px 6px;border-radius:4px}}
</style></head><body><div class="card">
<h1>Hubcap API key</h1>
<p class="sub">Paste your key below. It is checked against Hubcap, then stored
by Uran on your Steam Deck.</p>
<label for="k">API key</label>
<input id="k" type="password" inputmode="text" autocomplete="off"
       autocapitalize="off" autocorrect="off" spellcheck="false" placeholder="smm_...">
<button id="go">Submit</button>
<div id="m" class="msg"></div>
<p class="note">Get a key at <code>hubcapmanifest.com</code>. This page is
served by your Deck and closes automatically once the key is accepted.</p>
</div><script>
const TOKEN={token!r};
const inp=document.getElementById('k'),btn=document.getElementById('go'),m=document.getElementById('m');
function show(t,ok){{m.textContent=t;m.className='msg '+(ok?'ok':'err');}}
btn.onclick=async ()=>{{
 const k=inp.value.trim();
 if(!k){{show('Please paste a key first.',false);return;}}
 btn.disabled=true;btn.textContent='Checking…';show('Checking key with Hubcap…',true);
 try{{
  const r=await fetch('/submit',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{token:TOKEN,key:k}})}});
  const j=await r.json();
  if(j.ok){{show(j.message||'Key accepted.',true);btn.textContent='Done';inp.readOnly=true;}}
  else{{show(j.error||'Rejected.',false);btn.disabled=false;btn.textContent='Submit';}}
 }}catch(e){{show('Could not reach the Deck. Is it still on the same network?',false);
  btn.disabled=false;btn.textContent='Submit';}}
}};
inp.focus();
</script></body></html>"""

class _KeycareHandler(BaseHTTPRequestHandler):
    """Handles the phone's GET / and POST /submit."""

    server_version = "Uran"

    def log_message(self, fmt, *args):  # keep the key out of the Decky log
        logger.debug("keycare %s - %s", self.address_string(), fmt % args)

    def _send(self, code: int, body: str, ctype: str = "text/html; charset=utf-8") -> None:
        raw = body.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        token = _keycare_state.get("token")
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path != "/":
            return self._send(404, "not found", "text/plain")
        supplied = ""
        if "?" in self.path:
            for part in self.path.split("?", 1)[1].split("&"):
                if part.startswith("token="):
                    supplied = part[6:]
        # Same-origin token check: a bare scan from an untrusted device fails.
        if not token or supplied != token:
            return self._send(403, "Invalid or expired link.", "text/plain; charset=utf-8")
        self._send(200, _keycare_page(token))

    def do_POST(self):
        if self.path.split("?")[0].rstrip("/") != "/submit":
            return self._send(404, "not found", "text/plain")
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 8192:
                return self._send(400, "bad request", "text/plain")
            payload = json.loads(self.rfile.read(length).decode("utf-8", "replace"))
        except Exception:
            return self._send(400, "bad request", "text/plain")

        if payload.get("token") != _keycare_state.get("token"):
            return self._send(403, json.dumps({"ok": False, "error": "Invalid session."}),
                              "application/json")

        key = str(payload.get("key") or "").strip()
        if not key:
            return self._send(400, json.dumps({"ok": False, "error": "No key supplied."}),
                              "application/json")

        ok, message, detail = validate_hubcap_key(key)
        if not ok:
            _keycare_state["status"] = "rejected"
            return self._send(200, json.dumps({"ok": False, "error": message}),
                              "application/json")

        stored_ok, where = save_hubcap_key(key)
        logger.info("Hubcap key accepted via local QR capture (%s)", where)
        _keycare_state["status"] = "accepted" if stored_ok else "accepted_unstored"
        _keycare_state["stored_in"] = where
        _schedule_keycare_shutdown(delay=20)
        return self._send(200, json.dumps({
            "ok": True,
            "message": f"{message} Saved — shared with ASSella.",
        }), "application/json")

def validate_hubcap_key(key: str) -> tuple[bool, str, str]:
    """Validate a Hubcap API key via /user/stats (same endpoint ASSella uses).

    Returns (ok, message, detail_json). /user/stats is authenticated, consumes
    no generation quota, and reports the owning account so we can confirm the
    right key was pasted. (/health cannot be used: it is unauthenticated and
    answers 200 for any input.)
    """
    key = str(key or "").strip()
    if not key:
        return False, "No key supplied.", ""
    try:
        resp = requests.get(
            f"{HUBCAP_BASE_URL}/user/stats",
            headers={"Authorization": f"Bearer {key}"},
            timeout=20,
        )
    except Exception as e:
        return False, f"Could not reach Hubcap: {e}", ""

    if resp.status_code == 200:
        try:
            data = resp.json()
        except Exception:
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
        except Exception:
            pass
        return False, detail or "Hubcap rejected this key (401).", str(resp.status_code)
    if resp.status_code == 429:
        return False, "Hubcap rate limit reached. Try again later.", str(resp.status_code)
    return False, f"Unexpected Hubcap response (HTTP {resp.status_code}).", str(resp.status_code)

def get_hubcap_user_stats() -> dict:
    """Account stats for the currently configured key (via /user/stats)."""
    key = _detect_assella_canary_hubcap_key()
    if not key:
        return {"ok": False, "error": "No key configured"}
    ok, message, detail = validate_hubcap_key(key)
    if not ok:
        return {"ok": False, "error": message}
    try:
        data = json.loads(detail) if detail else {}
    except Exception:
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
        except Exception:
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

def save_hubcap_key(key: str) -> tuple[bool, str]:
    """Validate and persist a key into ACCELA's config (shared with ASSella).

    Returns (ok, message).
    """
    key = str(key or "").strip()
    ok, message, _ = validate_hubcap_key(key)
    if not ok:
        return False, message

    wrote, where = _write_accela_api_key(key)
    with _settings_write_lock:
        s = _load_settings()
        s["manifest_api_key"] = "" if wrote else key
        _save_settings(s)
    return True, where

def _schedule_keycare_shutdown(delay: int) -> None:
    def _stop():
        time.sleep(delay)
        stop_keycare_server()
    threading.Thread(target=_stop, daemon=True).start()

def stop_keycare_server() -> dict:
    """Shut the local capture server down."""
    global _keycare_server
    with _keycare_lock:
        srv = _keycare_server
        _keycare_server = None
    if srv is not None:
        try:
            srv.shutdown()
            srv.server_close()
        except Exception as e:
            logger.debug("keycare shutdown: %s", e)
    _keycare_state.update({"running": False, "port": None, "token": None, "urls": []})
    return {"ok": True}

def start_keycare_server() -> dict:
    """Start the local capture server and return the URLs to encode as a QR."""
    global _keycare_server
    with _keycare_lock:
        if _keycare_server is not None:
            return {"ok": True, **get_keycare_status()}

        token = secrets.token_urlsafe(24)
        httpd = None
        last_err = None
        lo, hi = _KEYCARE_PORT_RANGE
        for port in range(lo, hi):
            try:
                httpd = ThreadingHTTPServer(("0.0.0.0", port), _KeycareHandler)
                break
            except OSError as e:
                last_err = e
                continue
        if httpd is None:
            _keycare_state.update({"status": "error", "error": f"No free port: {last_err}"})
            return {"ok": False, "error": _keycare_state["error"]}

        httpd.daemon_threads = True
        _keycare_server = httpd
        port = httpd.server_address[1]
        urls = [f"http://{ip}:{port}/?token={token}" for ip in _lan_ip_addresses()]
        _keycare_state.update({
            "running": True,
            "port": port,
            "token": token,
            "started_at": time.time(),
            "urls": urls,
            "status": "waiting",
            "error": None,
            "keys_added": 0,
        })
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.3},
                         daemon=True).start()
        logger.info("Local key-capture server listening on port %d", port)

        # Auto-expire so we are not listening indefinitely.
        _schedule_keycare_shutdown(delay=_KEYCARE_TTL_SECONDS)

        if not urls:
            logger.warning("No LAN address detected; QR may not be reachable from a phone")
        return {"ok": True, **get_keycare_status()}

def get_keycare_status() -> dict:
    st = dict(_keycare_state)
    started = st.get("started_at")
    if started:
        st["expires_in"] = max(0, int(_KEYCARE_TTL_SECONDS - (time.time() - started)))
    # Never expose the token to logs/UI beyond what the URL already carries.
    st.pop("token", None)
    return st

def get_hubcap_key_status() -> dict:
    """Report where the Hubcap key came from, for the settings UI."""
    stored = _stored_hubcap_key()
    detected = ""
    source = ""
    for p in _accela_conf_candidates():
        if p.is_file():
            detected = _read_ini_value(p, "morrenus_api_key")
            if detected:
                source = str(p)
                break
    if stored:
        origin, masked = "plugin override", stored
    elif detected:
        origin, masked = f"ACCELA ({source})", detected
    else:
        origin, masked = "not found", ""
    return {
        "ok": bool(stored or detected),
        "source": origin,
        "configured_path": source,
        "masked": (masked[:8] + "..." + masked[-4:]) if len(masked) > 14 else masked,
        "is_override": bool(stored),
        "base_url": HUBCAP_BASE_URL,
    }

class Plugin:
    async def _main(self) -> None:
        logger.info("Uran plugin loaded")
        # Pre-seed cached manifests into depotcache
        cache = _manifest_cache_dir()
        depotcache = _depotcache_dir()
        if depotcache and cache.exists():
            seeded = 0
            for mf in cache.glob("*.manifest"):
                dst = depotcache / mf.name
                if not dst.exists():
                    try:
                        shutil.copy2(mf, dst)
                        seeded += 1
                    except OSError:
                        pass
            if seeded > 0:
                logger.info(f"Restored {seeded} cached manifest(s) to depotcache")

    async def _unload(self) -> None:
        # Never leave the LAN listener running after the plugin goes away.
        try:
            stop_keycare_server()
        except Exception as e:
            logger.debug("keycare cleanup on unload: %s", e)
        logger.info("Uran plugin unloaded")

    async def _uninstall(self) -> None:
        p = _settings_path()
        p.unlink(missing_ok=True)
        logger.info("Uran settings cleared on uninstall")

    # CDP helper for Steam Store webview
    async def discover_store_tab(self) -> dict | None:
        for port in range(8080, 8083):
            try:
                resp = requests.get(f"http://localhost:{port}/json", timeout=3)
                if resp.ok:
                    tabs = resp.json()
                    for t in tabs:
                        url = t.get("url", "")
                        if "store.steampowered.com/app/" in url:
                            return {
                                "webSocketDebuggerUrl": t.get("webSocketDebuggerUrl"),
                                "url": url,
                            }
            except Exception:
                continue
        return None

    # Settings Callables
    async def get_setting(self, key: str, default=None):
        return _get_setting(key, default)

    async def set_setting(self, key: str, value) -> None:
        _set_setting(key, value)

    async def read_clipboard(self) -> dict:
        return read_clipboard()

    async def fe_debug(self, msg: str) -> None:
        logger.debug(f"[FE] {msg}")

    async def restart_steam(self) -> None:
        restart_steam()

    # Search & Injection Callables
    async def search_games(self, query: str, limit: int = 20, appid: bool = False) -> dict:
        return search_games(query, limit=limit, appid=appid)

    async def inject_game(self, app_id: str) -> dict:
        return inject_game(app_id)

    async def get_inject_status(self, app_id: str) -> dict | None:
        return get_inject_status(app_id)

    async def get_recent_injects(self) -> list[dict]:
        return get_recent_injects()

    # Backups Callables
    async def list_backups(self) -> list[dict]:
        return list_backups()

    async def create_backup(self) -> str:
        return create_backup("manual")

    async def restore_backup(self, backup_name: str) -> dict:
        return restore_backup(backup_name)

    # FakeAppIds Callables
    async def get_fake_app_ids(self) -> dict:
        return get_fake_app_ids()

    async def add_fake_app_id(self, app_id: str) -> dict:
        return add_fake_app_id(app_id)

    async def remove_fake_app_id(self, app_id: str) -> dict:
        return remove_fake_app_id(app_id)

    # DLC & Manifest Callables
    async def fetch_dlcs_for_app(self, app_id: str) -> dict:
        return fetch_dlcs_for_app(app_id)

    async def toggle_game_dlcs(self, app_id: str, enable: bool) -> dict:
        return toggle_game_dlcs(app_id, enable)

    async def refetch_manifests(self, app_id: str) -> dict:
        return refetch_manifests(app_id)

    async def remove_manifest_id_pins(self, app_id: str) -> dict:
        return remove_manifest_id_pins(app_id)

    async def why_not_downloading(self, app_id: str) -> dict:
        return why_not_downloading(app_id)

    async def send_notification(self, title: str, body: str) -> dict:
        try:
            subprocess.run(["notify-send", title, body], timeout=2)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def get_hubcap_key_status(self) -> dict:
        return get_hubcap_key_status()

    async def start_key_server(self) -> dict:
        return start_keycare_server()

    async def key_server_status(self) -> dict:
        return get_keycare_status()

    async def stop_key_server(self) -> dict:
        return stop_keycare_server()

    async def validate_hubcap_key(self, key: str) -> dict:
        ok, message, detail = validate_hubcap_key(key)
        return {"ok": ok, "message": message, "detail": detail}

    async def save_hubcap_key(self, key: str) -> dict:
        ok, message = save_hubcap_key(key)
        return {"ok": ok, "message": message}

    async def get_hubcap_user_stats(self) -> dict:
        return get_hubcap_user_stats()

    async def hubcap_manifest_contents(self, app_id: str) -> dict:
        return hubcap_manifest_contents(app_id)

    async def list_plugin_games(self) -> dict:
        return {"ok": True, "games": list_atom_games()}

    async def get_atom_game(self, app_id: str) -> dict:
        return get_atom_game_detail(app_id)

    async def preview_atom_uninstall(self, app_id: str) -> dict:
        return preview_atom_uninstall(app_id)

    async def uninstall_atom_game(self, app_id: str) -> dict:
        return uninstall_atom_game(app_id)

    async def set_slsonline(self, app_id: str, enabled: bool, fake_appid: str = "480") -> dict:
        if enabled:
            return set_fake_appid(app_id, fake_appid or "480")
        # Turning SLSonline off also drops NetSock, matching ASSella's cascade.
        set_fake_appid(app_id, "")
        set_netsock(app_id, False)
        return {"ok": True, "fake_appid": ""}

    async def set_netsock_toggle(self, app_id: str, enabled: bool) -> dict:
        return set_netsock(app_id, enabled)

    async def set_eos_toggle(self, app_id: str, enabled: bool) -> dict:
        return set_eos_proxy(app_id, enabled)

    async def set_eos_netsock(self, app_id: str, enabled: bool) -> dict:
        """Enable/disable NetSock together with the EOS proxy."""
        eos = set_eos_proxy(app_id, enabled) if enabled else {"ok": True}
        net = set_netsock(app_id, enabled)
        if not eos.get("ok"):
            return eos
        return net if not net.get("ok") else {"ok": True, "eos": True, "netsock": enabled}

    async def unregister_plugin_game(self, app_id: str) -> dict:
        return {"ok": unregister_plugin_game(app_id)}

    async def get_notification_channel(self, gaming_ui: bool | None = None) -> dict:
        mode = _get_setting("notification_mode", "auto")
        if mode == "auto":
            channel = "steam" if (gaming_ui or os.environ.get("SteamGamepadUI")) else "desktop"
        else:
            channel = mode
        return {"ok": True, "channel": channel}
