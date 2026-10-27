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
    "spacebunny.lua": {"label": "SpaceBunny", "kind": "interceptor"},
    "spacebunny1.5.lua": {"label": "SpaceBunny 1.5", "kind": "interceptor"},
    "spliced-tickets.lua": {"label": "Spliced Tickets", "kind": "companion"},
    "hubcap.lua": {"label": "Hubcap Auto-Fetch", "kind": "companion"},
    "lobster.lua": {"label": "Lobster Config Recovery", "kind": "companion"},
}
COMPANION_PLUGINS = {
    "spliced-tickets.lua",
    "hubcap.lua",
    "lobster.lua",
    *(name for name, info in PLUGIN_INFO.items() if info.get("kind") == "companion"),
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

    @staticmethod
    def extract_plugin_version(content_or_path) -> str | None:
        """Extract semantic version from Lua file content or path.

        Matches multiple formats:
          - VERSION = "1.8.2" (code constant)
          - -- spacebunny.lua (1.8.2) (header comment with filename)
          - -- Version: 1.8.2 (alternate header)
          - -- spacebunny.lua v1.8.2 (version in comment)
        """
        try:
            if isinstance(content_or_path, Path):
                if not content_or_path.is_file():
                    return None
                content = content_or_path.read_text(encoding="utf-8", errors="ignore")
            elif isinstance(content_or_path, bytes):
                content = content_or_path.decode("utf-8", errors="ignore")
            else:
                content = str(content_or_path)

            # 1. VERSION = "1.8.2" or table.VERSION = "1.8.2"
            m = re.search(r'\bVERSION\s*=\s*["\']([^"\']+)["\']', content, re.IGNORECASE)
            if m:
                sem = re.search(r'(\d+\.\d+(?:\.\d+)?(?:[a-zA-Z0-9_.\-]+)?)', m.group(1))
                if sem:
                    return sem.group(1)

            # 2. Header comment: -- spacebunny.lua (1.8.2)
            m2 = re.search(r'^--\s*[\w.\-]+\.lua\s*\((v?\d+(?:\.\d+)*(?:[a-zA-Z0-9_.\-]+)?)\)', content, re.MULTILINE | re.IGNORECASE)
            if m2:
                return m2.group(1).lstrip("v")

            # 3. Header comment: -- Version: 1.8.2
            m3 = re.search(r'^--\s*(?:version|ver|v)\s*[:=]?\s*v?(\d+\.\d+(?:\.\d+)*(?:[a-zA-Z0-9_.\-]+)?)', content, re.MULTILINE | re.IGNORECASE)
            if m3:
                return m3.group(1)

            # 4. Header comment: -- spacebunny.lua v1.8.2
            m4 = re.search(r'^--\s*[\w.\-]+\.lua\s+v?(\d+\.\d+(?:\.\d+)*(?:[a-zA-Z0-9_.\-]+)?)', content, re.MULTILINE | re.IGNORECASE)
            if m4:
                return m4.group(1)
        except Exception as exc:
            logger.debug("Error extracting plugin version: %s", exc)
        return None

    def _fetch(self, url: str, limit: int) -> bytes:
        import ssl
        import subprocess

        # 1. Standard urllib
        try:
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
        except Exception as e1:
            logger.debug("Standard urllib fetch failed for %s: %s", url, e1)

        # 2. Unverified SSL (bypasses hostname mismatch / captive portal)
        if url.startswith("https"):
            try:
                unverified_ctx = ssl._create_unverified_context()
                request = urllib.request.Request(url, headers={"User-Agent": "Uran-PluginManager/1.0"})
                with urllib.request.urlopen(request, context=unverified_ctx, timeout=10) as response:
                    logger.info("Fetched %s via unverified SSL fallback", url)
                    data = response.read(limit + 1)
                    if len(data) <= limit:
                        return data
            except Exception as e2:
                logger.debug("Unverified SSL fetch failed for %s: %s", url, e2)

        # 3. curl_cffi with Chrome 120 impersonation (if installed)
        try:
            from curl_cffi import requests as cffi_requests
            cffi_resp = cffi_requests.get(url, headers={"User-Agent": "Uran-PluginManager/1.0"}, impersonate="chrome120", timeout=10, verify=False)
            if cffi_resp.status_code == 200 and len(cffi_resp.content) <= limit:
                logger.info("Fetched %s via curl_cffi impersonation", url)
                return cffi_resp.content
        except Exception as e3:
            logger.debug("curl_cffi fetch failed for %s: %s", url, e3)

        # 4. System curl subprocess. -f makes HTTP 4xx/5xx fail instead of
        # accidentally treating an error page as a valid manifest/plugin.
        try:
            cmd = [
                "curl", "-fsS", "-k", "--max-time", "10",
                "--max-filesize", str(limit),
                "-A", "Uran-PluginManager/1.0", url,
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=12)
            if res.returncode == 0 and res.stdout and len(res.stdout) <= limit:
                logger.info("Fetched %s via system curl fallback", url)
                return res.stdout
        except Exception as e4:
            logger.debug("System curl fetch failed for %s: %s", url, e4)

        raise RuntimeError(f"All network fetch attempts failed for {url}")

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
        # except independent companion plugins (Spliced Tickets, Hubcap, Lobster).
        for directory in directories:
            try:
                for candidate in sorted(directory.glob("*.lua")):
                    if (
                        candidate.is_file()
                        and not candidate.name.startswith(".")
                        and candidate.name not in COMPANION_PLUGINS
                        and PLUGIN_INFO.get(candidate.name, {}).get("kind") != "companion"
                    ):
                        return candidate.name
            except OSError:
                continue
        return None

    def _is_plugin_disabled(self, filename: str) -> bool:
        """Check if user has disabled this plugin."""
        disabled = self.ctx.read_setting("disabled_plugins", [])
        if not isinstance(disabled, list):
            return False
        return filename in disabled

    def _get_file_version(self, filename: str) -> str | None:
        """Extract version from deployed plugin file."""
        directories = self._targets()
        for directory in directories:
            plugin_path = directory / filename
            if plugin_path.is_file():
                version = self.extract_plugin_version(plugin_path)
                if version:
                    return version
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
            # Prefer file-extracted version over manifest version
            file_version = self._get_file_version(filename)
            manifest_version = manifest_info.get("version") if isinstance(manifest_info, dict) else None
            version = file_version or manifest_version
            plugins[filename] = {
                "label": definition["label"],
                "kind": definition["kind"],
                "state": state,
                "active": definition["kind"] == "companion"
                and installed is not None
                or definition["kind"] == "interceptor" and active == filename,
                "version": version,
                "available_remote": expected is not None,
                "user_disabled": self._is_plugin_disabled(filename),
            }
        return {
            "ok": True,
            "directory": str(directories[0]) if directories else "",
            "active_interceptor": active,
            "plugins": plugins,
        }

    def enable_plugin(self, filename: str) -> dict:
        """Enable a previously disabled plugin."""
        if filename not in PLUGIN_INFO:
            return {"ok": False, "error": "Unknown SLSsteam plugin."}
        disabled = self.ctx.read_setting("disabled_plugins", [])
        if not isinstance(disabled, list):
            disabled = []
        if filename in disabled:
            disabled = [p for p in disabled if p != filename]
            self.ctx.write_setting("disabled_plugins", disabled)
            logger.info("Enabled plugin: %s", filename)
            return {"ok": True}
        return {"ok": True}  # Already enabled

    def disable_plugin(self, filename: str) -> dict:
        """Disable a plugin so it won't be auto-deployed."""
        if filename not in PLUGIN_INFO:
            return {"ok": False, "error": "Unknown SLSsteam plugin."}
        disabled = self.ctx.read_setting("disabled_plugins", [])
        if not isinstance(disabled, list):
            disabled = []
        if filename not in disabled:
            disabled.append(filename)
            self.ctx.write_setting("disabled_plugins", disabled)
            logger.info("Disabled plugin: %s", filename)
            return {"ok": True}
        return {"ok": True}  # Already disabled

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
                                and existing.name != filename
                                and existing.name not in COMPANION_PLUGINS
                                and PLUGIN_INFO.get(existing.name, {}).get("kind") != "companion"
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

                # Mark as enabled when deployed
                self.enable_plugin(filename)

                if "spacebunny" in filename.lower() or filename == "hubcap.lua":
                    self.sync_spacebunny_conf()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Plugin deployment failed for %s", filename)
                return {"ok": False, "error": f"Could not deploy {filename}: {exc}"}

        return {"ok": True, "message": f"{PLUGIN_INFO[filename]['label']} deployed successfully."}

    def ensure_default_interceptor(self) -> dict:
        """If no interceptor plugin is deployed (ignoring companion plugins like spliced-tickets.lua, hubcap.lua, lobster.lua),
        auto-deploy SpaceBunny (spacebunny1.5.lua) from R2.
        If the user has any other interceptor lua, ignore.
        """
        config = self.ctx.sls_config()
        if config is None or not config.is_file():
            return {"ok": False, "skipped": True, "reason": "no_sls_config"}

        directories = self._targets()
        if not directories:
            return {"ok": False, "skipped": True, "reason": "no_plugins_dir"}

        active = self._active_interceptor(directories)
        if active is not None:
            if active == "spacebunny1.5.lua":
                disabled = self.ctx.read_setting("disabled_plugins", [])
                if not (isinstance(disabled, list) and "spacebunny.lua" in disabled):
                    logger.info("Auto-migrating legacy spacebunny1.5.lua to standardized spacebunny.lua...")
                    try:
                        res = self.deploy("spacebunny.lua")
                        if res.get("ok"):
                            return res
                        logger.warning("Auto-migration of spacebunny1.5.lua failed: %s; keeping legacy plugin active", res.get("error"))
                    except Exception as exc:
                        logger.warning("Auto-migration of spacebunny1.5.lua failed: %s", exc)
            # User already has an active interceptor (SpaceBunny, download.lua, or custom)
            has_hubcap = any((directory / "hubcap.lua").is_file() for directory in directories)
            if "spacebunny" in active.lower() or has_hubcap:
                self.sync_spacebunny_conf()
            return {"ok": True, "deployed": False, "active": active}

        # Check if default interceptor is disabled by user
        disabled = self.ctx.read_setting("disabled_plugins", [])
        if isinstance(disabled, list) and ("spacebunny.lua" in disabled or "spacebunny1.5.lua" in disabled):
            logger.info("SpaceBunny is disabled by user, skipping auto-deploy")
            return {"ok": True, "deployed": False, "reason": "user_disabled"}

        logger.info("No interceptor Lua plugin detected. Auto-deploying SpaceBunny from R2...")
        try:
            manifest = self._manifest()
            manifest_plugins = manifest.get("plugins", {}) if manifest else {}
            target_sb = "spacebunny.lua" if ("spacebunny.lua" in manifest_plugins or not manifest_plugins) else "spacebunny1.5.lua"
            return self.deploy(target_sb)
        except Exception as exc:
            logger.warning("Could not auto-deploy SpaceBunny: %s", exc)
            return {"ok": False, "error": str(exc)}

    def sync_spacebunny_conf(self) -> bool:
        """One-way sync: copy Hubcap API key to spacebunny.conf.lua if key exists.

        Preserves existing config structure. Only updates the api_key and timestamp fields.
        """
        from . import sls_lua_config

        config = self.ctx.sls_config()
        if config is None or not config.is_file():
            return False

        directories = self._targets()
        active = self._active_interceptor(directories)
        has_hubcap = any((directory / "hubcap.lua").is_file() for directory in directories)
        if not (has_hubcap or (active and "spacebunny" in active.lower())):
            return False

        key_resolver = getattr(self.ctx, "hubcap_key", None)
        api_key = key_resolver.current() if key_resolver else ""
        conf_path = config.parent / "spacebunny.conf.lua"

        if not api_key:
            # If no key, remove the conf file to avoid stale data
            if conf_path.exists():
                try:
                    conf_path.unlink()
                except OSError:
                    pass
            return False

        ts = None
        if hasattr(self.ctx, "settings"):
            raw_ts = self.ctx.settings.get("manifest_api_key_timestamp", 0)
            if raw_ts:
                try:
                    ts = int(raw_ts)
                except (ValueError, TypeError):
                    ts = None

        ok = sls_lua_config.sync_spacebunny_key(conf_path, api_key, timestamp=ts)
        if ok:
            logger.info("Synced Hubcap API key to spacebunny.conf.lua")
        return ok
