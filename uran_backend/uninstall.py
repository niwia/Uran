"""AT0-M uninstall operations."""

import logging
from pathlib import Path
import shutil

from .context import Context
from .integrations import Integrations
from .library import PluginLibrary
from .sls_config import SlsConfig, sanitize_id, signal_api
from .steammeta import SteamMeta

logger = logging.getLogger("Uran")


class AtomUninstallService:
    """Run uninstall operations through the shared Uran backend services."""

    def __init__(self, ctx: Context, sls: SlsConfig, steam: SteamMeta,
                 library: PluginLibrary, integrations: Integrations, guards):
        self.ctx = ctx
        self.sls = sls
        self.steam = steam
        self.library = library
        self.integrations = integrations
        self.guards = guards

    def preview(self, app_id: str) -> dict:
        aid = sanitize_id(app_id)
        if not aid:
            return {"ok": False, "error": "Invalid AppID"}

        env = self.guards.check_sls_environment()
        if not env.get("ok"):
            return {"ok": False, "error": env.get("error", "SLS environment check failed")}

        install = self.steam.install_info(aid)
        targets = []
        install_path = install.get("install_path") or ""
        if install_path and Path(install_path).exists():
            targets.append(install_path)
        library_path = install.get("library_path") or ""
        if library_path:
            for extra in (
                Path(library_path) / "steamapps" / "downloading" / aid,
                Path(library_path) / "steamapps" / "temp" / aid,
                Path(library_path) / "steamapps" / f"appmanifest_{aid}.acf",
                Path(library_path) / "steamapps" / "compatdata" / aid,
            ):
                if extra.exists():
                    targets.append(str(extra))
        for library in self.steam.libraries():
            for extra in (
                library / "steamapps" / "compatdata" / aid,
                library / "userdata" / aid,
            ):
                target = str(extra)
                if extra.is_dir() and target not in targets:
                    targets.append(target)
        return {
            "ok": True,
            "app_id": aid,
            "name": (self.library.load().get(aid) or {}).get("name") or f"App {aid}",
            "targets": targets,
            "installed": bool(install.get("installed")),
        }

    def uninstall(self, app_id: str) -> dict:
        aid = sanitize_id(app_id)
        if not aid:
            return {"ok": False, "error": "Invalid AppID"}

        env = self.guards.check_sls_environment()
        if not env.get("ok"):
            return {"ok": False, "error": env.get("error", "SLS environment check failed")}

        preview = self.preview(aid)
        if not preview.get("ok"):
            return preview
        install = self.steam.install_info(aid)

        self.sls.create_backup("pre_uninstall")
        signal_api(f"uninstall|{aid}")

        removed, failed = [], []
        install_path = install.get("install_path") or ""
        if install_path and Path(install_path).is_dir():
            try:
                self.integrations.remove_eos_proxy(Path(install_path))
            except Exception as e:
                logger.warning("Could not restore EOS files before uninstall of %s: %s", aid, e)

        for target in preview.get("targets", []):
            path = Path(target)
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.exists():
                    path.unlink()
                removed.append(target)
            except Exception as e:
                failed.append(f"{target}: {e}")
                logger.error("Uninstall failed on %s: %s", target, e)

        config_cleaned = self.library.unregister(aid)
        still_registered = aid in (self.library.load() or {})
        return {
            "ok": not failed and config_cleaned and not still_registered,
            "app_id": aid,
            "removed": removed,
            "failed": failed,
            "config_cleaned": config_cleaned,
            "registered": still_registered,
        }