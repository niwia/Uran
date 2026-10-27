"""Hubcap manifest bundle handling: download, parse, depotcache seeding, pins."""

import io
import logging
import zipfile
from pathlib import Path

from . import manifest_lua
from .context import Context
from .hubcap import HUBCAP_BASE_URL, auth_headers, request as hubcap_request
from .library import PluginLibrary
from .sls_config import (
    SlsConfig,
    ensure_plugins_enabled,
    sanitize_comment,
    sanitize_key,
    sort_ids,
)
from .steammeta import SteamMeta

logger = logging.getLogger("Uran")


class Manifests:
    """Fetches and applies Hubcap manifest bundles."""

    def __init__(self, ctx: Context, sls: SlsConfig, steam: SteamMeta, library: PluginLibrary):
        self.ctx = ctx
        self.sls = sls
        self.steam = steam
        self.library = library

    def contents(self, app_id: str) -> dict:
        """Zero-quota bundle preflight so a missing bundle is distinguishable."""
        from . import hubcap

        api_key = self.ctx.hubcap_key.current()
        if not api_key:
            return {"error": "Hubcap API key is not set in ACCELA settings"}
        return hubcap.manifest_contents(app_id, api_key, self.gateway_mode())

    def gateway_mode(self) -> str:
        """The configured route preference: auto | direct | proxy."""
        from . import hubcap

        value = self.ctx.read_setting("hubcap_gateway", hubcap.GATEWAY_DEFAULT)
        return value if value in hubcap.GATEWAY_MODES else hubcap.GATEWAY_DEFAULT

    def route_status(self) -> dict:
        """Route health plus the current preference, for the Settings panel."""
        from . import hubcap

        status = hubcap.route_health()
        status["mode"] = self.gateway_mode()
        return status

    def probe_routes(self) -> dict:
        """Actively test both routes and report what actually happened."""
        from . import hubcap

        result = hubcap.probe_routes(self.ctx.hubcap_key.current())
        result["mode"] = self.gateway_mode()
        return result

    def _download(self, app_id: str, api_key: str) -> tuple[bytes | None, str | None]:
        """Download the bundle, trying force_update then the plain endpoint.

        Mirrors ASSella: a server-side refresh error must not be fatal when the
        cached bundle is still usable.
        """
        last_error = None
        for force in (True, False):
            url = f"{HUBCAP_BASE_URL}/manifest/{app_id}"
            if force:
                url += "?force_update=true"
            logger.info("Hubcap: fetching bundle for AppID %s from %s", app_id, url)
            try:
                resp = hubcap_request(
                    url,
                    headers=auth_headers(api_key),
                    timeout=60,
                    mode=self.gateway_mode(),
                )
            except Exception as exc:  # noqa: BLE001
                last_error = f"Hubcap download failed: {exc}"
                continue

            if resp.status_code == 401:
                return None, "Invalid Hubcap API key (HTTP 401)"
            if resp.status_code == 404:
                return None, f"No Hubcap bundle available for {app_id}"
            if resp.status_code == 429:
                return None, "Hubcap API daily rate limit exceeded (HTTP 429)"
            if not resp.ok:
                last_error = f"Hubcap API HTTP {resp.status_code}"
                continue
            return resp.content, None
        return None, last_error or "Hubcap download failed"

    def fetch(self, app_id: str, persist_config: bool = True) -> dict:
        """Download the bundle, harvest depot keys and seed depotcache.

        By default the harvested keys/pins are persisted in one batched pass.
        Pass ``persist_config=False`` when the caller folds them into a larger
        atomic write (e.g. game injection).
        """
        app_id = str(app_id).strip()
        api_key = self.ctx.hubcap_key.current()
        if not api_key:
            return {"ok": False, "app_id": app_id, "error": "Hubcap API key is not configured"}

        data, error = self._download(app_id, api_key)
        if data is None:
            return {"ok": False, "app_id": app_id, "error": error}

        depotcache = self.ctx.depotcache()
        if depotcache is not None:
            try:
                depotcache.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                logger.warning("Could not create depotcache %s: %s", depotcache, exc)
                depotcache = None

        zip_path = self.ctx.manifest_zip_path(app_id)
        try:
            zip_path.parent.mkdir(parents=True, exist_ok=True)
            zip_path.write_bytes(data)
        except OSError as exc:
            logger.warning("Could not cache Hubcap bundle to %s: %s", zip_path, exc)

        extracted_manifests: list[str] = []
        written_count = 0
        depot_keys: dict[str, str] = {}
        manifest_ids: dict[str, str] = {}
        app_tokens: dict[str, str] = {}
        dlc_appids: list[str] = []
        game_name = ""

        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for name in archive.namelist():
                    base = Path(name).name
                    if base.endswith(".manifest"):
                        # Sanitize before this name becomes a depotcache path.
                        stem = base[: -len(".manifest")]
                        parts = stem.split("_", 1)
                        did = manifest_lua.coerce_depot_id(parts[0]) if len(parts) == 2 else None
                        mid = manifest_lua.coerce_manifest_gid(parts[1]) if len(parts) == 2 else None
                        if not (did and mid):
                            logger.warning("Skipping malformed manifest name: %s", base)
                            continue
                        extracted_manifests.append(base)
                        if depotcache:
                            try:
                                (depotcache / base).write_bytes(archive.read(name))
                                written_count += 1
                            except OSError as exc:
                                logger.warning("Failed writing manifest %s: %s", base, exc)
                        manifest_ids[did] = mid
                    elif base.endswith(".lua"):
                        try:
                            lua_content = archive.read(name).decode("utf-8", errors="replace")
                            manifest_lua.harvest_depot_names(
                                lua_content, self.ctx.depot_names, sanitize_comment
                            )
                            parsed = manifest_lua.parse(lua_content, sanitize_key)
                            depot_keys.update(parsed["keys"])
                            manifest_ids.update(parsed["manifests"])
                            app_tokens.update(parsed.get("tokens") or {})
                            for did in parsed["dlcs"]:
                                if did not in dlc_appids:
                                    dlc_appids.append(did)
                            if parsed.get("name"):
                                game_name = parsed["name"]
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("Error parsing .lua in bundle: %s", exc)
        except zipfile.BadZipFile:
            return {"ok": False, "app_id": app_id, "error": "Invalid zip file returned by Hubcap"}

        # Guard: a bundle with no usable keys cannot drive an injection. Writing
        # keyless depots makes Steam fail with DepotWithoutKey, so refuse.
        if not depot_keys:
            return {
                "ok": False,
                "app_id": app_id,
                "error": "Hubcap bundle contains no depot decryption keys",
            }

        # Keys are written by the caller in a single batched pass,
        # so one inject never rewrites the config once per depot.
        if persist_config:
            self._persist_keys(app_id, depot_keys)

        logger.info(
            "Hubcap: AppID %s processed. Manifests: %s, Keys harvested: %s",
            app_id, written_count, len(depot_keys),
        )
        return {
            "ok": True,
            "app_id": app_id,
            "manifests": extracted_manifests,
            "written": written_count,
            "depot_keys": depot_keys,
            "manifest_ids": manifest_ids,
            "app_tokens": app_tokens,
            "dlc_appids": dlc_appids,
            "game_name": game_name,
            # Back-compat: callers still read `keys_added` as a list of depot ids.
            "keys_added": sort_ids(depot_keys.keys()),
        }

    def _persist_keys(self, app_id: str, depot_keys: dict, manifest_ids: dict | None = None) -> dict:
        """Write harvested depot keys in one batched pass."""
        app_id = str(app_id).strip()
        try:
            name = sanitize_comment(self.steam.app_details(app_id).get("name") or f"App {app_id}")
        except Exception:  # noqa: BLE001
            name = f"App {app_id}"

        written: dict[str, str] = {}
        with self.sls.edit() as editor:
            editor.content = ensure_plugins_enabled(editor.content)
            editor.has_changes = True
            for did, key in (depot_keys or {}).items():
                # Sanitize at the write boundary: parsing keeps the root AppKey
                # verbatim for ASSella parity, so a malformed key must be caught
                # here before it can reach DecryptionKeys.
                clean = sanitize_key(key)
                if clean:
                    editor.add_key(did, clean, comment=self.ctx.depot_names.get(did, ""))
                    written[did] = clean
        return {"ok": editor.committed_successfully, "keys": list(written.keys())}

    def refetch(self, app_id: str) -> dict:
        self.remove_pins(app_id)
        return self.fetch(app_id)

    # -- pins -----------------------------------------------------------------
    def _pin_depots(self, app_id: str) -> list[str]:
        """Depot IDs for which this app's cached bundle carries manifest files."""
        zip_path = self.ctx.manifest_zip_path(app_id)
        depots: list[str] = []
        if not zip_path.exists():
            return depots
        try:
            with zipfile.ZipFile(zip_path) as archive:
                for name in archive.namelist():
                    base = Path(name).name
                    if base.endswith(".manifest") and "_" in base:
                        did = base.split("_")[0]
                        if did.isdigit():
                            depots.append(did)
        except Exception:  # noqa: BLE001
            pass
        return depots

    def _drop_pins(self, depots: list[str]) -> list[str]:
        """Remove ManifestIds entries in one batched write."""
        if not depots:
            return []
        from .sls_config import remove_in_memory

        removed = []
        with self.sls.edit() as editor:
            for did in depots:
                if editor.apply(*remove_in_memory(editor.content, "ManifestIds", did, is_list=False)):
                    removed.append(did)
        return removed if editor.committed_successfully else []

    def remove_pins(self, app_id: str) -> dict:
        app_id = str(app_id)
        return {
            "ok": True,
            "app_id": app_id,
            "removed_pins": self._drop_pins(self._pin_depots(app_id)),
        }

    def remove(self, app_id: str) -> dict:
        app_id = str(app_id)
        zip_path = self.ctx.manifest_zip_path(app_id)
        removed_files: list[str] = []
        depotcache = self.ctx.depotcache()

        # Collect the pin list BEFORE deleting the bundle, otherwise there is
        # nothing left to read and the pins would silently be orphaned.
        pinned_depots = self._pin_depots(app_id)

        if zip_path.exists():
            try:
                with zipfile.ZipFile(zip_path) as archive:
                    for name in archive.namelist():
                        base = Path(name).name
                        if base.endswith(".manifest") and depotcache:
                            target = depotcache / base
                            if target.exists():
                                target.unlink(missing_ok=True)
                                removed_files.append(base)
                zip_path.unlink(missing_ok=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error removing manifest for %s: %s", app_id, exc)

        return {
            "ok": True,
            "app_id": app_id,
            "removed_files": removed_files,
            "removed_pins": self._drop_pins(pinned_depots),
        }


def configured_manifest_ids(ctx: Context) -> dict:
    cfg = ctx.sls_config()
    if not cfg or not cfg.exists():
        return {"ok": True, "manifest_ids": {}}
    mids: dict[str, str] = {}
    in_section = False
    for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped == "ManifestIds:":
            in_section = True
            continue
        if not in_section:
            continue
        if not line.startswith((" ", "\t")):
            break
        if ":" in stripped and not stripped.startswith("#") and not stripped.startswith("-"):
            did, _, value = stripped.partition(":")
            if did.strip().isdigit():
                mids[did.strip()] = value.split("#")[0].strip()
    return {"ok": True, "manifest_ids": mids}


def configured_depot_keys(ctx: Context) -> dict:
    cfg = ctx.sls_config()
    if not cfg or not cfg.exists():
        return {"ok": True, "keys": {}}
    keys: dict[str, str] = {}
    in_section = False
    for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped == "DecryptionKeys:":
            in_section = True
            continue
        if not in_section:
            continue
        if not line.startswith((" ", "\t")):
            break
        if ":" in stripped and not stripped.startswith(("#", "-")):
            did, _, value = stripped.partition(":")
            if did.strip().isdigit():
                keys[did.strip()] = value.split("#")[0].strip()
    return {"ok": True, "keys": keys}


__all__ = ["Manifests", "configured_depot_keys", "configured_manifest_ids"]