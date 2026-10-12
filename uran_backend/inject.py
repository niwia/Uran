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

    # -- config rewrite -------------------------------------------------------
    def _inject_config(
        self,
        app_id: str,
        name: str,
        depot_keys: dict,
        manifest_ids: dict | None = None,
        dlc_appids: set | None = None,
        candidate_depots: set | None = None,
    ) -> dict:
        """Inject one game into config.yaml in a SINGLE atomic pass.

        Mirrors ASSella's `_patch_config` (NativeSteamDownloadTask) semantics:

          1. Plugins: yes              (required by the library-inject loader)
          2. AdditionalApps:           `  - {appid} # {game_name}`
          3. AdditionalDepots:         `  - {depot} # {game} [{desc}] ({appid})`, rebuilt
                                       sorted, ONLY depots that have keys (or are
                                       shared redists). Never an AppID.
          4. DecryptionKeys:           `  {depot}: {key} # ...`, rebuilt sorted. The root
                                       AppKey IS allowed here and is tagged `[AppKey]`.
          5. SmartTickets: 0x1

        Only depots that actually have a decryption key are registered: Steam
        fails the download with DepotWithoutKey otherwise. DLC AppIDs are
        excluded from AdditionalDepots/DecryptionKeys so they don't clobber the
        parent game's data.
        """
        app_id = sanitize_id(app_id)
        if not app_id:
            return {"ok": False, "error": "Invalid AppID"}

        cfg = self.ctx.sls_config()
        if cfg is None:
            return {"ok": False, "error": "SLSsteam config not found"}

        # Guard: refuse to register a game with no usable keys. Without an
        # AppKey Steam cannot download the game at all, and depots without keys
        # abort with DepotWithoutKey — a half-registered game is worse than none.
        if not depot_keys:
            return {
                "ok": False,
                "error": "No depot decryption keys available for this game — cannot register it.",
                "reason": "no_keys",
            }

        game_name = sanitize_comment(name) or f"App {app_id}"
        dlc_appids = {d for d in (sanitize_id(x) for x in (dlc_appids or ())) if d}
        content = cfg.read_text(encoding="utf-8", errors="ignore") if cfg.exists() else "Plugins: yes\nAdditionalApps:\n"

        # 1. Plugins: yes
        content = ensure_plugins_enabled(content)

        # 2. AdditionalApps
        content, _ = upsert_in_memory(content, "AdditionalApps", app_id, comment=game_name)

        # 3. AdditionalDepots — rebuilt sorted, keyed/shared only, never an AppID.
        # Candidates are the depots we hold a key for, plus any shared
        # redistributable the game actually reported. We never blanket-add the
        # whole SHARED_REDISTS set — that would claim every shared depot in
        # existence and take ownership of them on cleanup.
        keyed: dict[str, str] = {}
        for raw_id, raw_key in (depot_keys or {}).items():
            clean_id = sanitize_id(raw_id)
            clean_key = sanitize_key(raw_key)
            if clean_id and clean_key:
                keyed[clean_id] = clean_key
            elif raw_key:
                logger.warning("Skipping malformed key for %s", raw_id)

        candidates = set(keyed)
        candidates |= {
            d for d in (sanitize_id(x) for x in (candidate_depots or ()))
            if d and d in SHARED_REDISTS
        }
        depot_ids = [
            d for d in sort_ids(candidates)
            if d != app_id and d not in dlc_appids and (d in SHARED_REDISTS or d in keyed)
        ]

        depot_comments = {
            d: comment for d, comment in parse_list_section(content, "AdditionalDepots").items()
            # never keep base AppIDs in AdditionalDepots
            if d != app_id and d not in dlc_appids
        }
        for d in depot_ids:
            if d in SHARED_REDISTS:
                # Magic marker: marks these exempt from uninstall cleanup.
                depot_comments[d] = SHARED_COMMENT
            else:
                desc = sanitize_comment(self.ctx.depot_names.get(d, ""))
                depot_comments[d] = f"{game_name} [{desc}] ({app_id})" if desc else f"{game_name} ({app_id})"

        content = replace_section_block(content, "AdditionalDepots", [
            f"  - {d} # {depot_comments[d]}" if depot_comments.get(d) else f"  - {d}"
            for d in sort_ids(depot_comments)
        ])

        # 4. DecryptionKeys — merge into existing, sorted, DLC AppIDs excluded.
        all_keys, key_comments = parse_key_section(content, "DecryptionKeys")
        for d in dlc_appids:
            all_keys.pop(d, None)
            key_comments.pop(d, None)
        for d, k in keyed.items():
            # A DLC AppID is stored as appid==depotid in AdditionalApps, so
            # writing it here would claim ownership of another game's data.
            if d in dlc_appids:
                continue
            all_keys[d] = k
            if d in SHARED_REDISTS:
                key_comments[d] = SHARED_COMMENT
            elif d == app_id:
                # The root AppKey is legitimate here (unlike AdditionalDepots).
                key_comments[d] = f"{game_name} [AppKey] ({app_id})"
            else:
                desc = sanitize_comment(self.ctx.depot_names.get(d, ""))
                key_comments[d] = f"{game_name} [{desc}] ({app_id})" if desc else game_name

        content = replace_section_block(content, "DecryptionKeys", [
            f"  {d}: {all_keys[d]} # {key_comments[d]}" if key_comments.get(d) else f"  {d}: {all_keys[d]}"
            for d in sort_ids(all_keys)
        ])

        # 5. SmartTickets
        content = ensure_smart_tickets(content)

        # Optional manifest pinning (append, preserving the section as-is).
        for did, mid in (manifest_ids or {}).items():
            if sanitize_id(did) and sanitize_id(mid):
                content, _ = upsert_in_memory(content, "ManifestIds", did, value=str(mid))

        if not self.sls.write(content):
            return {"ok": False, "error": "Failed to write SLSsteam config"}

        logger.info(
            "Injected %s (%s): %d depot(s), %d key(s) in a single pass",
            game_name, app_id, len(depot_ids), len(keyed),
        )
        return {
            "ok": True,
            "app_id": app_id,
            "name": game_name,
            "depots_added": depot_ids,
            "keys_added": sort_ids(keyed),
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
                if app_id in (comment or "").lower()
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
        dlc_appids: set | None = None,
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
            resolved_dlcs = set(dlc_appids or ())
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
                resolved_dlcs |= {d for d in (manifest_res.get("dlc_appids") or []) if d}
            elif depot_keys:
                logger.info(
                    "Hubcap inquiry failed (%s), proceeding with %d cached keys",
                    manifest_res.get("error"), len(depot_keys),
                )
                status["depot_keys"] = sort_ids(depot_keys.keys())
            else:
                status["manifest_error"] = manifest_res.get("error")

            # 3. Top up from keys already in config, scoped to this game.
            depot_keys = self._merge_existing_keys(app_id, depot_keys, candidate_depots or set())

            result = self._inject_config(
                app_id, resolved_name, depot_keys, manifest_ids, resolved_dlcs, candidate_depots
            )
            if not result.get("ok"):
                status["error"] = result.get("error")
                status["blocked"] = result.get("reason")
                logger.warning("Inject blocked for %s: %s", app_id, result.get("error"))
            else:
                status["injected_depots"] = result.get("depots_added", [])
                status["injected_keys"] = result.get("keys_added", [])

                # 4. Register in the AT0-M library so ASSella manages this game
                #    exactly as if it had injected the game itself.
                depots_added = result.get("depots_added", [])
                if self.library.register(
                    app_id,
                    resolved_name,
                    depots_added,
                    depot_keys,
                    installdir="",
                    depot_names={d: self.ctx.depot_names.get(d, "") for d in depots_added},
                    # This UI injects the base game in normal AT0-M mode. The
                    # resolved DLC IDs above are metadata used to keep DLC AppIDs
                    # out of AdditionalDepots/DecryptionKeys; ASSella only stores
                    # dlc_appids for an actual DLC-only download.
                    dlc_appids=[],
                ):
                    status["registered"] = True
                    logger.info("Registered %s (%s) in plugin_library.json", resolved_name, app_id)
                else:
                    logger.warning(
                        "Config injected but plugin_library.json registration failed for %s", app_id
                    )

                # 5. Optional DLC registration (separate, batched write)
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
        dlc_ids = [sanitize_id(d) for d in details.get("dlc", [])]

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
            args=(aid, name, set(dlc_ids), set(depots)),
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

    # -- DLCs -----------------------------------------------------------------
    def fetch_dlcs(self, app_id: str) -> dict:
        """Register a game's DLC AppIDs in AdditionalApps, in one batched write.

        DLCs are added as AdditionalApps entries only — never AdditionalDepots.
        ASSella permits a DLC AppID in AdditionalDepots (Steam stores DLC as
        appid==depotid), but mixing them in here would also drag in unrelated
        depots, so we keep DLC handling to AdditionalApps.
        """
        details = self.steam.app_details(app_id)
        dlc_ids = [d for d in (sanitize_id(x) for x in details.get("dlc", [])) if d]
        if not dlc_ids:
            return {"ok": True, "count": 0, "message": "No DLCs found"}
        if self.ctx.sls_config() is None:
            return {"ok": False, "error": "SLSsteam config not found"}

        game_name = sanitize_comment(details.get("name") or f"App {app_id}")

        # Harvest from the base game's bundle (it usually carries DLC keys).
        manifest_res = self.manifests.fetch(app_id, persist_config=False)
        depot_keys = manifest_res.get("depot_keys", {}) if manifest_res.get("ok") else {}
        if not manifest_res.get("ok"):
            logger.warning("DLC fetch for %s: no Hubcap bundle (%s)", app_id, manifest_res.get("error"))

        keys_added: list[str] = []
        with self.sls.edit() as editor:
            editor.content = ensure_plugins_enabled(editor.content)
            editor.has_changes = True
            for dlc_id in dlc_ids:
                editor.add_app(dlc_id, comment=f"{game_name} DLC ({dlc_id})")
            for did, key in (depot_keys or {}).items():
                if editor.add_key(did, key, comment=self.ctx.depot_names.get(did, "")):
                    keys_added.append(did)

        if not editor.committed_successfully:
            return {"ok": False, "error": "Failed to write SLSsteam config"}
        return {
            "ok": True,
            "count": len(dlc_ids),
            "dlc_ids": dlc_ids,
            "apps_added": dlc_ids,
            "depots_added": [],
            "keys_added": sort_ids(keys_added),
        }

    def toggle_dlcs(self, app_id: str, enable: bool) -> dict:
        """Add or remove a game's DLC AppIDs in AdditionalApps and sync keyed depots."""
        aid = sanitize_id(app_id)
        if not aid:
            return {"ok": False, "error": "Invalid AppID"}

        if not enable:
            return self._remove_owned_dlcs(aid)

        dlc_ids = [d for d in (sanitize_id(x) for x in self.steam.app_details(aid).get("dlc", [])) if d]
        record = self.library.load().get(aid) or {}
        for did in record.get("dlc_appids", []):
            clean = sanitize_id(did)
            if clean and clean not in dlc_ids:
                dlc_ids.append(clean)

        manifest_res = self.manifests.fetch(aid, persist_config=False)
        if manifest_res.get("ok"):
            for did in manifest_res.get("dlc_appids", []):
                clean = sanitize_id(did)
                if clean and clean not in dlc_ids:
                    dlc_ids.append(clean)

        if not dlc_ids:
            return {"ok": False, "error": f"No DLCs found for AppID {aid}"}
        if self.ctx.sls_config() is None:
            return {"ok": False, "error": "SLSsteam config not found"}

        # DLC AppIDs and depot IDs are different namespaces. Use the database's
        # depot classification to select DLC depots, then take their keys from
        # the app bundle/library/database without registering base-game depots.
        dlc_depot_ids = self.library.dlc_depot_ids(aid)

        all_keys = dict(manifest_res.get("depot_keys", {})) if manifest_res.get("ok") else {}
        for did, key in (record.get("keys") or {}).items():
            all_keys.setdefault(str(did), str(key))
        for did, key in self.library.local_depot_keys(aid, dlc_depot_ids).items():
            all_keys.setdefault(str(did), str(key))
        depot_keys = {did: key for did, key in all_keys.items() if did in dlc_depot_ids}

        marker = _dlc_marker(aid)
        with self.sls.edit() as editor:
            editor.content = ensure_plugins_enabled(editor.content)
            editor.has_changes = True
            existing_apps = parse_list_section(editor.content, "AdditionalApps")
            existing_depots = parse_list_section(editor.content, "AdditionalDepots")
            existing_keys, _ = parse_key_section(editor.content, "DecryptionKeys")
            for dlc_id in dlc_ids:
                # Only claim entries this feature creates. Existing user entries
                # retain their comments and are never removed by the off toggle.
                if dlc_id not in existing_apps:
                    editor.add_app(dlc_id, comment=marker)
            for did, key in (depot_keys or {}).items():
                if did != aid and did not in existing_depots:
                    editor.add_depot(did, comment=marker)
                if did != aid and did not in existing_keys:
                    editor.add_key(did, key, comment=marker)

        if not editor.committed_successfully:
            return {"ok": False, "error": "Failed to write SLSsteam config"}

        lib = self.library.load()
        if aid in lib:
            lib[aid]["dlc_appids"] = dlc_ids
            lib[aid]["dlcs_injected"] = True
            self.library.save(lib)
        return {"ok": True, "count": len(dlc_ids), "dlc_ids": dlc_ids}

    def _remove_owned_dlcs(self, aid: str) -> dict:
        marker = _dlc_marker(aid)
        removed_apps = 0
        with self.sls.edit() as editor:
            for entry_id, comment in parse_list_section(editor.content, "AdditionalApps").items():
                if comment == marker:
                    removed_apps += editor.remove_app(entry_id)
            for entry_id, comment in parse_list_section(editor.content, "AdditionalDepots").items():
                if comment == marker:
                    editor.remove_depot(entry_id)
            _, key_comments = parse_key_section(editor.content, "DecryptionKeys")
            for entry_id, comment in key_comments.items():
                if comment == marker:
                    editor.remove_key(entry_id)

        if not editor.committed_successfully:
            return {"ok": False, "error": "Failed to write SLSsteam config"}

        lib = self.library.load()
        if aid in lib:
            lib[aid]["dlcs_injected"] = False
            self.library.save(lib)
        return {"ok": True, "count": removed_apps}

    def toggle_additional_app(self, app_id: str, dlc_appid: str, enable: bool) -> dict:
        """Add or remove a single AdditionalApps DLC entry and manage its keys."""
        aid = sanitize_id(app_id)
        dlc_id = sanitize_id(dlc_appid)
        if not aid or not dlc_id:
            return {"ok": False, "error": "Invalid AppID"}
        if self.ctx.sls_config() is None:
            return {"ok": False, "error": "SLSsteam config not found"}

        marker = _dlc_marker(aid)

        if enable:
            dlc_keys = self.library.local_depot_keys(dlc_id)
            if not dlc_keys:
                parent_keys = self.library.local_depot_keys(aid)
                if dlc_id in parent_keys:
                    dlc_keys[dlc_id] = parent_keys[dlc_id]

            dlc_depots = self.library.dlc_depot_ids(aid, dlc_id)

            with self.sls.edit() as editor:
                editor.content = ensure_plugins_enabled(editor.content)
                editor.has_changes = True
                existing_apps = parse_list_section(editor.content, "AdditionalApps")
                existing_depots = parse_list_section(editor.content, "AdditionalDepots")
                existing_keys, _ = parse_key_section(editor.content, "DecryptionKeys")

                if dlc_id not in existing_apps:
                    editor.add_app(dlc_id, comment=marker)
                for did in dlc_depots:
                    if did != aid and did not in existing_depots:
                        editor.add_depot(did, comment=marker)
                for did, key in dlc_keys.items():
                    if did != aid and did not in existing_depots:
                        editor.add_depot(did, comment=marker)
                    if did != aid and did not in existing_keys:
                        editor.add_key(did, key, comment=marker)

            if not editor.committed_successfully:
                return {"ok": False, "error": "Failed to write SLSsteam config"}

            lib = self.library.load()
            if aid in lib:
                dlcs = {str(d) for d in lib[aid].get("dlc_appids", [])}
                dlcs.add(dlc_id)
                lib[aid]["dlc_appids"] = sort_ids(dlcs)
                self.library.save(lib)

            signal_api("RELOAD", logger)
            return {"ok": True, "dlc_id": dlc_id, "enabled": True}

        with self.sls.edit() as editor:
            apps = parse_list_section(editor.content, "AdditionalApps")
            if dlc_id in apps:
                editor.apply(*remove_in_memory(editor.content, "AdditionalApps", dlc_id, is_list=True))
            depots = parse_list_section(editor.content, "AdditionalDepots")
            if dlc_id in depots and marker in (depots.get(dlc_id) or ""):
                editor.apply(*remove_in_memory(editor.content, "AdditionalDepots", dlc_id, is_list=True))
            _, key_comments = parse_key_section(editor.content, "DecryptionKeys")
            if dlc_id in key_comments and marker in (key_comments.get(dlc_id) or ""):
                editor.apply(*remove_in_memory(editor.content, "DecryptionKeys", dlc_id, is_list=False))

        lib = self.library.load()
        if aid in lib:
            lib[aid]["dlc_appids"] = [str(d) for d in lib[aid].get("dlc_appids", []) if str(d) != dlc_id]
            self.library.save(lib)

        signal_api("RELOAD", logger)
        return {"ok": True, "dlc_id": dlc_id, "enabled": False}


def _dlc_marker(aid: str) -> str:
    """Ownership comment marking entries this plugin's DLC feature created."""
    return f"uran:dlc:{aid}"


__all__ = ["Injector"]