"""Plugin settings and the shared Hubcap API key.

Settings live in Decky's per-plugin settings dir. The Hubcap key is special:
it is stored in ASSella's own config so both tools always present the same key,
and this module only keeps an override when it could not write there.
"""

import json
import logging
import threading
from pathlib import Path

from . import paths

logger = logging.getLogger("Uran")

APP_CONFIG_DIR = "assella-decky"

DEFAULTS: dict = {
    "fetch_dlcs_on_inject": False,
    "manifestid_pinning": False,
    "steam_store_enabled": True,
    "manifest_api_key": "",
    "notification_mode": "auto",
    # Route to the Hubcap API: auto | direct | proxy. See hubcap.py.
    "hubcap_gateway": "auto",
}


class Settings:
    """JSON-backed settings with an in-process cache.

    Reads are frequent (every Hubcap request consults a setting) and the file
    is tiny, so it is cached and invalidated on write.
    """

    def __init__(self, settings_dir: Path):
        self._dir = settings_dir
        self._path = settings_dir / "settings.json"
        # RLock: get+set is often performed as a pair while already holding it.
        self._lock = threading.RLock()
        self._cache: dict | None = None

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict:
        with self._lock:
            if self._cache is not None:
                return self._cache
            cfg = dict(DEFAULTS)
            if self._path.exists():
                try:
                    loaded = json.loads(self._path.read_text())
                    if isinstance(loaded, dict):
                        cfg.update(loaded)
                except Exception as exc:  # noqa: BLE001 - fall back to defaults
                    logger.warning("failed loading settings.json: %s", exc)
            self._cache = cfg
            return cfg

    def save(self, data: dict) -> None:
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._path.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, indent=2))
                tmp.replace(self._path)
                self._cache = dict(data)
            except Exception as exc:  # noqa: BLE001
                logger.error("failed saving settings: %s", exc)

    def get(self, key: str, default=None):
        value = self.load().get(key, default)
        if value is None and default is None:
            return DEFAULTS.get(key)
        return value

    def set(self, key: str, value) -> None:
        with self._lock:
            cfg = dict(self.load())
            cfg[key] = value
            self.save(cfg)

    def stored_hubcap_key(self) -> str:
        """Read the key override straight off disk.

        Bypasses the cache on purpose: the key detector runs from inside
        `load()`, so going through it here would recurse.
        """
        if not self._path.exists():
            return ""
        try:
            data = json.loads(self._path.read_text())
            if isinstance(data, dict):
                return str(data.get("manifest_api_key") or "").strip()
        except Exception:  # noqa: BLE001 - no override available
            pass
        return ""


class HubcapKey:
    """Resolves the Hubcap API key, preferring Uran's own override."""

    def __init__(self, settings: Settings, user_home_path: Path):
        self._settings = settings
        self._home = user_home_path
        self._last_source: str | None = None

    def current(self) -> str:
        """The key to authenticate with, or "" when none is configured."""
        override = self._settings.stored_hubcap_key()
        if override:
            return override

        for path in paths.accela_conf_candidates(self._home):
            if not path.is_file():
                continue
            key = paths.read_ini_value(path, "morrenus_api_key")
            if key:
                if self._last_source != str(path):
                    self._last_source = str(path)
                    logger.info(
                        "Auto-detected Hubcap API key from ACCELA config (%s)", path
                    )
                return key
        return ""

    def detected_in_assella(self) -> tuple[str, str]:
        """Return (key, path) for the key found in ASSella's config."""
        for path in paths.accela_conf_candidates(self._home):
            if path.is_file():
                key = paths.read_ini_value(path, "morrenus_api_key")
                if key:
                    return key, str(path)
        return "", ""

    def save(self, key: str) -> tuple[bool, str]:
        """Persist a key into ASSella's config, falling back to a local override."""
        wrote, where = paths.write_accela_api_key(key, self._home)
        # An empty override means "use ASSella's", which is the shared happy path.
        self._settings.set("manifest_api_key", "" if wrote else key)
        return wrote, where