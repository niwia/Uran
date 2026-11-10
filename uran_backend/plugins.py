"""Uran's adapter around the tool-neutral signed plugin manifest/install layer."""

from pathlib import Path

from assella_shared import plugin_install
from assella_shared.plugin_manifest import ManifestStore

from . import paths


class PluginManager:
    def __init__(self, ctx, guards=None):
        self.ctx = ctx
        self.guards = guards
        self.store = ManifestStore(ctx.runtime_dir / "plugins", ctx.plugin_dir / "plugins")

    # -- internals -----------------------------------------------------------
    def _manifest(self, refresh=False):
        manifest = self.store.load(force=refresh)
        if manifest is None:
            raise RuntimeError("No verified plugin manifest is available")
        return manifest

    def _local_manifest(self):
        manifest = self.store.load_local()
        if manifest is None:
            raise RuntimeError("No verified plugin manifest is available")
        return manifest

    def _named(self, manifest, name):
        """Reject a filename the manifest does not describe before it reaches the filesystem."""
        if not manifest.meta(name):
            raise ValueError(f"Unknown plugin: {name}")
        return manifest.meta(name)

    def _dirs(self):
        return paths.sls_plugins_dirs(self.ctx.home)

    def _disabled(self):
        return set(self.ctx.read_setting("disabled_plugins", []) or [])

    def _write_disabled(self, disabled):
        self.ctx.write_setting("disabled_plugins", sorted(disabled))

    def _require_enabled(self):
        """Install only where SLSsteam can load plugins; mirror Add's checks and fixes."""
        if self.guards is None:
            return
        gate = self.guards.check_sls_environment()
        if not gate.get("ok"):
            raise RuntimeError(gate.get("error") or "SLSsteam is not ready for plugins")

    # -- read ----------------------------------------------------------------
    def status(self, refresh=False):
        """Report plugin state. Never hits the network unless ``refresh`` is set."""
        manifest = self._manifest(refresh) if refresh else self._local_manifest()
        installed = {}
        for directory in self._dirs():
            if Path(directory).is_dir():
                for item in Path(directory).glob("*.lua"):
                    installed[item.name] = item
        disabled = self._disabled()
        rows = []
        for name in manifest.names:
            meta = manifest.meta(name)
            path = installed.get(name)
            off = name in disabled
            if off:
                state = "off"
            elif not path:
                state = "not_installed"
            elif plugin_install.sha256(path) != meta.get("sha256"):
                state = "update_available"
            else:
                state = "installed"
            rows.append({
                "filename": name,
                "name": meta.get("name", name),
                "version": str(meta.get("version", "")),
                "status": state,
                # A switched-off plugin is deliberately absent from disk; only a
                # plugin the user expects to be running counts as uninstalled.
                "installed": bool(path) or off,
                "enabled": not off,
                "required": manifest.policy(name) == "required",
                "deployable": manifest.is_deployable(name),
                "category": meta.get("category", ""),
                "disabled_reason": str(meta.get("disabled_reason") or ""),
            })
        return {"ok": True, "serial": manifest.serial, "source": manifest.source, "plugins": rows}

    # -- write ---------------------------------------------------------------
    def install(self, name):
        manifest = self._local_manifest()
        self._named(manifest, name)
        if not manifest.is_deployable(name):
            raise ValueError(f"{name} cannot be installed yet")
        self._require_enabled()
        result = plugin_install.deploy_plugin(
            name, self._dirs(), self.ctx.runtime_dir / "plugins" / "files", manifest
        )
        disabled = self._disabled()
        disabled.discard(name)
        self._write_disabled(disabled)
        return result

    def set_enabled(self, name, enabled):
        manifest = self._local_manifest()
        self._named(manifest, name)
        if enabled:
            disabled = self._disabled()
            if name in disabled:
                disabled.discard(name)
                self._write_disabled(disabled)
            if not any((Path(d) / name).is_file() for d in self._dirs()):
                return self.install(name)
            return {"ok": True, "filename": name, "enabled": True}
        if manifest.policy(name) == "required":
            raise ValueError("Required plugins cannot be disabled")
        disabled = self._disabled()
        disabled.add(name)
        self._write_disabled(disabled)
        plugin_install.undeploy_plugin(name, self._dirs())
        return {"ok": True, "filename": name, "enabled": False}

    def remove(self, name):
        manifest = self._local_manifest()
        self._named(manifest, name)
        if manifest.policy(name) == "required":
            raise ValueError("Required plugins cannot be removed")
        return plugin_install.undeploy_plugin(name, self._dirs())

    def install_essentials(self):
        manifest = self._local_manifest()
        self._require_enabled()
        retired = plugin_install.archive_retired(self._dirs(), manifest)
        results = [self.install(name) for name in manifest.required_plugins()]
        return {"ok": True, "retired": retired, "results": results}
