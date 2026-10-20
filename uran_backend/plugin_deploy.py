"""On-demand distribution and activation of ASSella's SLSsteam plugins."""

import hashlib
import json
import logging
import os
import re
import shutil
import threading
import urllib.request
from pathlib import Path

from . import paths
from .context import Context
from .sls_config import ensure_plugins_enabled, ensure_smart_tickets

logger = logging.getLogger("Uran")

R2_BASE_URL = "https://pub-19657b4f385d424b91a909253efdb29c.r2.dev"
MANIFEST_URL = f"{R2_BASE_URL}/plugins_manifest.json"
PLUGIN_INFO = {
    "download.lua": {"label": "Standard", "kind": "interceptor"},
    "spacebunny1.5.lua": {"label": "SpaceBunny 1.5", "kind": "interceptor"},
    "spliced-tickets.lua": {"label": "Spliced Tickets", "kind": "companion"},
}
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_PLUGIN_BYTES = 16 * 1024 * 1024


class PluginDeployer:
    """Fetch, verify, and deploy the allowlisted SLSsteam plugin set."""

    def __init__(self, ctx: Context, sls):
        self.ctx = ctx
        self.sls = sls
        self._lock = threading.Lock()

    @property
    def cache_dir(self) -> Path:
        path = self.ctx.runtime_dir / "plugins"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _fetch(self, url: str, limit: int) -> bytes:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Uran-PluginManager/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status} fetching plugin data")
            data = response.read(limit + 1)
        if len(data) > limit:
            raise RuntimeError("Plugin response exceeds the allowed size")
        return data

    def _manifest(self) -> dict:
        cache_path = self.cache_dir / "plugins_manifest.json"
        try:
            raw = self._fetch(MANIFEST_URL, _MAX_MANIFEST_BYTES)
            parsed = json.loads(raw.decode("utf-8"))
            if not isinstance(parsed, dict) or not isinstance(parsed.get("plugins"), dict):
                raise RuntimeError("Invalid plugins manifest format")
            temp = cache_path.with_suffix(".tmp")
            temp.write_bytes(raw)
            os.replace(temp, cache_path)
            return parsed
        except Exception as exc:
            logger.info("Could not refresh plugin manifest; trying cache: %s", exc)
        try:
            parsed = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict) and isinstance(parsed.get("plugins"), dict):
                return parsed
        except (OSError, ValueError):
            pass
        return {"plugins": {}}

    def _expected_hash(self, filename: str, manifest: dict) -> str | None:
        info = manifest["plugins"].get(filename)
        digest = info.get("sha256") if isinstance(info, dict) else None
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest.lower()):
            return None
        return digest.lower()

    @staticmethod
    def _hash(path: Path) -> str | None:
        try:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(65536), b""):
                    digest.update(block)
            return digest.hexdigest()
        except OSError:
            return None

    def _targets(self) -> list[Path]:
        config = self.ctx.sls_config()
        if config is None:
            return []
        directories = paths.sls_plugins_dirs(self.ctx.home)
        return directories or [config.parent / "plugins"]

    def _active_interceptor(self, directories: list[Path]) -> str | None:
        # Match ASSella: the active interceptor is any non-hidden Lua plugin
        # except the independent Spliced Tickets companion.
        for directory in directories:
            try:
                for candidate in sorted(directory.glob("*.lua")):
                    if (
                        candidate.is_file()
                        and not candidate.name.startswith(".")
                        and candidate.name != "spliced-tickets.lua"
                    ):
                        return candidate.name
            except OSError:
                continue
        return None

    def status(self) -> dict:
        config = self.ctx.sls_config()
        if config is None or not config.is_file():
            return {"ok": False, "error": "SLSsteam config.yaml not found."}
        manifest = self._manifest()
        directories = self._targets()
        active = self._active_interceptor(directories)
        plugins = {}
        for filename, definition in PLUGIN_INFO.items():
            installed = next(
                (directory / filename for directory in directories if (directory / filename).is_file()),
                None,
            )
            expected = self._expected_hash(filename, manifest)
            local_hash = self._hash(installed) if installed else None
            if installed is None:
                state = "missing"
            elif expected is None:
                state = "unknown"
            elif local_hash != expected:
                state = "outdated"
            else:
                state = "up_to_date"
            manifest_info = manifest["plugins"].get(filename)
            plugins[filename] = {
                "label": definition["label"],
                "state": state,
                "active": definition["kind"] == "companion"
                and installed is not None
                or definition["kind"] == "interceptor" and active == filename,
                "version": manifest_info.get("version") if isinstance(manifest_info, dict) else None,
            }
        return {
            "ok": True,
            "directory": str(directories[0]) if directories else "",
            "active_interceptor": active,
            "plugins": plugins,
        }

    def deploy(self, filename: str) -> dict:
        if filename not in PLUGIN_INFO:
            return {"ok": False, "error": "Unknown SLSsteam plugin."}
        config = self.ctx.sls_config()
        if config is None or not config.is_file():
            return {"ok": False, "error": "SLSsteam config.yaml not found."}

        with self._lock:
            manifest = self._manifest()
            expected = self._expected_hash(filename, manifest)
            if expected is None:
                return {"ok": False, "error": f"No valid SHA-256 for {filename} in the plugin manifest."}

            cache_path = self.cache_dir / filename
            if self._hash(cache_path) != expected:
                try:
                    content = self._fetch(f"{R2_BASE_URL}/{filename}", _MAX_PLUGIN_BYTES)
                except Exception as exc:
                    return {"ok": False, "error": f"Could not download {filename}: {exc}"}
                if hashlib.sha256(content).hexdigest() != expected:
                    return {"ok": False, "error": f"SHA-256 verification failed for {filename}."}
                temporary = cache_path.with_suffix(".tmp")
                temporary.write_bytes(content)
                os.replace(temporary, cache_path)

            directories = self._targets()
            if not directories:
                return {"ok": False, "error": "No SLSsteam plugin directory is available."}

            try:
                for directory in directories:
                    directory.mkdir(parents=True, exist_ok=True)
                    if PLUGIN_INFO[filename]["kind"] == "interceptor":
                        incoming_backup = directory / f"{filename}.bak"
                        if incoming_backup.is_file():
                            incoming_backup.unlink()
                        for existing in directory.glob("*.lua"):
                            if (
                                existing.is_file()
                                and not existing.name.startswith(".")
                                and existing.name not in (filename, "spliced-tickets.lua")
                            ):
                                backup = directory / f"{existing.name}.bak"
                                if backup.is_file():
                                    backup.unlink()
                                existing.replace(backup)

                    destination = directory / filename
                    if destination.is_file() and self._hash(destination) == expected:
                        continue
                    if destination.is_file():
                        backup = directory / f"{filename}.bak"
                        if backup.is_file():
                            backup.unlink()
                        shutil.copy2(destination, backup)
                    temporary = directory / f".{filename}.tmp"
                    shutil.copyfile(cache_path, temporary)
                    os.replace(temporary, destination)

                current = self.sls.read()
                updated = ensure_plugins_enabled(current)
                if filename == "spliced-tickets.lua":
                    updated = ensure_smart_tickets(updated)
                if updated != current and not self.sls.write(updated):
                    return {"ok": False, "error": "Plugin deployed, but SLSsteam config could not be updated."}
            except Exception as exc:  # noqa: BLE001
                logger.exception("Plugin deployment failed for %s", filename)
                return {"ok": False, "error": f"Could not deploy {filename}: {exc}"}

        return {"ok": True, "message": f"{PLUGIN_INFO[filename]['label']} deployed successfully."}
