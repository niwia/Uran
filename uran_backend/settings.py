"""Plugin settings and the shared Hubcap API key.

Uran and Epsilon are the same engine started two ways (inside Decky, or as a
standalone bridge), so they resolve one settings file: Decky's per-plugin file
when Uran is installed, otherwise Epsilon's own under ``~/.config/assella-decky``.
Older builds may still have a copy in the other location; ``Settings`` reads the
union (the file saved most recently wins a conflict) and mirrors writes into
copies that already exist, so both tools keep presenting the same values.

The Hubcap key is special: it is stored in ASSella's own config so both tools
always present the same key, and this module only keeps an override when it
could not write there.
"""

import json
import logging
import threading
from pathlib import Path

from . import paths

logger = logging.getLogger("Uran")

DEFAULTS: dict = {
    "fetch_dlcs_on_inject": True,
    "add_delisted_dlcs": True,
    "steam_store_enabled": True,
    "manifest_api_key": "",
    "manifest_api_key_timestamp": 0,
    "notification_mode": "auto",
    # Route to the Hubcap API: auto | direct | proxy. See hubcap.py.
    "hubcap_gateway": "auto",
    # User-disabled plugins (list of filenames)
    "disabled_plugins": [],
}


class Settings:
    """JSON-backed settings with an in-process cache.

    Reads are frequent (every Hubcap request consults a setting) and the files
    are tiny, so the merged view is cached and invalidated when any file's
    mtime changes.
    """

    def __init__(self, settings_dir: Path, mirrors: list[Path] | None = None):
        self._dir = settings_dir
        self._path = settings_dir / "settings.json"
        # Lower-precedence files, highest first (see paths.companion_settings_paths).
        self._mirrors = [Path(m) for m in (mirrors or []) if Path(m) != self._path]
        # RLock: get+set is often performed as a pair while already holding it.
        self._lock = threading.RLock()
        self._cache: dict | None = None
        self._cache_stamp: tuple | None = None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def mirror_paths(self) -> list[Path]:
        return list(self._mirrors)

    def all_paths(self) -> list[Path]:
        """Canonical file first, then every lower-precedence copy."""
        return [self._path, *self._mirrors]

    def _mtime_of(self, path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    def _stamp(self) -> tuple:
        return tuple((str(path), self._mtime_of(path)) for path in self.all_paths())

    @staticmethod
    def _read_path(path: Path) -> dict:
        """Read one settings file without going through the cache."""
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text())
        except Exception as exc:  # noqa: BLE001 - a bad file must not break the bridge
            logger.warning("failed loading %s: %s", path, exc)
            return {}
        return data if isinstance(data, dict) else {}

    def local_value(self, key: str):
        """A value as defined by the canonical file only."""
        return self._read_path(self._path).get(key)

    def shared_secret(self, key: str) -> str:
        """Newest file that defines ``key`` wins, like the Hubcap key sync.

        Used for the AT0-M console token: ASSella may rotate it in either file
        and the bridge must accept whichever was written last. Ties prefer the
        canonical file because it is listed first.
        """
        best = ""
        best_mtime = -1.0
        for path in self.all_paths():
            value = str(self._read_path(path).get(key) or "").strip()
            if not value:
                continue
            mtime = self._mtime_of(path)
            if mtime > best_mtime:
                best, best_mtime = value, mtime
        return best

    def load(self) -> dict:
        with self._lock:
            # ASSella (Settings -> Companions) and the other companion write
            # these files too: a changed mtime drops the cache so their edits
            # apply without reloading the plugin.
            stamp = self._stamp()
            if self._cache is not None and stamp == self._cache_stamp:
                return self._cache
            self._cache_stamp = stamp

            cfg = dict(DEFAULTS)
            # Oldest file first, newest last: the tool that saved most recently
            # wins, which is the same "newest wins" rule the Hubcap key uses.
            # Keys that only an older copy has still apply (that is what keeps
            # an upgrade from losing the console token).
            for path in self._load_order():
                cfg.update(self._read_path(path))
            self._cache = cfg
            return cfg

    def _load_order(self) -> list[Path]:
        """Settings files sorted oldest first; the canonical file wins a tie."""
        return sorted(
            self.all_paths(),
            key=lambda path: (self._mtime_of(path), path == self._path),
        )

    def save(self, data: dict) -> None:
        with self._lock:
            written = self._write_path(self._path, data)
            for mirror in self._mirrors:
                # Keep a copy other tools still read in sync, but never create
                # files that did not already exist: the canonical file is the
                # source of truth and an unused path is just noise.
                if not mirror.exists() and written:
                    continue
                merged = self._read_path(mirror)
                merged.update(data)
                written = self._write_path(mirror, merged) or written
            if written:
                self._cache = dict(data)
                self._cache_stamp = self._stamp()

    def _write_path(self, path: Path, data: dict) -> bool:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(path)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("failed saving %s: %s", path, exc)
            return False

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
        `load()`, so going through it here would recurse. Canonical file first,
        then the companion copies an older build may still have written.
        """
        for path in self.all_paths():
            key = str(self._read_path(path).get("manifest_api_key") or "").strip()
            if key:
                return key
        return ""


class HubcapKey:
    """Resolves and synchronizes the Hubcap API key with spacebunny.conf.lua and ASSella."""

    def __init__(self, settings: Settings, user_home_path: Path):
        self._settings = settings
        self._home = user_home_path
        self._last_source: str | None = None

    def spacebunny_conf_path(self) -> Path | None:
        """Resolve path to spacebunny.conf.lua."""
        return paths.spacebunny_conf(self._home)

    def current(self) -> str:
        """The key to authenticate with, synchronized with the spacebunny bridge."""
        from . import sls_lua_config

        active_key, was_synced, reason = sls_lua_config.sync_hubcap_key_bidirectional(
            self._settings, self.spacebunny_conf_path(), self._home
        )
        if active_key:
            return active_key

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

    def detected_in_spacebunny(self) -> tuple[str, str]:
        """Return (key, path) for the key found in spacebunny.conf.lua."""
        sb_path = self.spacebunny_conf_path()
        if sb_path and sb_path.is_file():
            from . import sls_lua_config
            cfg = sls_lua_config.read_spacebunny_conf(sb_path)
            key = str(cfg.get("hubcap", {}).get("api_key", "")).strip()
            if key:
                return key, str(sb_path)
        return "", ""

    def save(self, key: str, timestamp: int | None = None) -> tuple[bool, str]:
        """Persist a key into ASSella's config and spacebunny.conf.lua with timestamps."""
        from . import sls_lua_config

        key = str(key or "").strip()
        ts = timestamp if timestamp is not None else (sls_lua_config.generate_hubcap_timestamp() if key else 0)

        # 1. Update local settings
        self._settings.set("manifest_api_key", key)
        self._settings.set("manifest_api_key_timestamp", ts)

        # 2. Update spacebunny.conf.lua
        sb_path = self.spacebunny_conf_path()
        wrote_lua = False
        if sb_path is not None:
            if key:
                wrote_lua = sls_lua_config.sync_spacebunny_key(sb_path, key, timestamp=ts)
            elif sb_path.exists():
                try:
                    sb_path.unlink()
                    wrote_lua = True
                except OSError:
                    pass

        # 2b. katamari.conf.lua: what the AT0-M plugins read (key fields only)
        if key:
            sls_lua_config.write_katamari_hubcap_key(sls_lua_config.katamari_conf_path(sb_path), key, ts)

        # 3. Update ASSella ACCELA.conf
        wrote_accela = False
        where_accela = ""
        if key:
            wrote_accela, where_accela = paths.write_accela_api_key(key, self._home, timestamp=ts)

        if wrote_lua and wrote_accela:
            return True, f"Key saved to spacebunny.conf.lua and {where_accela}"
        if wrote_lua:
            return True, f"Key saved to {sb_path}"
        if wrote_accela:
            return True, where_accela
        return True, "Key saved to plugin settings"