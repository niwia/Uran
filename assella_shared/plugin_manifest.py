"""SLSsteam plugin set and ASSella's signed plugin manifest.

The manifest is the single source of truth for which plugins exist, which are
required, which retired into which successor, and the SHA-256 of each file.
Uran both *checks* plugins against it and installs from it, and ASSella uses
the same model, so the two tools can never disagree.

Loading is a three-tier fallback so the plugin set is always available: the
newest verified copy reachable over the network, else the newest verified copy
on disk under the cache directory, else the copy bundled with the plugin. A
manifest is only ever used after its Ed25519 signature verifies against
``MANIFEST_PUBLIC_KEYS`` and only when its serial is not older than the best
copy already on hand, so a stale or downgraded origin cannot roll us back.
"""

import base64
import json
import logging
import re
import threading
import time
import urllib.request
from pathlib import Path

from . import ed25519

logger = logging.getLogger("assella_shared.plugin_manifest")

PLUGIN_SOURCES = (
    "https://pub-19657b4f385d424b91a909253efdb29c.r2.dev",
)
MANIFEST_FILENAME = "plugins_manifest.json"
SIGNATURE_SUFFIX = ".sig"
MANIFEST_PUBLIC_KEYS = (
    "QQxWspG4TVGY8se+6+/izUXy5v+7bg2dKqnrVi/s10k=",
)
MANIFEST_TIMEOUT = 6.0
MANIFEST_MEMO_TTL = 900.0
UNREACHABLE_MEMO_TTL = 120.0
MAX_MANIFEST_BYTES = 1 << 20

# How a plugin should be treated, in the order the questions are asked.
POLICY_REQUIRED = "required"          # always installed
POLICY_DEFAULT_ON = "default_on"      # installed unless the user turned it off
POLICY_OPTIONAL = "optional"          # installed only when already present
POLICY_UNAVAILABLE = "unavailable"    # held back or retired: never installed

# Used as safety fallback if a manifest is completely empty or missing
FALLBACK_REQUIRED_PLUGINS = (
    "spacebunny.lua",
    "styx.lua",
    "lobster.lua",
)


def verify_signature(manifest_bytes: bytes, signature: bytes) -> bool:
    """Ed25519 check of a manifest body against every known public key."""
    sig = (signature or b"").strip()
    if len(sig) != 64:
        try:
            sig = base64.b64decode(sig, validate=True)
        except Exception:  # noqa: BLE001 - not valid base64, so not a signature
            return False
    if len(sig) != 64:
        return False
    for key in MANIFEST_PUBLIC_KEYS:
        try:
            raw = base64.b64decode(key)
        except Exception:  # noqa: BLE001 - a bad configured key is skipped
            continue
        if ed25519.verify(raw, sig, manifest_bytes):
            return True
    return False


def _http_get(url: str) -> bytes:
    # Certificate checks are always on. There is deliberately no unverified
    # fallback: a manifest that cannot be fetched safely is not used.
    request = urllib.request.Request(url, headers={"User-Agent": "assella-shared/plugin-manifest"})
    with urllib.request.urlopen(request, timeout=MANIFEST_TIMEOUT) as response:
        return response.read(MAX_MANIFEST_BYTES)


def _valid_manifest_shape(data) -> bool:
    if not isinstance(data, dict):
        return False
    plugins = data.get("plugins")
    if not isinstance(plugins, dict) or not plugins:
        return False
    for name, meta in plugins.items():
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+\.lua", name)
                or not isinstance(meta, dict)):
            return False
        sha = meta.get("sha256")
        if not isinstance(sha, str) or len(sha) != 64:
            return False
        try:
            int(sha, 16)
        except ValueError:
            return False
    return True


def manifest_serial(data: dict) -> int:
    """Monotonic manifest serial, used to reject a rolled-back manifest."""
    try:
        return int(data.get("serial"))
    except (TypeError, ValueError):
        pass
    stamp = str(data.get("updated_at") or "")
    digits = "".join(ch for ch in stamp if ch.isdigit())
    return int(digits[:14]) if len(digits) >= 14 else 0


