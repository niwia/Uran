"""Uran's adapter around the tool-neutral signed plugin manifest/install layer."""

from pathlib import Path

from assella_shared import plugin_install
from assella_shared.plugin_manifest import ManifestStore

from . import paths


class PluginManager:
    def __init__(self, ctx):
        self.ctx = ctx
        self.store = ManifestStore(ctx.runtime_dir / "plugins", ctx.plugin_dir / "plugins")

    def _manifest(self, refresh=False):
        manifest = self.store.load(force=refresh)
        if manifest is None:
            raise RuntimeError("No verified plugin manifest is available")
        return manifest

    def status(self, refresh=False):
        manifest = self._manifest(refresh)
        dirs = paths.sls_plugins_dirs(self.ctx.home)
        installed = {}
        for directory in dirs:
            for item in Path(directory).glob("*.lua"):
                installed[item.name] = item
        disabled = set(self.ctx.read_setting("disabled_plugins", []) or [])
        rows = []
        for name in manifest.names:
            meta = manifest.meta(name)
            path = installed.get(name)
            current_hash = plugin_install.sha256(path) if path else None
            if not path:
                state = "not_installed"
            elif current_hash != meta["sha256"]:
                state = "update_available"
            else:
                state = "installed"
            if name in disabled:
                state = "off"
            rows.append({"filename": name, "name": meta.get("name", name),
                         "version": str(meta.get("version", "")), "status": state,
                         "installed": bool(path), "enabled": name not in disabled,
                         "required": manifest.policy(name) == "required",
                         "deployable": manifest.is_deployable(name),
                         "category": meta.get("category", "")})
        return {"ok": True, "serial": manifest.serial, "source": manifest.source, "plugins": rows}

    def install(self, name):
        manifest = self._manifest()
        result = plugin_install.deploy_plugin(name, paths.sls_plugins_dirs(self.ctx.home),
                                              self.ctx.runtime_dir / "plugins" / "files", manifest)
        disabled = set(self.ctx.read_setting("disabled_plugins", []) or [])
        disabled.discard(name)
        self.ctx.write_setting("disabled_plugins", sorted(disabled))
        return result

    def set_enabled(self, name, enabled):
        manifest = self._manifest()
        if not manifest.meta(name):
            raise ValueError("Unknown plugin")
        disabled = set(self.ctx.read_setting("disabled_plugins", []) or [])
        if enabled:
            disabled.discard(name)
            if not any((Path(d) / name).is_file() for d in paths.sls_plugins_dirs(self.ctx.home)):
                return self.install(name)
        else:
            if manifest.policy(name) == "required":
                raise ValueError("Required plugins cannot be disabled")
            disabled.add(name)
            plugin_install.undeploy_plugin(name, paths.sls_plugins_dirs(self.ctx.home))
        self.ctx.write_setting("disabled_plugins", sorted(disabled))
        return {"ok": True, "filename": name, "enabled": enabled}

    def remove(self, name):
        manifest = self._manifest()
        if manifest.policy(name) == "required":
            raise ValueError("Required plugins cannot be removed")
        result = plugin_install.undeploy_plugin(name, paths.sls_plugins_dirs(self.ctx.home))
        return result

    def install_essentials(self):
        manifest = self._manifest()
        results = [self.install(name) for name in manifest.required_plugins()]
        return {"ok": True, "results": results}
