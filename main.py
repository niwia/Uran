"""Uran — Decky Loader plugin backend.

Composition root only: Decky imports this file and instantiates `Plugin`, which
delegates to the services built in uran_backend/.
"""

import sys
from pathlib import Path

# Decky Loader's sandboxed importlib runner does not add the plugin directory to
# sys.path, so subpackages (uran_backend) must be explicitly resolvable.
_PLUGIN_DIR = str(Path(__file__).parent.resolve())
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

try:
    import decky_plugin as decky
except ImportError:  # Decky injects this at runtime; absent in local tooling.
    decky = None

from uran_backend.plugin_api import Plugin  # noqa: E402

__all__ = ["Plugin"]