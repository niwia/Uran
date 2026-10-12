"""Shared service wiring.

Every module that needs another service receives it through this object, so
dependencies are explicit and a renamed attribute fails at import time rather
than at the first call on a user's Deck.
"""

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from . import paths
from .settings import HubcapKey, Settings

logger = logging.getLogger("Uran")


@dataclass
class Context:
    """Environment discovery plus the services that hang off it."""

    home: Path
    settings: Settings
    hubcap_key: HubcapKey
    plugin_dir: Path
    runtime_dir: Path

    # Guards config.yaml writes and SLSsteam reload notifications.
    sls_lock: threading.Lock = field(default_factory=threading.Lock)

    # Cross-injection state.
    recent_injects: list = field(default_factory=list)
    inject_status: dict = field(default_factory=dict)
    depot_names: dict = field(default_factory=dict)

    store_details_cache: dict = field(default_factory=dict)
    steamcmd_details_cache: dict = field(default_factory=dict)

    def sls_config(self) -> Path | None:
        return paths.sls_config(self.home)

    def steam_root(self) -> Path | None:
        return paths.steam_root(self.home)

    def depotcache(self) -> Path | None:
        return paths.depotcache(self.home)

    def accela_base(self) -> Path:
        return paths.accela_base(self.home)

    def manifest_cache_dir(self) -> Path:
        cache = self.runtime_dir / "manifests"
        cache.mkdir(parents=True, exist_ok=True)
        return cache

    def manifest_zip_path(self, app_id: str) -> Path:
        return self.manifest_cache_dir() / f"{app_id}.zip"

    def read_setting(self, key: str, default=None):
        return self.settings.get(key, default)

    def write_setting(self, key: str, value) -> None:
        self.settings.set(key, value)


def _first_existing(*candidates) -> Path | None:
    """First non-empty candidate, coerced to Path.

    Decky exposes its environment as plain strings, so every candidate is
    wrapped before use rather than assumed to be a Path already.
    """
    for candidate in candidates:
        if candidate:
            return Path(candidate)
    return None


def build_context(decky_module=None) -> Context:
    """Discover the Decky runtime environment and construct the services."""
    settings_dir = _first_existing(
        getattr(decky_module, "DECKY_PLUGIN_SETTINGS_DIR", None),
        getattr(decky_module, "DECKY_SETTINGS_DIR", None),
        Path.home() / ".config" / "assella-decky",
    )
    if settings_dir is None:
        settings_dir = Path.home() / ".config" / "assella-decky"
    settings_dir.mkdir(parents=True, exist_ok=True)

    plugin_dir = _first_existing(
        getattr(decky_module, "DECKY_PLUGIN_DIR", None),
        Path(os.environ.get("DECKY_PLUGIN_DIR", "")) if os.environ.get("DECKY_PLUGIN_DIR") else None,
        Path(__file__).resolve().parent.parent,
    ) or Path(__file__).resolve().parent.parent

    runtime_dir = _first_existing(
        getattr(decky_module, "DECKY_PLUGIN_RUNTIME_DIR", None),
        settings_dir,
    ) or settings_dir
    runtime_dir.mkdir(parents=True, exist_ok=True)

    home = paths.user_home(getattr(decky_module, "DECKY_USER_HOME", None))
    settings = Settings(settings_dir)

    return Context(
        home=home,
        settings=settings,
        hubcap_key=HubcapKey(settings, home),
        plugin_dir=plugin_dir,
        runtime_dir=runtime_dir,
    )