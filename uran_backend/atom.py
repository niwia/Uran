"""AT0-M library view: game list, depot/DLC inspection, per-game detail.

Reads the AT0-M registry (plugin_library.json) plus Steam's appmanifest files
and exposes the state the AT0-M tab renders.
"""

import logging
import re
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
        """Cross-reference a game's depots and DLCs against the live config."""
        record_depots = {str(d) for d in record.get("depots", [])}
        record_keys = {str(d): str(k) for d, k in (record.get("keys", {}) or {}).items()}
        record_names = {str(d): str(n) for d, n in (record.get("depot_names", {}) or {}).items()}
        record_dlcs = [str(d) for d in record.get("dlc_appids", [])]

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

        if not record_dlcs:
            try:
                record_dlcs = [str(d) for d in self.steam.app_details(aid).get("dlc", [])]
            except Exception:  # noqa: BLE001
                pass
        for did, info in enrichments.items():
            if info.get("is_dlc") and did not in record_dlcs:
                record_dlcs.append(did)

        dlcs_list: list[dict] = []
        for did in sorted(set(record_dlcs), key=lambda x: int(x) if x.isdigit() else 0):
            raw_name = enrichments.get(did, {}).get("name") or record_names.get(did) or f"DLC {did}"
            dlcs_list.append({
                "id": did,
                "name": re.sub(r"^\[DLC\s*\d+\]\s*", "", raw_name),
                "in_config": did in live_apps,
            })

        all_depots = (record_depots | set(enrichments.keys()) | set(record_keys.keys())) - {aid}
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

    def check_updates(self, app_id: str) -> dict:
        """Check if an AT0-M game has new depots/keys ready in Hubcap.

        Mirrors ASSella's At0mUpdateChecker:
          1. Collects locally known depots/keys.
          2. Compares against Steam's current content depots.
          3. Checks Hubcap free preflight (/manifest/{appid}/contents).
        """
        aid = sanitize_id(app_id)
        if not aid:
            return {"ok": False, "error": "Invalid AppID"}

        record = self.library.load().get(aid) or {}
        known_depots = {str(d) for d in (record.get("depots") or [])}
        known_keys = {str(k) for k in (record.get("keys") or {}).keys()}

        # Steam content depots
        details = self.steam.app_details(aid)
        steam_depots = {
            str(d)
            for d in details.get("depots", [])
            if str(d).isdigit() and str(d) not in SHARED_REDISTS and str(d) != aid
        }

        missing_depots = steam_depots - (known_depots | known_keys)
        if not missing_depots:
            return {
                "ok": True,
                "app_id": aid,
                "status": "up_to_date",
                "missing_count": 0,
                "new_depots": [],
            }

        # Hubcap preflight (free / zero quota)
        contents = self.manifests.contents(aid)
        if contents.get("error"):
            return {
                "ok": True,
                "app_id": aid,
                "status": "unknown",
                "error": contents["error"],
                "missing_count": len(missing_depots),
                "new_depots": [],
            }

        hubcap_depots = set()
        for m in contents.get("manifests", []):
            if isinstance(m, dict) and m.get("depot_id"):
                hubcap_depots.add(str(m["depot_id"]))
        if not hubcap_depots and contents.get("manifest_map"):
            hubcap_depots = {str(k) for k in contents["manifest_map"].keys()}

        ready_depots = missing_depots & hubcap_depots
        if ready_depots:
            new_depots_info = []
            for did in sorted(ready_depots, key=lambda x: int(x) if x.isdigit() else 0):
                new_depots_info.append({"id": did, "name": f"Depot {did}"})
            return {
                "ok": True,
                "app_id": aid,
                "status": "update_available",
                "missing_count": len(missing_depots),
                "new_depots": new_depots_info,
                "ready_count": len(ready_depots),
            }

        return {
            "ok": True,
            "app_id": aid,
            "status": "up_to_date",
            "missing_pending": list(missing_depots),
            "missing_count": len(missing_depots),
            "new_depots": [],
        }