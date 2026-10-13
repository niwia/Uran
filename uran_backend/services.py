"""Composition root: builds the service graph."""

import logging

from .atom import AtomLibrary
from .context import build_context
from .guards import GuardService
from .health import Health
from .http import HAS_REQUESTS, requests
from .inject import Injector
from .integrations import Integrations
from .keycare import Keycare
from .library import PluginLibrary
from .manifests import Manifests
from .sls_config import SlsConfig
from .steam_store import StoreDebugger
from .steammeta import SteamMeta
from .uninstall import AtomUninstallService

logger = logging.getLogger("Uran")


class _ServiceBag:
    """The services GuardService needs, without a circular import."""

    def __init__(self, ctx, sls, steam, library, manifests, integrations):
        self.ctx = ctx
        self.sls = sls
        self.steam = steam
        self.library = library
        self.manifests = manifests
        self.integrations = integrations


def _load_decky():
    """Import Decky's injected module, or None when running outside Decky.

    Decky calls `Plugin()` with no arguments, so the module has to be resolved
    here rather than threaded in from the caller.
    """
    try:
        import decky_plugin  # type: ignore

        return decky_plugin
    except ImportError:
        return None


def build(decky_module=None):
    """Construct every service and return a `plugin_api.Services`."""
    ctx = build_context(decky_module if decky_module is not None else _load_decky())

    sls = SlsConfig(ctx)
    steam = SteamMeta(ctx)
    library = PluginLibrary(ctx, sls)
    manifests = Manifests(ctx, sls, steam, library)
    integrations = Integrations(ctx, sls, steam)

    # Guards reach across services, so they are constructed after them.
    guards = GuardService(_ServiceBag(ctx, sls, steam, library, manifests, integrations))

    injector = Injector(ctx, sls, steam, library, manifests, guards)
    keycare = Keycare(ctx)
    store_debugger = StoreDebugger(requests, logger)
    atom = AtomLibrary(ctx, sls, steam, library, manifests, integrations)
    uninstaller = AtomUninstallService(ctx, sls, steam, library, integrations, guards)
    health = Health(ctx, sls)

    from .plugin_api import Services

    logger.debug("Uran services built (HTTP client: %s)", "requests" if HAS_REQUESTS else "urllib shim")
    return Services(
        ctx=ctx,
        sls=sls,
        steam=steam,
        library=library,
        manifests=manifests,
        integrations=integrations,
        injector=injector,
        guards=guards,
        keycare=keycare,
        store_debugger=store_debugger,
        atom=atom,
        uninstaller=uninstaller,
        health=health,
    )