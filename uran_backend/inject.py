"""Game injection into SLSsteam config.yaml.

One inject is one atomic pass: AppID, depots, decryption keys, manifest pins
and SmartTickets all land together, so SLSsteam never observes a half-registered
game.
"""

import logging
import threading

from .context import Context
from .guards import GuardService
from .library import PluginLibrary
from .manifests import Manifests
from .paths import SHARED_COMMENT, SHARED_REDISTS
from .sls_config import (
    SlsConfig,
    ensure_plugins_enabled,
    ensure_smart_tickets,
    parse_key_section,
    parse_list_section,
    remove_in_memory,
    replace_section_block,
    sanitize_comment,
    sanitize_id,
    sanitize_key,
    signal_api,
    sort_ids,
    upsert_in_memory,
)
from .steammeta import SteamMeta

logger = logging.getLogger("Uran")


class Injector:
    """Registers games into SLSsteam and tracks in-flight inject jobs."""

    def __init__(
        self,
        ctx: Context,
        sls: SlsConfig,
        steam: SteamMeta,
        library: PluginLibrary,
        manifests: Manifests,
        guards: GuardService,
    ):
        self.ctx = ctx
        self.sls = sls
        self.steam = steam
        self.library = library
        self.manifests = manifests
        self.guards = guards

    # -- config projection ----------------------------------------------------
    @staticmethod
    def _owned(comment: str, aid: str) -> bool:
        """True when a config comment marks an entry as ours for this game.

        Both shapes count: the per-depot projection tag ``(app_id)`` and the
        legacy DLC-toggle marker ``uran:dlc:app_id``.
        """
        c = comment or ""
        return f"({aid})" in c or f"uran:dlc:{aid}" in c

    def _depot_keys_for(self, app_id: str, record: dict, use_hubcap: bool) -> tuple[dict, dict, dict]:
        """Harvest every depot key we can for a game, plus its depot->owner map.

        Returns ``(depot_keys, owner_map, details)``. Keys come from the library
        record, config.yaml (scoped to this game), the local SQLite cache and,
        when ``use_hubcap`` is set, a fresh Hubcap bundle fetched WITHOUT writing
        config — the caller writes everything in one atomic pass.
        """
        details = self.steam.app_details(app_id)
        if not isinstance(details, dict):
            details = {}
        installed_depots = (
            (self.steam.install_info(app_id) or {}).get("installed_depots") or {}
        )
        owner_map = self.library.app_to_depots(
            app_id,
            record=record,
            depot_dlc=details.get("depot_dlc") or {},
            installed_depots=installed_depots,
        )

        depot_keys: dict[str, str] = {
            str(d): str(k) for d, k in (record.get("keys") or {}).items()
        }
        # Scope the merge to the base depots we attributed to this game. The
        # worker passes its broader candidate set instead, since it also knows
        # the parent appid's full injected depot list.
        depot_keys = self._merge_existing_keys(
            app_id, depot_keys, set(owner_map.get("base", ()))
        )
        for did, key in self.library.local_depot_keys(app_id).items():
            depot_keys.setdefault(str(did), str(key))

        if use_hubcap:
            res = self.manifests.fetch(app_id, persist_config=False)
            if res.get("ok"):
                depot_keys.update(res.get("depot_keys", {}))
                if res.get("game_name"):
                    details.setdefault("name", res["game_name"])
        return depot_keys, owner_map, details

    def _project_config(
        self,
        app_id: str,
        name: str,
        depot_keys: dict,
        owner_map: dict,
        enabled_dlc_ids,
        candidate_depots: set | None = None,
        manifest_ids: dict | None = None,
    ) -> dict:
        """Write config.yaml as the projection of the base game + enabled DLCs.

        This is the ASSella model: the config is a *projection* of what the user
        selected, rewritten whole each time, so turning a DLC off removes
        exactly what turning it on added. One atomic pass:

          1. Plugins: yes
          2. AdditionalApps:   base AppID + every ENABLED DLC AppID; our own
                               now-disabled DLC entries are removed.
          3. AdditionalDepots: base + enabled-DLC depots that have a key (or are
                               shared redists). Never an AppID; never a depot
                               owned by a disabled DLC.
          4. DecryptionKeys:   keys for exactly those depots + the root AppKey.
          5. SmartTickets: 0x1 (+ optional ManifestIds pins).

        Ownership rides in the comment as ``{game} ... ({app_id})`` so a later
        projection or uninstall can rewrite or remove exactly our lines.
        """
        aid = sanitize_id(app_id)
        if not aid:
            return {"ok": False, "error": "Invalid AppID"}

        cfg = self.ctx.sls_config()
        if cfg is None:
            return {"ok": False, "error": "SLSsteam config not found"}

        keyed: dict[str, str] = {}
        for raw_id, raw_key in (depot_keys or {}).items():
            clean_id = sanitize_id(raw_id)
            clean_key = sanitize_key(raw_key)
            if clean_id and clean_key:
                keyed[clean_id] = clean_key
            elif raw_key:
                logger.warning("Skipping malformed key for %s", raw_id)

        # Without a usable key we cannot register the game at all (Steam aborts
        # with DepotWithoutKey), so refuse rather than half-register.
        if not keyed:
            return {
                "ok": False,
                "error": "No depot decryption keys available for this game — cannot register it.",
                "reason": "no_keys",
            }

        enabled = {d for d in (sanitize_id(x) for x in (enabled_dlc_ids or ())) if d and d != aid}

        # depot id -> owning AppID ("" = base game). Depots we cannot attribute
        # are treated as base content: mounting a surplus keyed depot is
        # harmless, whereas hiding a needed one breaks the download.
        owner_of: dict[str, str] = {}
        for owner, ids in (owner_map or {}).items():
            if owner == "base":
                continue
            for did in ids or ():
                clean = sanitize_id(did)
                if clean and clean != aid:
                    owner_of.setdefault(clean, str(owner))
        for did in keyed:
            owner_of.setdefault(did, "")

        # Depots to mount: base + enabled DLCs, keyed (or shared redist).
        candidates = set(keyed)
        candidates |= {
            d for d in (sanitize_id(x) for x in (candidate_depots or ()))
            if d and d in SHARED_REDISTS
        }
        selected = {
            d for d in candidates
            if d != aid
            and (d in SHARED_REDISTS or d in keyed)
            and (owner_of.get(d, "") == "" or owner_of.get(d, "") in enabled)
        }

        game_name = sanitize_comment(name) or f"App {aid}"
        content = cfg.read_text(encoding="utf-8", errors="ignore") if cfg.exists() else "Plugins: yes\nAdditionalApps:\n"
        content = ensure_plugins_enabled(content)

        def tag(did: str) -> str:
            owner = owner_of.get(did, "")
            return f" [DLC {owner}]" if owner else ""

        def desc(did: str) -> str:
            return sanitize_comment(self.ctx.depot_names.get(did, ""))

        # 2. AdditionalApps — base + enabled DLCs; drop our now-disabled entries.
        for eid, comment in parse_list_section(content, "AdditionalApps").items():
            if eid != aid and eid not in enabled and self._owned(comment, aid):
                content, _ = remove_in_memory(content, "AdditionalApps", eid, is_list=True)
        content, _ = upsert_in_memory(content, "AdditionalApps", aid, comment=game_name)
        for dlc in sort_ids(enabled):
            content, _ = upsert_in_memory(
                content, "AdditionalApps", dlc,
                comment=f"{game_name} [DLC {dlc}] ({aid})",
            )

        # 3. AdditionalDepots — rebuild ours, keep other owners' comments.
        depot_comments: dict[str, str] = {}
        for d, c in parse_list_section(content, "AdditionalDepots").items():
            if d == aid or d in enabled or self._owned(c, aid):
                continue
            depot_comments[d] = c
        for did in sort_ids(selected):
            if did in SHARED_REDISTS:
                depot_comments[did] = SHARED_COMMENT
                continue
            dsc = desc(did)
            depot_comments[did] = (
                f"{game_name}{tag(did)} [{dsc}] ({aid})" if dsc
                else f"{game_name}{tag(did)} ({aid})"
            )
        content = replace_section_block(content, "AdditionalDepots", [
            f"  - {d} # {depot_comments[d]}" if depot_comments.get(d) else f"  - {d}"
            for d in sort_ids(depot_comments)
        ])

        # 4. DecryptionKeys — ours only, sorted; root AppKey allowed.
        all_keys, key_comments = parse_key_section(content, "DecryptionKeys")
        for did in list(all_keys):
            if did == aid or did in selected:
                continue
            if did in SHARED_REDISTS and did not in keyed:
                continue
            if self._owned(key_comments.get(did, ""), aid):
                all_keys.pop(did, None)
                key_comments.pop(did, None)
        for did in sort_ids(selected):
            if did not in keyed:
                continue
            all_keys[did] = keyed[did]
            if did in SHARED_REDISTS:
                key_comments[did] = SHARED_COMMENT
            else:
                dsc = desc(did)
                key_comments[did] = (
                    f"{game_name}{tag(did)} [{dsc}] ({aid})" if dsc
                    else f"{game_name}{tag(did)} ({aid})"
                )
        if aid in keyed:
            all_keys[aid] = keyed[aid]
            key_comments[aid] = f"{game_name} [AppKey] ({aid})"
        content = replace_section_block(content, "DecryptionKeys", [
            f"  {d}: {all_keys[d]} # {key_comments[d]}" if key_comments.get(d) else f"  {d}: {all_keys[d]}"
            for d in sort_ids(all_keys)
        ])

        # 5. SmartTickets (+ optional manifest pins).
        content = ensure_smart_tickets(content)
        for did, mid in (manifest_ids or {}).items():
            if sanitize_id(did) and sanitize_id(mid):
                content, _ = upsert_in_memory(content, "ManifestIds", did, value=str(mid))

        if not self.sls.write(content):
            return {"ok": False, "error": "Failed to write SLSsteam config"}

        logger.info(
            "Projected %s (%s): %d depot(s), %d key(s), %d DLC(s)",
            game_name, aid, len(selected), len(keyed), len(enabled),
        )
        return {
            "ok": True,
            "app_id": aid,
            "name": game_name,
            "depots_added": sort_ids(selected),
            "keys_added": sort_ids(d for d in (selected | {aid}) if d in keyed),
            "dlc_appids": sort_ids(enabled),
        }

    def _merge_existing_keys(self, app_id: str, depot_keys: dict, candidate_depots: set) -> dict:
        """Top up `depot_keys` from keys already present in config.yaml.

        Scoped deliberately: only depots already attributed to THIS game (by
        name/appid in their ownership comment) or among its known depots are
        reused. Merging every key in the config would register other games'
        depots under this game and break cleanup on both sides.
        """
        cfg = self.ctx.sls_config()
        if cfg is None or not cfg.exists():
            return depot_keys
        try:
            content = cfg.read_text(encoding="utf-8", errors="replace")
            keys, _ = parse_key_section(content, "DecryptionKeys")
            depot_comments = parse_list_section(content, "AdditionalDepots")

            owned = {
                did for did, comment in depot_comments.items()
                if self._owned(comment, app_id)
            }
            owned |= {d for d in candidate_depots if d}
            for did in owned:
                if did in keys and did not in depot_keys:
                    depot_keys[did] = keys[did]
        except Exception as exc:  # noqa: BLE001
            logger.debug("merge_existing_keys failed for %s: %s", app_id, exc)
        return depot_keys

    # -- job orchestration ----------------------------------------------------
    def _worker(
        self,
        app_id: str,
        name: str,
        candidate_depots: set | None = None,
    ) -> None:
        status = self.ctx.inject_status.setdefault(app_id, {})
        status["running"] = True
        try:
            # 1. Harvest local depot keys from the SQLite cache first, so a
            #    Hubcap outage does not block a game we can already handle.
            depot_keys = self.library.local_depot_keys(app_id, candidate_depots)
            if depot_keys:
                logger.info(
                    "Local DB: found %d cached depot key(s) for AppID %s", len(depot_keys), app_id
                )

            # 2. Harvest the Hubcap bundle WITHOUT writing config, so the whole
            #    inject lands as one atomic write below.
            manifest_res = self.manifests.fetch(app_id, persist_config=False)
            manifest_ids: dict[str, str] = {}
            resolved_name = name

            if manifest_res.get("ok"):
                hubcap_keys = dict(manifest_res.get("depot_keys", {}))
                depot_keys.update(hubcap_keys)
                if hubcap_keys:
                    self.library.save_local_depot_keys(app_id, hubcap_keys)
                status["depot_keys"] = sort_ids(depot_keys.keys())
                status["manifests"] = manifest_res.get("manifests", [])
                if self.ctx.read_setting("manifestid_pinning"):
                    manifest_ids = manifest_res.get("pinned_manifests", {})
                # The Lua carries the authoritative game name and DLC list.
                if manifest_res.get("game_name"):
                    resolved_name = manifest_res["game_name"]
            elif depot_keys:
                logger.info(
                    "Hubcap inquiry failed (%s), proceeding with %d cached keys",
                    manifest_res.get("error"), len(depot_keys),
                )
                status["depot_keys"] = sort_ids(depot_keys.keys())
            else:
                status["manifest_error"] = manifest_res.get("error")

            # 3. Top up from keys already in config, scoped to this game. This
            #    candidate set is broader than the projection's base set — it
            #    also covers the parent appid's full injected depot list.
            depot_keys = self._merge_existing_keys(app_id, depot_keys, candidate_depots or set())

            # 4. Project the config: base game only on inject (DLCs are opt-in).
            details = self.steam.app_details(app_id)
            installed_depots = (
                (self.steam.install_info(app_id) or {}).get("installed_depots") or {}
            )
            owner_map = self.library.app_to_depots(
                app_id,
                depot_dlc=((details or {}).get("depot_dlc") or {}),
                installed_depots=installed_depots,
            )
            result = self._project_config(
                app_id, resolved_name, depot_keys, owner_map, set(),
                candidate_depots=candidate_depots, manifest_ids=manifest_ids,
            )
            if not result.get("ok"):
                status["error"] = result.get("error")
                status["blocked"] = result.get("reason")
                logger.warning("Inject blocked for %s: %s", app_id, result.get("error"))
            else:
                status["injected_depots"] = result.get("depots_added", [])
                status["injected_keys"] = result.get("keys_added", [])

                # 5. Register in the AT0-M library so ASSella manages this game
                #    exactly as if it had injected the game itself.
                depots_added = result.get("depots_added", [])
                if self.library.register(
                    app_id,
                    resolved_name,
                    depots_added,
                    depot_keys,
                    installdir="",
                    depot_names={d: self.ctx.depot_names.get(d, "") for d in depots_added},
                    # This UI injects the base game in normal AT0-M mode. DLC
                    # layers are opt-in and enabled later via set_game_apps.
                    dlc_appids=[],
                ):
                    status["registered"] = True
                    logger.info("Registered %s (%s) in plugin_library.json", resolved_name, app_id)
                else:
                    logger.warning(
                        "Config injected but plugin_library.json registration failed for %s", app_id
                    )

                # 6. Optional DLC registration (separate, batched write)
                if self.ctx.read_setting("fetch_dlcs_on_inject"):
                    self.fetch_dlcs(app_id)

            status["done"] = True
            status["running"] = False
            logger.info("Background inject complete for %s (%s)", resolved_name, app_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("Background inject failed for %s: %s", app_id, exc, exc_info=True)
            status["error"] = str(exc)
            status["done"] = True
            status["running"] = False

    def inject(self, app_id: str) -> dict:
        """Kick off a background inject after the preflight guards pass."""
        aid = sanitize_id(str(app_id).strip())
        if not aid:
            return {"error": "Invalid AppID"}

        details = self.steam.app_details(aid)
        name = details.get("name", f"App {aid}")
        depots = details.get("depots", [])

        # Preflight 1: SLS environment
        env = self.guards.check_sls_environment()
        if not env.get("ok"):
            return {"error": env.get("error", "SLS environment validation failed"),
                    "blocked": env.get("reason")}

        # Preflight 2: already registered
        if self.guards.is_app_added(aid):
            return {"error": f"{name} is already registered in your library.", "already_added": True}

        # Preflight 3: Hubcap key
        if not self.ctx.hubcap_key.current():
            return {
                "error": "No Hubcap API key found. Set morrenus_api_key in ASSella "
                         "settings (~/.config/Tachibana Labs/ACCELA.conf) or add an "
                         "override in this plugin's settings.",
                "blocked": "no_api_key",
            }

        # Automatic safety backup
        self.sls.create_backup("pre_inject")

        self.ctx.inject_status[aid] = {"done": False, "running": True, "app_id": aid, "name": name}

        self.ctx.recent_injects.insert(0, {"app_id": aid, "name": name, "depots_resolved": depots})
        del self.ctx.recent_injects[20:]

        threading.Thread(
            target=self._worker,
            args=(aid, name, set(depots)),
            daemon=True,
        ).start()

        return {"name": name, "depots": depots, "fetching": True}

    def status(self, app_id: str) -> dict | None:
        return self.ctx.inject_status.get(str(app_id))

    def recent(self) -> list[dict]:
        """Merge live worker status into the recent list for the UI."""
        out = []
        for entry in self.ctx.recent_injects:
            merged = dict(entry)
            status = self.ctx.inject_status.get(str(entry.get("app_id")))
            if status:
                for key in ("done", "running", "error", "blocked", "registered",
                            "depot_keys", "injected_depots", "injected_keys",
                            "manifests", "manifest_error"):
                    if key in status:
                        merged[key] = status[key]
            out.append(merged)
        return out

    # -- appid-driven projection ----------------------------------------------
    def _enabled_dlcs(self, app_id: str) -> list[str]:
        """DLC AppIDs currently enabled for a game, read from the live config."""
        aid = sanitize_id(app_id)
        if not aid:
            return []
        cfg = self.ctx.sls_config()
        record = self.library.load().get(aid) or {}
        known = {str(d) for d in (record.get("enabled_dlc_appids") or []) if str(d).isdigit()}
        known |= {str(d) for d in (record.get("dlc_appids") or []) if str(d).isdigit()}
        if cfg is None or not cfg.exists():
            return sort_ids(known)
        try:
            content = cfg.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return sort_ids(known)
        apps = parse_list_section(content, "AdditionalApps")
        enabled = {
            d for d, c in apps.items()
            if d != aid and (self._owned(c, aid) or d in known)
        }
        return sort_ids(enabled)

    def set_game_apps(self, app_id: str, enabled_dlc_ids=None, use_hubcap: bool = True) -> dict:
        """Enable exactly the given DLC AppIDs, reprojecting config.yaml.

        The base game is always included — this only turns DLC layers on and
        off. Going off removes exactly the depots and keys that DLC contributed
        (the residue bug in the old per-DLC toggle). The requested set is
        intersected with the DLCs we can actually see for the game, so a stale
        id from the UI cannot claim an unrelated app.
        """
        aid = sanitize_id(app_id)
        if not aid:
            return {"ok": False, "error": "Invalid AppID"}
        if self.ctx.sls_config() is None:
            return {"ok": False, "error": "SLSsteam config not found"}

        record = self.library.load().get(aid) or {}
        depot_keys, owner_map, details = self._depot_keys_for(aid, record, use_hubcap)

        known = set(owner_map) - {"base"}
        known |= {d for d in (sanitize_id(x) for x in (details.get("dlc") or [])) if d}
        known |= {d for d in (sanitize_id(x) for x in (details.get("depot_dlc") or {}).values()) if d}
        known |= {str(d) for d in (record.get("dlc_appids") or []) if str(d).isdigit()}
        known |= {str(d) for d in (record.get("enabled_dlc_appids") or []) if str(d).isdigit()}
        known.discard(aid)

        requested = {d for d in (sanitize_id(x) for x in (enabled_dlc_ids or ())) if d and d != aid}
        enabled = requested & known if known else requested

        result = self._project_config(
            aid,
            details.get("name") or record.get("name") or f"App {aid}",
            depot_keys,
            owner_map,
            enabled,
            candidate_depots={str(d) for d in (record.get("depots") or [])},
        )
        if result.get("ok"):
            depots_added = result.get("depots_added", [])
            self.library.register(
                aid,
                result.get("name") or f"App {aid}",
                depots_added,
                depot_keys,
                installdir=record.get("installdir", ""),
                depot_names={d: self.ctx.depot_names.get(d, "") for d in depots_added},
                dlc_appids=record.get("dlc_appids", []),
                enabled_dlc_appids=sort_ids(enabled),
            )
            signal_api("RELOAD", logger)
        return result

    def refresh(self, app_id: str) -> dict:
        """Re-project a game's config from the freshest keys and depots.

        The base game always stays on and currently-enabled DLCs are preserved.
        This is how a freshly fetched base-game key gets its depot mounted: a
        plain manifest refetch only writes the key into DecryptionKeys and never
        touches AdditionalDepots, so before this the depot was never mounted.
        """
        aid = sanitize_id(app_id)
        if not aid:
            return {"ok": False, "error": "Invalid AppID"}
        return self.set_game_apps(aid, self._enabled_dlcs(aid), use_hubcap=True)

    # -- DLCs -----------------------------------------------------------------
    def fetch_dlcs(self, app_id: str) -> dict:
        """Enable every DLC the game exposes, as one full projection.

        DLC AppIDs land in AdditionalApps and their keyed depots in
        AdditionalDepots/DecryptionKeys, all tagged so the off path can remove
        exactly what this added.
        """
        aid = sanitize_id(app_id)
        if not aid:
            return {"ok": False, "error": "Invalid AppID"}
        details = self.steam.app_details(aid)
        dlcs = {d for d in (sanitize_id(x) for x in ((details or {}).get("dlc") or [])) if d}
        if not dlcs:
            res = self.manifests.fetch(aid, persist_config=False)
            if res.get("ok"):
                dlcs = {d for d in (sanitize_id(x) for x in (res.get("dlc_appids") or [])) if d}
        if not dlcs:
            return {"ok": True, "count": 0, "message": "No DLCs found"}
        result = self.set_game_apps(aid, sort_ids(dlcs), use_hubcap=True)
        if result.get("ok"):
            result["count"] = len(dlcs)
            result["apps_added"] = sort_ids(dlcs)
        return result

    def toggle_dlcs(self, app_id: str, enable: bool) -> dict:
        """Turn every DLC of a game on, or off, in one reprojection."""
        aid = sanitize_id(app_id)
        if not aid:
            return {"ok": False, "error": "Invalid AppID"}
        if not enable:
            result = self.set_game_apps(aid, [], use_hubcap=True)
            result.setdefault("count", 0)
            return result

        record = self.library.load().get(aid) or {}
        details = self.steam.app_details(aid)
        if not isinstance(details, dict):
            details = {}
        dlcs = {d for d in (sanitize_id(x) for x in (details.get("dlc") or [])) if d}
        details_dlc = details.get("dlc_appids")
        if details_dlc:
            dlcs |= {d for d in (sanitize_id(x) for x in details_dlc) if d}
        dlcs |= {d for d in (sanitize_id(x) for x in (record.get("dlc_appids") or [])) if d}
        dlcs.discard(aid)
        if not dlcs:
            res = self.manifests.fetch(aid, persist_config=False)
            if res.get("ok"):
                dlcs = {d for d in (sanitize_id(x) for x in (res.get("dlc_appids") or [])) if d}
        if not dlcs:
            return {"ok": False, "error": f"No DLCs found for AppID {aid}"}
        result = self.set_game_apps(aid, sort_ids(dlcs), use_hubcap=True)
        if result.get("ok"):
            result["count"] = len(dlcs)
            result["dlc_ids"] = sort_ids(dlcs)
        return result

    def toggle_additional_app(self, app_id: str, dlc_appid: str, enable: bool) -> dict:
        """Enable or disable one DLC AppID by reprojecting the whole config.

        Reprojection guarantees a disable removes exactly what the enable added:
        the DLC's depots and keys disappear with its AdditionalApps entry,
        instead of lingering because they were written by a different path.
        """
        aid = sanitize_id(app_id)
        dlc_id = sanitize_id(dlc_appid)
        if not aid or not dlc_id:
            return {"ok": False, "error": "Invalid AppID"}
        enabled = set(self._enabled_dlcs(aid))
        if enable:
            enabled.add(dlc_id)
        else:
            enabled.discard(dlc_id)
        result = self.set_game_apps(aid, sort_ids(enabled), use_hubcap=True)
        if result.get("ok"):
            result["dlc_id"] = dlc_id
            result["enabled"] = bool(enable)
        return result

    def toggle_additional_depot(self, app_id: str, depot_id: str, enable: bool) -> dict:
        """Add or remove an individual depot from AdditionalDepots."""
        aid = sanitize_id(app_id)
        did = sanitize_id(depot_id)
        if not aid or not did:
            return {"ok": False, "error": "Invalid ID"}
        if self.ctx.sls_config() is None:
            return {"ok": False, "error": "SLSsteam config not found"}
        with self.sls.edit() as editor:
            if enable:
                dname = self.ctx.depot_names.get(did, "")
                comment = f"[{dname}] ({aid})" if dname else f"({aid})"
                editor.add_depot(did, comment=comment)
            else:
                editor.remove_depot(did)
        if not editor.committed_successfully:
            return {"ok": False, "error": "Failed to update SLSsteam config"}
        signal_api("RELOAD", logger)
        return {"ok": True, "depot_id": did, "enabled": bool(enable)}

    def toggle_decryption_key(self, app_id: str, target_id: str, enable: bool) -> dict:
        """Add or remove an individual key from DecryptionKeys."""
        aid = sanitize_id(app_id)
        tid = sanitize_id(target_id)
        if not aid or not tid:
            return {"ok": False, "error": "Invalid ID"}
        if self.ctx.sls_config() is None:
            return {"ok": False, "error": "SLSsteam config not found"}
        with self.sls.edit() as editor:
            if enable:
                rec = self.library.load().get(aid) or {}
                k = (rec.get("keys") or {}).get(tid)
                if not k:
                    k = self.library.local_depot_keys(aid).get(tid)
                if not k:
                    return {"ok": False, "error": f"No key found locally for ID {tid}"}
                comment = f"[AppKey] ({aid})" if tid == aid else f"({aid})"
                editor.add_key(tid, k, comment=comment)
            else:
                editor.remove_key(tid)
        if not editor.committed_successfully:
            return {"ok": False, "error": "Failed to update SLSsteam config"}
        signal_api("RELOAD", logger)
        return {"ok": True, "target_id": tid, "enabled": bool(enable)}


__all__ = ["Injector"]