class Manifest:
    """A verified plugin manifest and the questions callers ask of it."""

    def __init__(self, data: dict, source: str, base_url: str | None = None):
        self.data = data
        self.source = source          # "remote", "cache" or "bundled"
        self.base_url = base_url      # only a remote manifest can be downloaded from
        self.bundled_dir = None
        self._entries = {
            key: value for key, value in (data.get("plugins") or {}).items()
            if isinstance(value, dict)
        }

    # -- identity -----------------------------------------------------------
    @property
    def serial(self) -> int:
        return manifest_serial(self.data)

    @property
    def entries(self) -> dict:
        return self._entries

    @property
    def names(self) -> list:
        return sorted(self._entries)

    @property
    def retired(self) -> dict:
        """old filename -> successor filename (or None when it is just gone)."""
        retired = {}
        for old, meta in (self.data.get("retired") or {}).items():
            successor = meta.get("replaced_by") if isinstance(meta, dict) else None
            retired[str(old)] = str(successor) if successor else None
        return retired

    @property
    def default_interceptor(self) -> str | None:
        value = self.data.get("default_interceptor")
        return str(value) if value else None

    # -- per-plugin ---------------------------------------------------------
    def meta(self, name: str) -> dict | None:
        return self._entries.get(name)

    def is_deployable(self, name: str) -> bool:
        meta = self._entries.get(name)
        return bool(meta and meta.get("deployable", True))

    def policy(self, name: str) -> str:
        meta = self._entries.get(name)
        if not meta or not self.is_deployable(name):
            return POLICY_UNAVAILABLE
        if meta.get("required"):
            return POLICY_REQUIRED
        if meta.get("default_on"):
            return POLICY_DEFAULT_ON
        return POLICY_OPTIONAL

    def is_wanted(self, name: str, installed: bool, disabled: bool) -> bool:
        """Whether the plugin belongs in the plugin directory right now."""
        policy = self.policy(name)
        if policy == POLICY_REQUIRED:
            return True
        if policy == POLICY_DEFAULT_ON:
            return not disabled
        if policy == POLICY_OPTIONAL:
            return installed and not disabled
        return False

    def required_plugins(self) -> list:
        names = [name for name in self.names if self.policy(name) == POLICY_REQUIRED]
        if names:
            return names
        return [name for name in FALLBACK_REQUIRED_PLUGINS if self.is_deployable(name)]

    def interceptor_names(self) -> list:
        return [
            name for name in self.names
            if (self._entries[name].get("category") or "") == "interceptor"
        ]


class ManifestStore:
    """Fetches, verifies and caches a manifest, preferring the newest copy."""

    def __init__(self, cache_dir: Path, bundled_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.bundled_dir = Path(bundled_dir)
        self._lock = threading.Lock()
        self._manifest: Manifest | None = None
        self._expires_at = 0.0

    def load(self, force: bool = False) -> Manifest | None:
        with self._lock:
            now = time.time()
            if not force and self._manifest is not None and now < self._expires_at:
                return self._manifest
            manifest = self._fetch_remote(self._newest_local()) or self._newest_local()
            self._manifest = manifest
            # A network manifest is trusted for the full window; a local
            # fallback is retried sooner, so a recovery is picked up quickly.
            ttl = MANIFEST_MEMO_TTL if manifest and manifest.source == "remote" else UNREACHABLE_MEMO_TTL
            self._expires_at = now + ttl
            return manifest

    def load_local(self) -> Manifest | None:
        """The newest manifest on disk (cache or bundled), without the network."""
        with self._lock:
            return self._newest_local()

    def _newest_local(self) -> Manifest | None:
        best = None
        for source, path in (("cache", self.cache_dir / MANIFEST_FILENAME),
                             ("bundled", self.bundled_dir / MANIFEST_FILENAME)):
            manifest = self._read_local(source, path)
            if manifest is not None and (best is None or manifest.serial > best.serial):
                best = manifest
        return best

    def _read_local(self, source: str, path: Path) -> Manifest | None:
        try:
            if not path.is_file():
                return None
            body = path.read_bytes()
            signature = path.with_name(path.name + SIGNATURE_SUFFIX).read_bytes()
            if not verify_signature(body, signature):
                logger.warning("Ignoring unsigned or invalid %s manifest %s", source, path)
                return None
            data = json.loads(body.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - any bad file is simply ignored
            logger.debug("Ignoring unreadable %s manifest %s: %s", source, path, exc)
            return None
        if not _valid_manifest_shape(data):
            logger.warning("Ignoring malformed %s manifest %s", source, path)
            return None
        manifest = Manifest(data, source, PLUGIN_SOURCES[0] if source == "cache" else None)
        manifest.bundled_dir = self.bundled_dir
        return manifest

    def _fetch_remote(self, floor: Manifest | None) -> Manifest | None:
        for base in PLUGIN_SOURCES:
            try:
                body = _http_get(f"{base}/{MANIFEST_FILENAME}")
                signature = _http_get(f"{base}/{MANIFEST_FILENAME}{SIGNATURE_SUFFIX}")
            except Exception as exc:  # noqa: BLE001 - try the next source
                logger.debug("Plugin manifest unavailable from %s: %s", base, exc)
                continue
            if not verify_signature(body, signature):
                logger.warning("Plugin manifest from %s failed signature verification", base)
                continue
            try:
                data = json.loads(body.decode("utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if not _valid_manifest_shape(data):
                logger.warning("Plugin manifest from %s is malformed", base)
                continue
            candidate = Manifest(data, "remote", base)
            candidate.bundled_dir = self.bundled_dir
            if floor is not None and candidate.serial < floor.serial:
                logger.warning(
                    "Ignoring plugin manifest serial %s older than the local %s",
                    candidate.serial, floor.serial,
                )
                continue
            self._write_cache(body, signature)
            return candidate
        return None

    def _write_cache(self, body: bytes, signature: bytes) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_dir / (MANIFEST_FILENAME + ".tmp")
            tmp.write_bytes(body)
            tmp.replace(self.cache_dir / MANIFEST_FILENAME)
            sig_tmp = self.cache_dir / (MANIFEST_FILENAME + SIGNATURE_SUFFIX + ".tmp")
            sig_tmp.write_bytes(signature)
            sig_tmp.replace(self.cache_dir / (MANIFEST_FILENAME + SIGNATURE_SUFFIX))
        except OSError as exc:
            logger.debug("Could not cache the plugin manifest: %s", exc)
