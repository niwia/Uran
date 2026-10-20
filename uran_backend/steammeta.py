"""Steam store + SteamCMD app metadata, search, and library introspection."""

import json
import logging
import os
import re
import threading
import time
from pathlib import Path

from .context import Context
from .http import requests

logger = logging.getLogger("Uran")

# How long a cached Steam response stays trustworthy. Steam metadata barely
# changes, so the window is generous: within it the game page renders straight
# from disk, and past it the page serves the stale copy and refreshes behind
# the scenes. Refreshes also happen on every toggle/refresh action.
_META_TTL = 6 * 3600
_META_CACHE_VERSION = 1
_SOURCES = ("store", "steamcmd")


class SteamMeta:
    """App details and search, with a persistent two-source disk cache.

    SteamCMD costs 1-4s per request and both endpoints change rarely, so each
    source is cached as JSON under the plugin runtime directory. An entry is
    *fresh* while younger than ``_META_TTL``, *stale* once older, and *missing*
    when we have never fetched it (or the cache was unreadable). The game page
    paints from disk instantly and only talks to the network when a source is
    not fresh, so it can name what it is waiting for.
    """

    def __init__(self, ctx: Context, library=None):
        self.ctx = ctx
        # Optional ASSella library: when present, its cached depot map seeds
        # this cache so a game page can open with no network call at all.
        self.library = library
        self._dir = ctx.runtime_dir / "meta"
        self._mem: dict[str, dict] = {}
        self._lock = threading.Lock()

    # -- persistent cache -----------------------------------------------------
    def _path(self, app_id: str) -> Path:
        return self._dir / f"{app_id}.json"

    def _read(self, app_id: str) -> dict:
        """Cached record for an app: ``{source: {"at": epoch, "data": {...}}}``."""
        with self._lock:
            if app_id in self._mem:
                return self._mem[app_id]
        record: dict = {}
        try:
            path = self._path(app_id)
            if path.is_file():
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and raw.get("version") == _META_CACHE_VERSION:
                    for source in _SOURCES:
                        entry = raw.get(source)
                        if isinstance(entry, dict) and isinstance(entry.get("data"), dict):
                            at = entry.get("at")
                            record[source] = {
                                "at": float(at) if isinstance(at, (int, float)) else 0.0,
                                "data": entry["data"],
                            }
        except (OSError, ValueError) as exc:
            logger.debug("Could not read metadata cache for %s: %s", app_id, exc)
        with self._lock:
            self._mem[app_id] = record
        return record

    def _write(self, app_id: str, record: dict) -> None:
        with self._lock:
            self._mem[app_id] = record
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            path = self._path(app_id)
            tmp = path.with_name(f"{path.name}.tmp")
            payload = {"version": _META_CACHE_VERSION}
            payload.update(record)
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, path)  # atomic: a reader never sees a half-written file
        except OSError as exc:
            logger.debug("Could not persist metadata cache for %s: %s", app_id, exc)

    @staticmethod
    def _age_state(entry: dict | None) -> str:
        """fresh | stale | missing, from an entry's age (presence, not content)."""
        if not entry:
            return "missing"
        return "fresh" if time.time() - entry.get("at", 0) < _META_TTL else "stale"

    def _state(self, record: dict, source: str) -> str:
        return self._age_state(record.get(source))

    def meta_state(self, app_id: str) -> dict:
        """Freshness of each source, so the page can say what it is fetching."""
        record = self._read(app_id)
        state = {source: self._state(record, source) for source in _SOURCES}
        state["needs_fetch"] = any(value != "fresh" for value in state.values())
        return state

    def _cached(self, app_id: str, source: str) -> dict:
        return dict((self._read(app_id).get(source) or {}).get("data") or {})

    def _local(self, app_id: str, source: str) -> dict | None:
        """Seed a source from ASSella's cached depot map — never the network.

        Returns ``{"at": epoch, "data": {...}}`` when ASSella has an expanded,
        authoritative row for this appid, else ``None`` so the caller goes to
        the network. The timestamp is ASSella's ``apps.last_updated``, so the
        seed ages exactly like a real fetch: a stale row still triggers the
        background refresh that only the network can satisfy.
        """
        if self.library is None:
            return None
        row = self.library.steam_app_depots(app_id)
        if not row:
            return None
        at = float(row.get("at") or 0)
        if source == "store":
            return {
                "at": at,
                "data": {
                    "name": row.get("name") or "",
                    "packages": [],
                    "dlc": list(row.get("dlc") or []),
                },
            }
        depots: dict[str, dict] = {}
        for did, info in (row.get("depots") or {}).items():
            if not isinstance(info, dict):
                continue
            size = info.get("size")
            depots[str(did)] = {
                "name": info.get("name"),
                "dlcappid": info.get("dlcappid"),
                "config": {
                    "oslist": info.get("oslist") or "",
                    "osarch": info.get("osarch") or "",
                    "language": info.get("language") or "",
                },
                "manifests": {"public": {"size": size}} if size is not None else {},
            }
        return {"at": at, "data": {"common": {"name": row.get("name") or ""}, "depots": depots}}

    def _source(
        self, app_id: str, source: str, fetch, allow_network: bool, force: bool,
        local=None,
    ) -> dict:
        """Serve a cached source, refreshing it only when it is not fresh.

        A local seed (ASSella's DB) is tried before the network, so a fresh row
        answers with no request at all. ``allow_network=False`` never issues a
        request either way: it returns the cached copy (stale is fine) or
        ``{}``. With ``True`` a stale or missing entry is refreshed from the
        network, and a failed refresh keeps the existing copy rather than
        blanking the page. ``force=True`` (an explicit Refresh) skips the local
        seed and always asks the network for the latest.
        """
        record = self._read(app_id)
        state = self._age_state(record.get(source))
        if local is not None and state != "fresh" and not force:
            seed = local(app_id, source)
            if isinstance(seed, dict) and isinstance(seed.get("data"), dict) and seed["data"]:
                record[source] = {"at": float(seed.get("at") or 0), "data": seed["data"]}
                self._write(app_id, record)
                state = self._age_state(record.get(source))
        if not allow_network or (state == "fresh" and not force):
            return self._cached(app_id, source)
        fetched = fetch(app_id)
        if fetched is None:
            return self._cached(app_id, source)
        record = self._read(app_id)
        record[source] = {"at": time.time(), "data": fetched}
        self._write(app_id, record)
        return fetched

    # -- sources --------------------------------------------------------------
    def _store_details(self, app_id: str, allow_network: bool = True, force: bool = False) -> dict:
        return self._source(
            app_id, "store", self._fetch_store, allow_network, force, self._local
        )

    def _steamcmd_details(self, app_id: str, allow_network: bool = True, force: bool = False) -> dict:
        return self._source(
            app_id, "steamcmd", self._fetch_steamcmd, allow_network, force, self._local
        )

    @staticmethod
    def _fetch_store(app_id: str) -> dict | None:
        """None on failure; a dict (possibly empty) on success."""
        try:
            url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=english&cc=US"
            resp = requests.get(url, timeout=10)
            if resp.ok:
                return resp.json().get(app_id, {}).get("data", {}) or {}
        except Exception as exc:  # noqa: BLE001
            logger.debug("Store details failed for %s: %s", app_id, exc)
        return None

    @staticmethod
    def _fetch_steamcmd(app_id: str) -> dict | None:
        try:
            resp = requests.get(f"https://api.steamcmd.net/v1/info/{app_id}", timeout=10)
            if resp.ok:
                return resp.json().get("data", {}).get(app_id, {}) or {}
        except Exception as exc:  # noqa: BLE001
            logger.debug("SteamCMD details failed for %s: %s", app_id, exc)
        return None

    def app_details(self, app_id: str, allow_network: bool = True, force: bool = False) -> dict:
        """Store + SteamCMD metadata, with ``depot_dlc`` attribution.

        Answers from the disk cache while it is fresh. ``allow_network=False``
        never waits on the network (the game page's instant first paint);
        ``force=True`` refreshes even a fresh entry.
        """
        store = self._store_details(app_id, allow_network, force)
        cmd = self._steamcmd_details(app_id, allow_network, force)

        packages = [str(pkg) for pkg in store.get("packages", [])]
        depots = []
        depot_dlc: dict[str, str] = {}
        depot_meta: dict[str, dict] = {}
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

                cfg = raw_info.get("config", {}) if isinstance(raw_info.get("config"), dict) else {}
                manifests = raw_info.get("manifests", {}) if isinstance(raw_info.get("manifests"), dict) else {}
                public_manifest = manifests.get("public", {}) if isinstance(manifests.get("public"), dict) else {}
                size_bytes = public_manifest.get("size")
                try:
                    size_num = int(size_bytes) if size_bytes else 0
                except (ValueError, TypeError):
                    size_num = 0

                depot_meta[raw_id] = {
                    "name": raw_info.get("name") or "",
                    "oslist": cfg.get("oslist") or "",
                    "osarch": cfg.get("osarch") or "",
                    "language": cfg.get("language") or "",
                    "size_bytes": size_num,
                }

        # SteamCMD listofdlc (historical / complete catalog)
        cmd_dlc_raw = (
            cmd.get("extended", {}).get("listofdlc")
            or cmd.get("common", {}).get("listofdlc")
            or ""
        )
        cmd_dlcs = [
            str(part).strip()
            for part in str(cmd_dlc_raw).split(",")
            if str(part).strip().isdigit()
        ]
        store_dlcs = [
            str(d).strip()
            for d in (store.get("dlc") or [])
            if str(d).strip().isdigit()
        ]

        if cmd_dlcs:
            all_dlcs = list(dict.fromkeys(cmd_dlcs + store_dlcs))
        else:
            all_dlcs = list(dict.fromkeys(store_dlcs))

        cmd_set = set(cmd_dlcs)
        store_set = set(store_dlcs)

        # Catalog intersection safeguard:
        # If cmd_dlcs and store_dlcs intersect, store_dlcs defines the currently active DLCs.
        # If they don't intersect (e.g. Rocksmith 2014 where store lists song packs while
        # SteamCMD lists individual songs, or games where store returns no DLCs),
        # filtering would drop the entire catalog, so treat all known DLCs as active.
        if cmd_dlcs and store_set and (cmd_set & store_set):
            active_dlcs = [d for d in all_dlcs if d in store_set]
        else:
            active_dlcs = list(all_dlcs)

        return {
            "app_id": app_id,
            "name": store.get("name") or cmd.get("common", {}).get("name") or f"App {app_id}",
            "packages": list(set(packages)),
            "depots": list(set(depots)),
            "depot_dlc": depot_dlc,
            "depot_meta": depot_meta,
            "dlc": active_dlcs,
            "dlc_all": all_dlcs,
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
        """Steam library folders from the selected installation's libraryfolders.vdf."""
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

        if root and root.is_dir() and root not in libs:
            libs.append(root)
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
        # InstalledDepots carries a per-depot `dlcappid`, which is the same
        # authoritative depot -> owning-AppID field SteamCMD exposes. For an
        # installed game this gives us DLC attribution with no network call.
        out["installed_depots"] = self._parse_installed_depots(content)
        return out

    @staticmethod
    def _parse_installed_depots(content: str) -> dict:
        """`{depot_id: {manifest, size, dlcappid}}` from an appmanifest.

        Steam writes an ``InstalledDepots`` block of ``"<depot_id>" { ... }``
        entries; DLC-owned depots carry a ``"dlcappid"`` line inside them.
        """
        depots: dict = {}
        start = re.search(r'"InstalledDepots"\s*\{', content)
        if not start:
            return depots
        depth = 1
        current: str | None = None
        for line in content[start.end():].splitlines():
            stripped = line.strip()
            entry = re.match(r'"(\d+)"\s*$', stripped)
            if entry:
                current = entry.group(1)
                depots.setdefault(current, {})
                continue
            if stripped.startswith("}"):
                depth -= 1
                if depth <= 0:
                    break
                current = None
                continue
            if stripped.endswith("{"):
                depth += 1
                continue
            if current:
                for field in ("manifest", "size", "dlcappid"):
                    match = re.match(rf'"{field}"\s+"([^"]*)"', stripped)
                    if match:
                        depots[current][field] = match.group(1)
        return depots

    def install_info(self, app_id: str) -> dict:
        """Locate a game's install dir across every Steam library.

        Mirrors ASSella's get_atom_game_install_info: appmanifest_<appid>.acf's
        "installdir" under steamapps/common, plus staged download folders.
        """
        info = {
            "installed": False, "install_path": "", "library_path": "",
            "install_dir": "", "game_name": "", "buildid": "",
            "size_on_disk": 0, "downloading": False, "state_flags": 0,
            "installed_depots": {},
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
                "installed_depots": data.get("installed_depots") or {},
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
