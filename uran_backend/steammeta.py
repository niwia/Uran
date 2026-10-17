"""Steam store + SteamCMD app metadata, search, and library introspection."""

import logging
import re
import time
from pathlib import Path

from .context import Context
from .http import requests

logger = logging.getLogger("Uran")

_STORE_CACHE_TTL = 300
_STEAMCMD_CACHE_TTL = 3600


class SteamMeta:
    """App details and search, with per-source caches."""

    def __init__(self, ctx: Context):
        self.ctx = ctx

    def _store_details(self, app_id: str) -> dict:
        cached = self.ctx.store_details_cache.get(app_id)
        if cached and time.time() - cached["fetchedAt"] < _STORE_CACHE_TTL:
            return cached["data"]
        try:
            url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=english&cc=US"
            resp = requests.get(url, timeout=10)
            if resp.ok:
                data = resp.json().get(app_id, {}).get("data", {})
                self.ctx.store_details_cache[app_id] = {"data": data, "fetchedAt": time.time()}
                return data
        except Exception as exc:  # noqa: BLE001
            logger.debug("Store details failed for %s: %s", app_id, exc)
        return {}

    def _steamcmd_details(self, app_id: str) -> dict:
        cached = self.ctx.steamcmd_details_cache.get(app_id)
        if cached and time.time() - cached["fetchedAt"] < _STEAMCMD_CACHE_TTL:
            return cached["data"]
        try:
            resp = requests.get(f"https://api.steamcmd.net/v1/info/{app_id}", timeout=10)
            if resp.ok:
                data = resp.json().get("data", {}).get(app_id, {})
                self.ctx.steamcmd_details_cache[app_id] = {"data": data, "fetchedAt": time.time()}
                return data
        except Exception as exc:  # noqa: BLE001
            logger.debug("SteamCMD details failed for %s: %s", app_id, exc)
        return {}

    def app_details(self, app_id: str) -> dict:
        store = self._store_details(app_id)
        cmd = self._steamcmd_details(app_id)

        packages = [str(pkg) for pkg in store.get("packages", [])]
        depots = []
        depot_dlc: dict[str, str] = {}
        depot_names: dict[str, str] = {}
        depot_dict = cmd.get("depots", {})
        if isinstance(depot_dict, dict):
            for raw_id, raw_info in depot_dict.items():
                if not raw_id.isdigit():
                    continue
                depots.append(raw_id)
                if not isinstance(raw_info, dict):
                    continue
                # SteamCMD marks a DLC-owned depot with `dlcappid`. This is the
                # authoritative depot -> owning-AppID attribution, and it is
                # the same field ASSella caches in apps.depots_json.
                dlc_id = raw_info.get("dlcappid")
                if dlc_id is not None and str(dlc_id).isdigit():
                    depot_dlc[raw_id] = str(dlc_id)
                dname = raw_info.get("name")
                if dname:
                    depot_names[raw_id] = str(dname)

        return {
            "app_id": app_id,
            "name": store.get("name") or cmd.get("common", {}).get("name") or f"App {app_id}",
            "packages": list(set(packages)),
            "depots": list(set(depots)),
            "depot_dlc": depot_dlc,
            "depot_names": depot_names,
            "dlc": [str(d) for d in store.get("dlc", [])],
        }

    def search(self, query: str, limit: int = 20, appid: bool = False) -> dict:
        """Search by name, or resolve an exact AppID to its title."""
        q = query.strip()
        if not q:
            return {"results": []}

        results = []
        if appid or q.isdigit():
            details = self._store_details(q)
            name = details.get("name")
            if not name:
                name = self._steamcmd_details(q).get("common", {}).get("name")
            if name:
                results.append({"app_id": q, "title": name})

        try:
            resp = requests.get(
                "https://store.steampowered.com/api/storesearch/",
                params={"term": q, "l": "english", "cc": "US"},
                timeout=10,
            )
            if resp.ok:
                seen = {r["app_id"] for r in results}
                for item in resp.json().get("items", []):
                    aid = str(item.get("id"))
                    if aid and aid not in seen:
                        seen.add(aid)
                        results.append({
                            "app_id": aid,
                            "title": item.get("name") or f"App {aid}",
                        })
        except Exception as exc:  # noqa: BLE001
            logger.error("Search API error: %s", exc)

        return {"results": results[:limit]}

    # -- library introspection ------------------------------------------------
    def libraries(self) -> list[Path]:
        """Steam library folders from libraryfolders.vdf, plus native fallbacks."""
        libs: list[Path] = []
        root = self.ctx.steam_root()
        if root:
            vdf = root / "steamapps" / "libraryfolders.vdf"
            try:
                if vdf.is_file():
                    content = vdf.read_text(encoding="utf-8", errors="replace")
                    for match in re.finditer(r'"path"\s+"([^"]+)"', content):
                        path = Path(match.group(1).replace("\\\\", "\\"))
                        if path.is_dir() and path not in libs:
                            libs.append(path)
            except Exception as exc:  # noqa: BLE001
                logger.debug("libraryfolders.vdf parse failed: %s", exc)

        for fallback in (
            self.ctx.home / ".local/share/Steam",
            self.ctx.home / ".steam/steam",
            self.ctx.home / ".var/app/com.valvesoftware.Steam/data/Steam",
        ):
            if fallback.is_dir() and fallback not in libs:
                libs.append(fallback)
        return libs

    def _parse_acf(self, path: Path) -> dict:
        """Pull the useful fields out of a Steam appmanifest_<appid>.acf file."""
        out: dict = {}
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return out
        for field, key in (
            (r'"installdir"\s+"([^"]*)"', "installdir"),
            (r'"name"\s+"([^"]*)"', "name"),
            (r'"StateFlags"\s+"(\d+)"', "StateFlags"),
            (r'"buildid"\s+"(\d+)"', "buildid"),
            (r'"LastUpdated"\s+"(\d+)"', "LastUpdated"),
            (r'"SizeOnDisk"\s+"(\d+)"', "SizeOnDisk"),
            (r'"LastOwner"\s+"(\d+)"', "LastOwner"),
        ):
            match = re.search(field, content)
            if match:
                out[key] = match.group(1)
        for numeric in ("SizeOnDisk", "StateFlags"):
            try:
                out[numeric] = int(out.get(numeric) or 0)
            except ValueError:
                out[numeric] = 0
        return out

    def install_info(self, app_id: str) -> dict:
        """Locate a game's install dir across every Steam library.

        Mirrors ASSella's get_atom_game_install_info: appmanifest_<appid>.acf's
        "installdir" under steamapps/common, plus staged download folders.
        """
        info = {
            "installed": False, "install_path": "", "library_path": "",
            "install_dir": "", "game_name": "", "buildid": "",
            "size_on_disk": 0, "downloading": False, "state_flags": 0,
        }
        libs = self.libraries()
        for lib in libs:
            steamapps = lib / "steamapps"
            if not steamapps.is_dir():
                continue
            acf = steamapps / f"appmanifest_{app_id}.acf"
            if not acf.is_file():
                continue
            data = self._parse_acf(acf)
            installdir = data.get("installdir") or ""
            info.update({
                "installed": True,
                "library_path": str(lib),
                "install_dir": installdir,
                "install_path": str(steamapps / "common" / installdir) if installdir else "",
                "game_name": data.get("name") or "",
                "buildid": data.get("buildid") or "",
                "size_on_disk": data.get("SizeOnDisk", 0),
                "state_flags": data.get("StateFlags", 0),
                "acf_path": str(acf),
            })
            break

        if not info["installed"]:
            # Might still be mid-download (no appmanifest written yet).
            for lib in libs:
                downloading = lib / "steamapps" / "downloading" / app_id
                if downloading.is_dir():
                    info.update({
                        "downloading": True,
                        "install_path": str(downloading),
                        "library_path": str(lib),
                    })
                    break
        return info


def sls_config_dir(ctx: Context) -> Path:
    cfg = ctx.sls_config()
    return cfg.parent if cfg is not None else ctx.home / ".config" / "SLSsteam"