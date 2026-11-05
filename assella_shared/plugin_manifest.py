"""SLSsteam plugin set and ASSella's signed plugin manifest.

Uran only *checks* that the plugins are installed (ASSella installs them).
The manifest reader below is the same source of truth ASSella uses, so the
two tools can never disagree about which plugins exist - but it is switched
off (``MANIFEST_ENABLED = False``) until plugin distribution is stable.
While it is off, ``required_plugins()`` returns the built-in list.
"""

import base64
import json
import logging
import urllib.request

logger = logging.getLogger(__name__)

# Same as ASSella utils/plugin_manager.FALLBACK_REQUIRED_PLUGINS.
REQUIRED_PLUGINS = (
    "spacebunny.lua",
    "styx.lua",
    "lobster.lua",
    "katamari.lua",
    "lettuce.lua",
)

# Old names that count as the current plugin while users migrate.
LEGACY_NAMES = {
    "bypass.lua": "lettuce.lua",
}

# --- Signed manifest (DISABLED) ---------------------------------------------
MANIFEST_ENABLED = False

PLUGIN_SOURCES = (
    "https://pub-19657b4f385d424b91a909253efdb29c.r2.dev",
)
MANIFEST_FILENAME = "plugins_manifest.json"
SIGNATURE_SUFFIX = ".sig"
MANIFEST_PUBLIC_KEYS = (
    "QQxWspG4TVGY8se+6+/izUXy5v+7bg2dKqnrVi/s10k=",
)
MANIFEST_TIMEOUT = 6.0


def required_plugins() -> tuple:
    """The plugin files a working AT0-M setup needs."""
    if MANIFEST_ENABLED:
        manifest = fetch_manifest()
        if manifest:
            names = [
                name for name, meta in (manifest.get("plugins") or {}).items()
                if isinstance(meta, dict) and meta.get("required") and meta.get("deployable", True)
            ]
            if names:
                return tuple(sorted(names))
    return REQUIRED_PLUGINS


def missing_plugins(present_names) -> list:
    """Required plugins not present (legacy names count for their successor)."""
    present = {str(n) for n in present_names}
    present |= {new for old, new in LEGACY_NAMES.items() if old in present}
    return [name for name in required_plugins() if name not in present]


def verify_signature(manifest_bytes: bytes, signature: bytes) -> bool:
    """Ed25519 check against MANIFEST_PUBLIC_KEYS (needs `cryptography`)."""
    if not MANIFEST_ENABLED:
        return False
    sig = (signature or b"").strip()
    if len(sig) != 64:
        try:
            sig = base64.b64decode(sig, validate=True)
        except Exception:
            return False
    if len(sig) != 64:
        return False
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except Exception as exc:
        logger.error("cryptography unavailable, cannot verify the plugin manifest: %s", exc)
        return False
    for key in MANIFEST_PUBLIC_KEYS:
        try:
            raw = base64.b64decode(key)
            Ed25519PublicKey.from_public_bytes(raw).verify(sig, manifest_bytes)
            return True
        except InvalidSignature:
            continue
        except Exception as exc:
            logger.debug("Signature check error: %s", exc)
    return False


def _get(url: str) -> bytes:
    # Certificate checks are always on. There is deliberately no unverified
    # fallback: a manifest that cannot be fetched safely is not used.
    req = urllib.request.Request(url, headers={"User-Agent": "assella-shared/plugin-manifest"})
    with urllib.request.urlopen(req, timeout=MANIFEST_TIMEOUT) as resp:
        return resp.read(1 << 20)


def fetch_manifest():
    """The signed manifest from the first source that serves a valid one, else None."""
    if not MANIFEST_ENABLED:
        return None
    for base in PLUGIN_SOURCES:
        try:
            body = _get(f"{base}/{MANIFEST_FILENAME}")
            sig = _get(f"{base}/{MANIFEST_FILENAME}{SIGNATURE_SUFFIX}")
        except Exception as exc:
            logger.debug("Plugin manifest unavailable from %s: %s", base, exc)
            continue
        if not verify_signature(body, sig):
            logger.warning("Plugin manifest from %s failed signature verification", base)
            continue
        try:
            return json.loads(body.decode("utf-8"))
        except Exception:
            continue
    return None
