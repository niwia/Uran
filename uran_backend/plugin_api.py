"""Decky callable surface.

These method names and signatures ARE the plugin's RPC contract: the frontend
resolves `callable("inject_game")` against them, so they must stay stable even
as the implementation moves behind them. Everything here is a thin delegation.
"""

import asyncio
import logging
import os
import shutil
import subprocess

logger = logging.getLogger("Uran")

_services = None


def default_services(decky_module=None) -> "Services":
    """Build the service graph on first use.

    Imported lazily so `main.py` stays a thin composition root and this module
    has no import-time dependency on the concrete services.
    """
    global _services
    if _services is None:
        from uran_backend import services

        _services = services.build(decky_module)
    return _services


class Services:
    """Everything the RPC surface needs, wired once at startup."""

    def __init__(self, ctx, sls, steam, library, manifests, integrations,
                 injector, guards, keycare, store_debugger, atom, uninstaller,
                 health=None, plugin_deployer=None):
        self.ctx = ctx
        self.sls = sls
        self.steam = steam
        self.library = library
        self.manifests = manifests
        self.integrations = integrations
        self.injector = injector
        self.guards = guards
        self.keycare = keycare
        self.store_debugger = store_debugger
        self.atom = atom
        self.uninstaller = uninstaller
        self.health = health
        self.plugin_deployer = plugin_deployer


