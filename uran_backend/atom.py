"""AT0-M library view: game list, depot/DLC inspection, per-game detail.

Reads the AT0-M registry (plugin_library.json) plus Steam's appmanifest files
and exposes the state the AT0-M tab renders.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .context import Context
from .integrations import Integrations
from .library import PluginLibrary
from .manifests import Manifests
from .paths import SHARED_REDISTS
from .sls_config import (
    SlsConfig,
    parse_key_section,
    parse_list_section,
    sanitize_id,
)
from .steammeta import SteamMeta

logger = logging.getLogger("Uran")

# Batch checks fan out across a few threads; request pacing is enforced in
# hubcap._throttle, so this only needs to be small enough to overlap network
# latency with the next request.
CHECK_WORKERS = 3


class AtomLibrary:
    """The AT0-M tab's read model."""

    def __init__(
        self,
        ctx: Context,
        sls: SlsConfig,
        steam: SteamMeta,
        library: PluginLibrary,
        manifests: Manifests,
        integrations: Integrations,
    ):
        self.ctx = ctx
        self.sls = sls
        self.steam = steam
        self.library = library
        self.manifests = manifests
        self.integrations = integrations

    def list_games(self) -> list[dict]:
        """All AT0-M registered games with their install state."""
        games = []
        for app_id, record in (self.library.load() or {}).items():
            if not isinstance(record, dict):
                continue
            aid = sanitize_id(app_id)
            if not aid:
                continue
            install = self.steam.install_info(aid)
            games.append({
                "app_id": aid,
                "name": record.get("name") or install.get("game_name") or f"App {aid}",
                "installed": bool(install.get("installed")),
                "downloading": bool(install.get("downloading")),
                "install_path": install.get("install_path", ""),
                "install_dir": install.get("install_dir", ""),
                "size_on_disk": install.get("size_on_disk", 0),
                "buildid": install.get("buildid", ""),
                "depots": record.get("depots", []),
                "key_count": len(record.get("keys", {}) or {}),
                "dlc_only": bool(record.get("dlc_only")),
                "dlc_appids": record.get("dlc_appids", []),
                "updated_at": record.get("updated_at", 0),
                "source": record.get("source", "plugin_native"),
            })
        games.sort(key=lambda g: (not g["installed"], g["name"].lower()))
        return games

    def inspect(self, aid: str, record: dict) -> tuple[list[dict], list[dict], bool]:
        """Cross-reference a game's depots and DLCs against the live config.

        The DLC list is the union of every attribution source we have, so a DLC
        that owns depots still shows up even when Steam's own ``dlc`` list omits
        it. Each DLC carries ``depot_count`` so the UI can show what toggling it
        will add or remove.
        """
        record_depots = {str(d) for d in record.get("depots", [])}
        record_keys = {str(d): str(k) for d, k in (record.get("keys", {}) or {}).items()}
        record_names = {str(d): str(n) for d, n in (record.get("depot_names", {}) or {}).items()}

        enrichments = self.library.depot_enrichments(aid)
        for did, key in self.library.local_depot_keys(aid).items():
            record_keys.setdefault(str(did), str(key))

        cfg = self.ctx.sls_config()
        live_apps: set[str] = set()
        live_depots: set[str] = set()
        live_keys: set[str] = set()
        if cfg and cfg.exists():
            try:
                content = cfg.read_text(encoding="utf-8", errors="ignore")
                live_apps = set(parse_list_section(content, "AdditionalApps").keys())
                live_depots = set(parse_list_section(content, "AdditionalDepots").keys())
                live_keys = set(parse_key_section(content, "DecryptionKeys")[0].keys())
            except Exception as exc:  # noqa: BLE001
                logger.debug("SLS config parse error: %s", exc)

        try:
            details = self.steam.app_details(aid) or {}
        except Exception:  # noqa: BLE001
            details = {}
        steam_depots = {str(d) for d in (details.get("depots") or []) if str(d).isdigit()}
        depot_dlc = {str(k): str(v) for k, v in (details.get("depot_dlc") or {}).items()}

        # Same attribution the projection uses: depot id -> owning appid.
        owner_map = self.library.app_to_depots(aid, record=record, depot_dlc=depot_dlc)
        owner_of: dict[str, str] = {}
        for owner, ids in owner_map.items():
            for did in ids:
                owner_of[str(did)] = "" if owner == "base" else str(owner)

        # DLC universe: attribution + Steam's list + record + enrichment flag.
        dlc_ids = set(owner_map) - {"base"}
        dlc_ids |= {str(d) for d in (details.get("dlc") or []) if str(d).isdigit()}
        dlc_ids |= {str(d) for d in (record.get("dlc_appids") or []) if str(d).isdigit()}
        dlc_ids |= {str(d) for d in (record.get("enabled_dlc_appids") or []) if str(d).isdigit()}
        dlc_ids |= {str(d) for d in depot_dlc.values() if str(d).isdigit()}
        dlc_ids |= {d for d, info in enrichments.items() if info.get("is_dlc")}
        dlc_ids.discard(aid)

        dlcs_list: list[dict] = []
        for did in sorted(dlc_ids, key=lambda x: int(x) if x.isdigit() else 0):
            raw_name = enrichments.get(did, {}).get("name") or record_names.get(did) or f"DLC {did}"
            owned = owner_map.get(did) or set()
            dlcs_list.append({
                "id": did,
                "name": re.sub(r"^\[DLC\s*\d+\]\s*", "", raw_name),
                "in_config": did in live_apps,
                "depot_count": len(owned),
            })

        all_depots = (record_depots | set(enrichments) | set(record_keys) | steam_depots) - {aid}
        for ids in owner_map.values():
            all_depots |= ids
        all_depots = {d for d in all_depots if d not in dlc_ids}
        depots_list: list[dict] = []
        for did in sorted(all_depots, key=lambda x: int(x) if x.isdigit() else 0):
            enrich = enrichments.get(did, {})
            dname = (
                enrich.get("name")
                or record_names.get(did)
                or self.ctx.depot_names.get(did)
                or f"Depot {did}"
            )
            depots_list.append({
                "id": did,
                "name": dname,
                "in_config": did in live_depots,
                "has_key": did in live_keys or did in record_keys,
                "is_dlc": enrich.get("is_dlc", False) or "[dlc" in dname.lower(),
                "is_shared": did in SHARED_REDISTS,
                "os": enrich.get("oslist", ""),
                "owner": owner_of.get(did, ""),
            })

        dlcs_injected = bool(dlcs_list and all(d["in_config"] for d in dlcs_list))
        return depots_list, dlcs_list, dlcs_injected

    def detail(self, app_id: str) -> dict:
        """Per-game state for the detail page: toggles, depots, DLCs, install info."""
        aid = sanitize_id(app_id)
        if not aid:
            return {"ok": False, "error": "Invalid AppID"}
        record = self.library.load().get(aid) or {}
        install = self.steam.install_info(aid)
        game_dir = Path(install.get("install_path") or "")

        global_online = self.integrations.global_slsonline_enabled()
        fake = self.integrations.get_fake_appid(aid)
        eos = self.integrations.eos_status(game_dir) if install.get("installed") else "none"

        depots_detail, dlcs_detail, dlcs_injected = self.inspect(aid, record)

        return {
            "ok": True,
            "app_id": aid,
            "name": record.get("name") or install.get("game_name") or f"App {aid}",
            "installed": bool(install.get("installed")),
            "install_path": install.get("install_path", ""),
            "size_on_disk": install.get("size_on_disk", 0),
            "buildid": install.get("buildid", ""),
            "depots": record.get("depots", []),
            "key_count": len(record.get("keys", {}) or {}),
            "dlc_only": bool(record.get("dlc_only")),
            "slsonline": bool(fake) or global_online,
            "global_slsonline": global_online,
            "fake_appid": fake,
            "netsock": self.integrations.netsock_active(aid),
            "eos": eos,
            "eos_available": eos != "none",
            "registered": bool(record),
            "depots_detail": depots_detail,
            "dlcs_detail": dlcs_detail,
            "dlcs_injected": dlcs_injected,
        }

    def check_updates(self, app_id: str, use_cache: bool = True) -> dict:
        """Check whether an AT0-M game has new depots/keys ready on Hubcap.

        Tiered, cheapest first:

          0. ASSella's persisted ``at0m_update_status`` — free, no network, and
             identical to what the desktop tool concluded.
          1. Hubcap's free ``/manifest/{id}/contents`` preflight.
          2. Delta: what Hubcap holds minus what this machine already knows.

        Three states are reported, matching ASSella's vocabulary so the cached
        and freshly-computed answers are interchangeable:

          up_to_date       nothing on Hubcap that we do not already have
          update_available Hubcap holds depots we lack — a refetch gains something
          key_pending      Steam knows depots we lack that Hubcap has not
                           generated yet; re-check after the cooldown
        """
        aid = sanitize_id(app_id)
        if not aid:
            return {"ok": False, "error": "Invalid AppID"}

        record = self.library.load().get(aid) or {}

        # Tier 0 — ASSella already computed this; trust it while it is fresh.
        if use_cache:
            cached = self.library.cached_update_status(aid)
            if cached:
                return {
                    "ok": True,
                    "app_id": aid,
                    "status": cached["status"],
                    "has_update": cached["status"] == "update_available",
                    "new_depots": cached["new_depots"] or [],
                    "from": cached["from"],
                    "last_checked": cached.get("last_checked", 0),
                }

        # Tier 1 — Hubcap's free preflight.
        contents = self.manifests.contents(aid)
        if contents.get("error"):
            # An error is NOT "no updates". Reporting it as one turns a missing
            # API key into a confident "everything is up to date".
            return {
                "ok": False,
                "app_id": aid,
                "status": "error",
                "has_update": False,
                "new_depots": [],
                "error": contents["error"],
            }

        hubcap_depots: set[str] = set()
        for entry in contents.get("manifests", []):
            if isinstance(entry, dict) and entry.get("depot_id"):
                hubcap_depots.add(str(entry["depot_id"]))
        if not hubcap_depots and contents.get("manifest_map"):
            hubcap_depots = {str(k) for k in contents["manifest_map"].keys()}
        if not hubcap_depots and contents.get("depot_ids"):
            hubcap_depots = {str(d) for d in contents["depot_ids"]}

        known = self.library.known_depots_for(aid, record)
        offerable = {
            d for d in hubcap_depots
            if d.isdigit() and d not in SHARED_REDISTS and d != aid
        }
        new_depots = offerable - known

        if new_depots:
            return {
                "ok": True,
                "app_id": aid,
                "status": "update_available",
                "has_update": True,
                "new_depots": self._describe(sorted(new_depots)),
                "from": "live",
            }

        # Tier 2 — nothing new on Hubcap. If Steam knows about depots we lack
        # that Hubcap has not generated yet, that is `key_pending`, not
        # `up_to_date`: a refetch now would gain nothing, but it will soon.
        pending = self._pending_depots(aid, record)
        if pending:
            return {
                "ok": True,
                "app_id": aid,
                "status": "key_pending",
                "has_update": False,
                "new_depots": [],
                "pending_depots": self._describe(sorted(pending)),
                "cooldown_hours": self.library.KEY_PENDING_COOLDOWN // 3600,
                "from": "live",
            }

        return {
            "ok": True,
            "app_id": aid,
            "status": "up_to_date",
            "has_update": False,
            "new_depots": [],
            "from": "live",
        }

    def _describe(self, depot_ids) -> list[dict]:
        """Depot records with real names where the local cache has them."""
        return [{"id": did, "name": self.library.depot_name(did)} for did in depot_ids]

    def _pending_depots(self, aid: str, record: dict) -> set[str]:
        """Depots Steam knows about that we lack and Hubcap has not supplied.

        Only meaningful when we can see Steam's current depot list; without it
        we have no evidence a depot is missing, so we report nothing rather
        than guess.
        """
        details = self.steam.app_details(aid)
        steam_depots = {
            str(d)
            for d in details.get("depots", [])
            if str(d).isdigit() and str(d) not in SHARED_REDISTS and str(d) != aid
        }
        if not steam_depots:
            return set()

        known = self.library.known_depots_for(aid, record)
        return steam_depots - known

    def check_all_updates(self, use_cache: bool = True) -> dict:
        """Check every registered AT0-M game against Hubcap.

        Returns per-app results plus an aggregate that never hides a failure:
        `error_count` games could not be checked, and `ok` is false when any
        of them failed, so the UI cannot report a clean sweep it never did.

        Requests are spaced by hubcap.MIN_REQUEST_INTERVAL through a shared
        lock, so worker threads do not fire in parallel.
        """
        games = self.library.load() or {}
        if not games:
            return {
                "ok": True,
                "updates": {},
                "update_count": 0,
                "error_count": 0,
                "pending_count": 0,
                "checked": 0,
                "cached": 0,
            }

        def _check_one(aid: str) -> tuple[str, dict]:
            try:
                return aid, self.check_updates(aid, use_cache=use_cache)
            except Exception as exc:  # noqa: BLE001 - one bad game must not abort the batch
                return aid, {
                    "ok": False,
                    "app_id": aid,
                    "status": "error",
                    "has_update": False,
                    "new_depots": [],
                    "error": str(exc),
                }

        results: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=CHECK_WORKERS) as executor:
            futures = [executor.submit(_check_one, aid) for aid in games.keys()]
            for future in as_completed(futures):
                aid, result = future.result()
                results[aid] = result

        error_count = sum(1 for r in results.values() if r.get("status") == "error")
        pending_count = sum(1 for r in results.values() if r.get("status") == "key_pending")
        update_count = sum(1 for r in results.values() if r.get("has_update"))
        cached = sum(1 for r in results.values() if r.get("from") == "assella_cache")

        first_error = next(
            (r["error"] for r in results.values() if r.get("status") == "error"), ""
        )
        return {
            "ok": error_count == 0,
            "updates": results,
            "update_count": update_count,
            "error_count": error_count,
            "pending_count": pending_count,
            "checked": len(results),
            "cached": cached,
            "error": first_error if error_count else "",
        }
