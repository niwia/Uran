"""Thin Decky callable adapter; feature logic lives in the backend modules."""

_core = None


def bind_core(core) -> None:
    global _core
    _core = core


class Plugin:
    async def _main(self) -> None:
        core = _core
        core.logger.info("Uran plugin loaded")
        cache = core._manifest_cache_dir()
        depotcache = core._depotcache_dir()
        if depotcache and cache.exists():
            seeded = 0
            for manifest in cache.glob("*.manifest"):
                target = depotcache / manifest.name
                if not target.exists():
                    try:
                        core.shutil.copy2(manifest, target)
                        seeded += 1
                    except OSError:
                        pass
            if seeded:
                core.logger.info("Restored %s cached manifest(s) to depotcache", seeded)

    async def _unload(self) -> None:
        try:
            _core.stop_keycare_server()
        except Exception as e:
            _core.logger.debug("keycare cleanup on unload: %s", e)
        _core.logger.info("Uran plugin unloaded")

    async def _uninstall(self) -> None:
        path = _core._settings_path()
        path.unlink(missing_ok=True)
        _core.logger.info("Uran settings cleared on uninstall")

    async def discover_store_tab(self) -> dict | None:
        return _core.discover_store_tab()

    async def get_store_debug_status(self, refresh: bool = False) -> dict:
        return _core.get_store_debug_status(refresh)

    async def get_setting(self, key: str, default=None):
        return _core._get_setting(key, default)

    async def set_setting(self, key: str, value) -> None:
        _core._set_setting(key, value)

    async def read_clipboard(self) -> dict:
        return _core.read_clipboard()

    async def fe_debug(self, msg: str) -> None:
        _core._store_debugger.record_log(msg)
        _core.logger.debug("[FE] %s", msg)

    async def restart_steam(self) -> None:
        _core.restart_steam()

    async def search_games(self, query: str, limit: int = 20, appid: bool = False) -> dict:
        return _core.search_games(query, limit=limit, appid=appid)

    async def inject_game(self, app_id: str) -> dict:
        return _core.inject_game(app_id)

    async def get_inject_status(self, app_id: str) -> dict | None:
        return _core.get_inject_status(app_id)

    async def get_recent_injects(self) -> list[dict]:
        return _core.get_recent_injects()

    async def list_backups(self) -> list[dict]:
        return _core.list_backups()

    async def create_backup(self) -> str:
        return _core.create_backup("manual")

    async def restore_backup(self, backup_name: str) -> dict:
        return _core.restore_backup(backup_name)

    async def get_fake_app_ids(self) -> dict:
        return _core.get_fake_app_ids()

    async def add_fake_app_id(self, app_id: str) -> dict:
        return _core.add_fake_app_id(app_id)

    async def remove_fake_app_id(self, app_id: str) -> dict:
        return _core.remove_fake_app_id(app_id)

    async def fetch_dlcs_for_app(self, app_id: str) -> dict:
        return _core.fetch_dlcs_for_app(app_id)

    async def toggle_game_dlcs(self, app_id: str, enable: bool) -> dict:
        return _core.toggle_game_dlcs(app_id, enable)

    async def refetch_manifests(self, app_id: str) -> dict:
        return _core.refetch_manifests(app_id)

    async def remove_manifest_id_pins(self, app_id: str) -> dict:
        return _core.remove_manifest_id_pins(app_id)

    async def why_not_downloading(self, app_id: str) -> dict:
        return _core.why_not_downloading(app_id)

    async def send_notification(self, title: str, body: str) -> dict:
        try:
            _core.subprocess.run(["notify-send", title, body], timeout=2)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def get_hubcap_key_status(self) -> dict:
        return _core.get_hubcap_key_status()

    async def start_key_server(self) -> dict:
        return _core.start_keycare_server()

    async def key_server_status(self) -> dict:
        return _core.get_keycare_status()

    async def stop_key_server(self) -> dict:
        return _core.stop_keycare_server()

    async def validate_hubcap_key(self, key: str) -> dict:
        ok, message, detail = _core.validate_hubcap_key(key)
        return {"ok": ok, "message": message, "detail": detail}

    async def save_hubcap_key(self, key: str) -> dict:
        ok, message = _core.save_hubcap_key(key)
        return {"ok": ok, "message": message}

    async def get_hubcap_user_stats(self) -> dict:
        return _core.get_hubcap_user_stats()

    async def hubcap_manifest_contents(self, app_id: str) -> dict:
        return _core.hubcap_manifest_contents(app_id)

    async def list_plugin_games(self) -> dict:
        return {"ok": True, "games": _core.list_atom_games()}

    async def get_atom_game(self, app_id: str) -> dict:
        return _core.get_atom_game_detail(app_id)

    async def preview_atom_uninstall(self, app_id: str) -> dict:
        return _core.preview_atom_uninstall(app_id)

    async def uninstall_atom_game(self, app_id: str) -> dict:
        return _core.uninstall_atom_game(app_id)

    async def set_slsonline(self, app_id: str, enabled: bool, fake_appid: str = "480") -> dict:
        if _core.is_global_slsonline_enabled():
            return {"ok": False, "error": "Global SLS Online is active for all games"}
        if enabled:
            return _core.set_fake_appid(app_id, fake_appid or "480")
        _core.set_fake_appid(app_id, "")
        _core.set_netsock(app_id, False)
        return {"ok": True, "fake_appid": ""}

    async def toggle_additional_app(self, app_id: str, dlc_appid: str, enable: bool) -> dict:
        return _core.toggle_additional_app(app_id, dlc_appid, enable)

    async def is_global_slsonline_enabled(self) -> dict:
        return {"ok": True, "enabled": _core.is_global_slsonline_enabled()}

    async def set_global_slsonline(self, enabled: bool) -> dict:
        return _core.set_global_slsonline(enabled)

    async def set_netsock_toggle(self, app_id: str, enabled: bool) -> dict:
        return _core.set_netsock(app_id, enabled)

    async def set_eos_toggle(self, app_id: str, enabled: bool) -> dict:
        return _core.set_eos_proxy(app_id, enabled)

    async def set_eos_netsock(self, app_id: str, enabled: bool) -> dict:
        eos = _core.set_eos_proxy(app_id, enabled) if enabled else {"ok": True}
        net = _core.set_netsock(app_id, enabled)
        if not eos.get("ok"):
            return eos
        return net if not net.get("ok") else {"ok": True, "eos": True, "netsock": enabled}

    async def unregister_plugin_game(self, app_id: str) -> dict:
        return {"ok": _core.unregister_plugin_game(app_id)}

    async def get_notification_channel(self, gaming_ui: bool | None = None) -> dict:
        mode = _core._get_setting("notification_mode", "auto")
        if mode == "auto":
            channel = "steam" if (gaming_ui or _core.os.environ.get("SteamGamepadUI")) else "desktop"
        else:
            channel = mode
        return {"ok": True, "channel": channel}