class Plugin:
    """Decky instantiates this with no arguments; services arrive via a default."""

    def __init__(self, services: "Services | None" = None, decky_module=None):
        self.s = services if services is not None else default_services(decky_module)

    async def _main(self) -> None:
        ctx = self.s.ctx
        logger.info("Uran plugin loaded")
        # Restore any manifests we cached last session into depotcache.
        cache = ctx.manifest_cache_dir()
        depotcache = ctx.depotcache()
        if depotcache and cache.exists():
            seeded = 0
            for manifest in cache.glob("*.manifest"):
                target = depotcache / manifest.name
                if not target.exists():
                    try:
                        shutil.copy2(manifest, target)
                        seeded += 1
                    except OSError:
                        pass
            if seeded:
                logger.info("Restored %s cached manifest(s) to depotcache", seeded)

        # Check and auto-deploy default interceptor (SpaceBunny) if none is present
        if self.s.plugin_deployer:
            try:
                await asyncio.to_thread(self.s.plugin_deployer.ensure_default_interceptor)
                await asyncio.to_thread(self.s.plugin_deployer.sync_spacebunny_conf)
            except Exception as exc:
                logger.warning("Plugin deployer initialization check failed: %s", exc)

    async def _unload(self) -> None:
        try:
            self.s.keycare.stop()
        except Exception as exc:  # noqa: BLE001
            logger.debug("keycare cleanup on unload: %s", exc)
        logger.info("Uran plugin unloaded")

    async def _uninstall(self) -> None:
        self.s.keycare.stop()
        self.s.ctx.settings.path.unlink(missing_ok=True)
        logger.info("Uran settings cleared on uninstall")

    # -- diagnostics ---------------------------------------------------------
    async def discover_store_tab(self) -> dict | None:
        return self.s.store_debugger.discover()

    async def get_store_debug_status(self, refresh: bool = False) -> dict:
        return self.s.store_debugger.status(refresh)

    async def fe_debug(self, msg: str) -> None:
        self.s.store_debugger.record_log(msg)
        logger.debug("[FE] %s", msg)

    async def read_clipboard(self) -> dict:
        """Read clipboard text using wl-paste or xclip."""
        for cmd in (["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"]):
            try:
                result = subprocess.run(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=2
                )
                if result.returncode == 0 and result.stdout:
                    return {"ok": True, "text": result.stdout.strip()}
            except Exception:  # noqa: BLE001
                continue
        return {"ok": False, "error": "Clipboard unavailable"}

    # -- settings ------------------------------------------------------------
    async def get_setting(self, key: str, default=None):
        return self.s.ctx.read_setting(key, default)

    async def set_setting(self, key: str, value) -> None:
        self.s.ctx.write_setting(key, value)

    async def get_plugin_info(self) -> dict:
        from .updates import plugin_info

        return plugin_info(self.s.ctx)

    async def get_sls_plugin_deploy_status(self) -> dict:
        if self.s.plugin_deployer is None:
            return {"ok": False, "error": "Plugin deployment is unavailable."}
        return await asyncio.to_thread(self.s.plugin_deployer.status)

    async def deploy_sls_plugin(self, filename: str) -> dict:
        if self.s.plugin_deployer is None:
            return {"ok": False, "error": "Plugin deployment is unavailable."}
        return await asyncio.to_thread(self.s.plugin_deployer.deploy, filename)

    async def enable_sls_plugin(self, filename: str) -> dict:
        """Enable a previously disabled plugin."""
        if self.s.plugin_deployer is None:
            return {"ok": False, "error": "Plugin deployment is unavailable."}
        return await asyncio.to_thread(self.s.plugin_deployer.enable_plugin, filename)

    async def disable_sls_plugin(self, filename: str) -> dict:
        """Disable a plugin so it won't be auto-deployed on startup."""
        if self.s.plugin_deployer is None:
            return {"ok": False, "error": "Plugin deployment is unavailable."}
        return await asyncio.to_thread(self.s.plugin_deployer.disable_plugin, filename)

    async def check_for_updates(self) -> dict:
        from .updates import check_for_updates

        return await asyncio.to_thread(check_for_updates, self.s.ctx)

    # -- search & inject -----------------------------------------------------
    async def search_games(self, query: str, limit: int = 20, appid: bool = False) -> dict:
        return await asyncio.to_thread(self.s.steam.search, query, limit, appid)

    async def inject_game(self, app_id: str) -> dict:
        return self.s.injector.inject(app_id)

    async def get_inject_status(self, app_id: str) -> dict | None:
        return self.s.injector.status(app_id)

    async def get_recent_injects(self) -> list[dict]:
        return self.s.injector.recent()

    async def fetch_dlcs_for_app(self, app_id: str) -> dict:
        return await asyncio.to_thread(self.s.injector.fetch_dlcs, app_id)

    async def toggle_game_dlcs(self, app_id: str, enable: bool) -> dict:
        return await asyncio.to_thread(self.s.injector.toggle_dlcs, app_id, enable)

    async def toggle_additional_app(self, app_id: str, dlc_appid: str, enable: bool) -> dict:
        return await asyncio.to_thread(self.s.injector.toggle_additional_app, app_id, dlc_appid, enable)

    async def toggle_additional_depot(self, app_id: str, depot_id: str, enable: bool) -> dict:
        return await asyncio.to_thread(self.s.injector.toggle_additional_depot, app_id, depot_id, enable)

    async def toggle_decryption_key(self, app_id: str, target_id: str, enable: bool) -> dict:
        return await asyncio.to_thread(self.s.injector.toggle_decryption_key, app_id, target_id, enable)

    async def refresh_game(self, app_id: str) -> dict:
        """Re-project a game's config from the freshest keys/depots.

        The base game stays on and enabled DLCs are preserved; this is how a
        freshly fetched base-game key gets its depot mounted.
        """
        return await asyncio.to_thread(self.s.injector.refresh, app_id)

    async def refetch_game(self, app_id: str) -> dict:
        """Force-fetch freshest Hubcap bundle and inject full configuration."""
        return await asyncio.to_thread(self.s.injector.refetch_game, app_id)

    async def apply_depot_selection(
        self,
        app_id: str,
        depot_ids: list | None = None,
        dlc_ids: list | None = None,
        key_ids: list | None = None,
    ) -> dict:
        """Mount exactly the ticked depot/DLC/key set (the Advanced selector's Apply)."""
        return await asyncio.to_thread(
            self.s.injector.apply_depot_selection,
            app_id,
            depot_ids,
            dlc_ids,
            key_ids,
        )

    # -- backups -------------------------------------------------------------
    async def list_backups(self) -> list[dict]:
        return self.s.sls.list_backups()

    async def create_backup(self) -> str:
        return self.s.sls.create_backup("manual")

    async def restore_backup(self, backup_name: str) -> dict:
        return await asyncio.to_thread(self.s.sls.restore_backup, backup_name)

    # -- library / FakeAppIds ------------------------------------------------
    async def get_fake_app_ids(self) -> dict:
        return self.s.integrations.list_fake_app_ids()

    async def add_fake_app_id(self, app_id: str) -> dict:
        return self.s.integrations.add_fake_app_id(app_id)

    async def remove_fake_app_id(self, app_id: str) -> dict:
        return self.s.integrations.remove_fake_app_id(app_id)

    async def is_app_added(self, app_id: str) -> bool:
        return self.s.guards.is_app_added(app_id)

    async def get_added_app_ids(self) -> list[str]:
        return self.s.guards.get_added_app_ids()

    async def why_not_downloading(self, app_id: str) -> dict:
        from .manifests import configured_depot_keys

        ctx = self.s.ctx
        cfg = ctx.sls_config()
        if not cfg or not cfg.exists():
            return {"ok": False, "message": "SLS config.yaml not found"}
        configured_keys = configured_depot_keys(ctx)["keys"]
        details = self.s.steam.app_details(str(app_id))
        depots = details.get("depots", [])
        missing = [d for d in depots if d not in configured_keys]
        msg = f"App {app_id}: {len(depots)} depot(s)."
        if missing:
            msg += f" {len(missing)} depot(s) lack decryption keys."
        else:
            msg += " All depots have decryption keys."
        return {"ok": True, "message": msg}

    # -- manifests -----------------------------------------------------------
    async def refetch_manifests(self, app_id: str) -> dict:
        return await asyncio.to_thread(self.s.manifests.refetch, app_id)

    async def remove_manifest_id_pins(self, app_id: str) -> dict:
        return self.s.manifests.remove_pins(app_id)

    async def hubcap_manifest_contents(self, app_id: str) -> dict:
        return await asyncio.to_thread(self.s.manifests.contents, app_id)

    async def get_hubcap_routes(self) -> dict:
        """Current gateway mode and whether each route is reachable."""
        return await asyncio.to_thread(self.s.manifests.route_status)

    async def test_hubcap_routes(self) -> dict:
        """Actively probe both routes and report the result."""
        return await asyncio.to_thread(self.s.manifests.probe_routes)

    # -- Hubcap key ----------------------------------------------------------
    async def get_hubcap_key_status(self) -> dict:
        return self.s.keycare.key_status()

    async def start_key_server(self) -> dict:
        return self.s.keycare.start()

    async def key_server_status(self) -> dict:
        return self.s.keycare.status()

    async def stop_key_server(self) -> dict:
        return self.s.keycare.stop()

    async def validate_hubcap_key(self, key: str) -> dict:
        ok, message, detail = await asyncio.to_thread(self.s.keycare.validate, key)
        return {"ok": ok, "message": message, "detail": detail}

    async def save_hubcap_key(self, key: str) -> dict:
        ok, message = await asyncio.to_thread(self.s.keycare.save, key)
        return {"ok": ok, "message": message}

    async def get_hubcap_user_stats(self) -> dict:
        return await asyncio.to_thread(self.s.keycare.user_stats)

    # -- AT0-M library -------------------------------------------------------
    async def list_plugin_games(self) -> dict:
        return {"ok": True, "games": self.s.atom.list_games()}

    async def get_atom_game(self, app_id: str) -> dict:
        """Local-only detail page — never blocks on Steam's network."""
        return await asyncio.to_thread(self.s.atom.detail, app_id, False)

    async def refresh_atom_meta(self, app_id: str) -> dict:
        """Same page, with freshly fetched Steam metadata (full DLC list)."""
        return await asyncio.to_thread(self.s.atom.detail, app_id, True)

    async def check_atom_game_updates(self, app_id: str) -> dict:
        return await asyncio.to_thread(self.s.atom.check_updates, app_id)

    async def check_all_atom_updates(self) -> dict:
        return await asyncio.to_thread(self.s.atom.check_all_updates)

    async def preview_atom_uninstall(self, app_id: str) -> dict:
        return await asyncio.to_thread(self.s.uninstaller.preview, app_id)
    async def uninstall_atom_game(self, app_id: str) -> dict:
        return await asyncio.to_thread(self.s.uninstaller.uninstall, app_id)

    # -- health (read-only) --------------------------------------------------
    async def get_health_status(self) -> dict:
        return await asyncio.to_thread(self.s.health.status)

    async def check_config_status(self, online: bool = True) -> dict:
        return await asyncio.to_thread(self.s.health.check_config, online)

    async def set_slsonline(self, app_id: str, enabled: bool, fake_appid: str = "480") -> dict:
        if self.s.integrations.global_slsonline_enabled():
            return {"ok": False, "error": "Global SLS Online is active for all games"}
        if enabled:
            return self.s.integrations.set_fake_appid(app_id, fake_appid or "480")
        self.s.integrations.set_fake_appid(app_id, "")
        self.s.integrations.set_netsock(app_id, False)
        return {"ok": True, "fake_appid": ""}

    async def is_global_slsonline_enabled(self) -> dict:
        config = self.s.integrations.ctx.sls_config()
        return {
            "ok": True,
            "enabled": self.s.integrations.global_slsonline_enabled(),
            "config_path": str(config) if config and config.is_file() else "",
        }

    async def set_global_slsonline(self, enabled: bool) -> dict:
        return self.s.integrations.set_global_slsonline(enabled)

    async def set_netsock_toggle(self, app_id: str, enabled: bool) -> dict:
        return await asyncio.to_thread(self.s.integrations.set_netsock, app_id, enabled)

    async def set_eos_toggle(self, app_id: str, enabled: bool) -> dict:
        return await asyncio.to_thread(self.s.integrations.set_eos_proxy, app_id, enabled)

    async def set_eos_netsock(self, app_id: str, enabled: bool) -> dict:
        eos = await asyncio.to_thread(self.s.integrations.set_eos_proxy, app_id, enabled) if enabled else {"ok": True}
        net = await asyncio.to_thread(self.s.integrations.set_netsock, app_id, enabled)
        if not eos.get("ok"):
            return eos
        return net if not net.get("ok") else {"ok": True, "eos": True, "netsock": enabled}

    async def unregister_plugin_game(self, app_id: str) -> dict:
        return {"ok": self.s.library.unregister(app_id)}

    # -- notifications -------------------------------------------------------
    async def send_notification(self, title: str, body: str) -> dict:
        try:
            subprocess.run(["notify-send", title, body], timeout=2)
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    async def get_notification_channel(self, gaming_ui: bool | None = None) -> dict:
        mode = self.s.ctx.read_setting("notification_mode", "auto")
        if mode == "auto":
            channel = "steam" if (gaming_ui or os.environ.get("SteamGamepadUI")) else "desktop"
        else:
            channel = mode
        return {"ok": True, "channel": channel}
