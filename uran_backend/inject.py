"""Game injection into SLSsteam config.yaml.

One inject is one atomic pass: AppID, depots, decryption keys, manifest pins
and SmartTickets all land together, so SLSsteam never observes a half-registered
game.
"""

import logging
from pathlib import Path
import re
import threading

from .context import Context
from .depot_tags import qualify_dlc_name
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
    parse_manifest_section,
    remove_in_memory,
    replace_section_block,
    sanitize_comment,
    sanitize_id,
    sanitize_key,
    section_bounds,
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


    def _heal_acf_if_needed(self, app_id: str, manifest_ids: dict | None = None) -> bool:
        """Heal appmanifest_<aid>.acf if it is stuck in manifest-0 / update-required loop.

        When Steam tries to update an unlicensed depot with manifest '0', Steam CDN returns
        401 Unauthorized in an infinite loop and marks StateFlags=518 (Update Required | Paused).
        Writing the known manifest GID and resetting StateFlags=4 (Fully Installed) stops the loop.
        """
        info = self.steam.install_info(app_id) or {}
        acf_path = info.get("acf_path")
        if not acf_path:
            return False
        p = Path(acf_path)
        if not p.is_file():
            return False
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            installed_depots = self.steam._parse_installed_depots(content)
            changed = False
            for did, d_data in installed_depots.items():
                if str(d_data.get("manifest", "")) in ("0", ""):
                    mid = (manifest_ids or {}).get(did)
                    if not mid:
                        cache = self.ctx.depotcache()
                        if cache:
                            manifest_files = list(cache.glob(f"{did}_*.manifest"))
                            if manifest_files:
                                stem = manifest_files[0].stem
                                mid = stem.split("_", 1)[1] if "_" in stem else None
                    if mid and sanitize_id(mid):
                        pat = re.compile(
                            rf'("{re.escape(did)}"\s*\{{[^}}]*"manifest"\s*)"0"',
                            re.DOTALL,
                        )
                        new_content, n = pat.subn(rf'\g<1>"{mid}"', content, count=1)
                        if n:
                            content = new_content
                            changed = True
            current_flags = int(info.get("state_flags") or 0)
            if changed or current_flags in (514, 518):
                content = re.sub(r'"StateFlags"\s*"\d+"', '"StateFlags"\t\t"4"', content, count=1)
                content = re.sub(r'"UpdateResult"\s*"\d+"', '"UpdateResult"\t\t"0"', content, count=1)
                p.write_text(content, encoding="utf-8")
                logger.info("Healed appmanifest for %s at %s", app_id, acf_path)
                return True
        except Exception as exc:
            logger.debug("Failed healing appmanifest for %s: %s", app_id, exc)
        return False

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
        app_tokens: dict | None = None,
        selected_depots: set | None = None,
        selected_dlcs: set | None = None,
        selected_keys: set | None = None,
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

        if selected_dlcs is not None:
            enabled = {d for d in (sanitize_id(x) for x in selected_dlcs) if d and d != aid}
        else:
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
        # The Advanced depot selector passes the exact set the user ticked; we
        # still require a key (or shared redist) so an unkeyable tick cannot
        # half-register the game.
        if selected_depots is not None:
            wanted = {d for d in (sanitize_id(x) for x in selected_depots) if d}
            selected = {
                d for d in wanted
                if d != aid and (d in SHARED_REDISTS or d in keyed)
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
            raw_dlc_name = self.ctx.depot_names.get(dlc, "")
            label = qualify_dlc_name(raw_dlc_name, dlc, game_name) if raw_dlc_name else f"DLC {dlc}"
            content, _ = upsert_in_memory(
                content, "AdditionalApps", dlc,
                comment=f"{game_name} [{label}] ({aid})",
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

        # 4. DecryptionKeys — keep keys for all base depots + enabled DLCs; root AppKey allowed.
        # Alternate OS depots or unmounted base depots still keep their keys in the keychain
        # so Steam never fails with 'Missing decryption key'.
        allowed_keys = {d for d in (sanitize_id(x) for x in selected_keys) if d} if selected_keys is not None else None
        all_keys, key_comments = parse_key_section(content, "DecryptionKeys")

        # Drop keys that belong to this game if they are owned by disabled DLCs or explicitly unselected
        for did in list(all_keys):
            if did == aid:
                continue
            if did in SHARED_REDISTS and did not in keyed:
                continue
            if self._owned(key_comments.get(did, ""), aid):
                owner = owner_of.get(did, "")
                if (owner and owner not in enabled) or (allowed_keys is not None and did not in allowed_keys):
                    all_keys.pop(did, None)
                    key_comments.pop(did, None)

        # Add / update keys for base game and enabled DLCs
        for did in sort_ids(keyed):
            if did == aid:
                continue
            owner = owner_of.get(did, "")
            if owner and owner not in enabled:
                continue
            if allowed_keys is not None and did not in allowed_keys:
                all_keys.pop(did, None)
                key_comments.pop(did, None)
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

        if aid in keyed and (allowed_keys is None or aid in allowed_keys):
            all_keys[aid] = keyed[aid]
            key_comments[aid] = f"{game_name} [AppKey] ({aid})"
        elif aid in all_keys and allowed_keys is not None and aid not in allowed_keys:
            all_keys.pop(aid, None)
            key_comments.pop(aid, None)

        content = replace_section_block(content, "DecryptionKeys", [
            f"  {d}: {all_keys[d]} # {key_comments[d]}" if key_comments.get(d) else f"  {d}: {all_keys[d]}"
            for d in sort_ids(all_keys)
        ])

        # 5. SmartTickets (+ clean any leftover manifest pins for this game).
        content = ensure_smart_tickets(content)
        all_manifests, manifest_comments = parse_manifest_section(content)
        manifests_changed = False
        for did in list(all_manifests):
            if self._owned(manifest_comments.get(did, ""), aid) or did in candidates or did in keyed or did == aid:
                all_manifests.pop(did, None)
                manifest_comments.pop(did, None)
                manifests_changed = True
        if manifests_changed:
            if all_manifests:
                content = replace_section_block(content, "ManifestIds", [
                    f"  {d}: {all_manifests[d]} # {manifest_comments[d]}" if manifest_comments.get(d) else f"  {d}: {all_manifests[d]}"
                    for d in sort_ids(all_manifests)
                ])
            else:
                bounds = section_bounds(content, "ManifestIds")
                if bounds:
                    content = replace_section_block(content, "ManifestIds", [])

        # 6. AppTokens — write license tokens from Hubcap Lua.
        if app_tokens:
            existing_tokens = parse_app_token_section(content)
            # Keep existing tokens that don't belong to this game.
            cleaned: dict[str, str] = {}
            for tid, tval in existing_tokens.items():
                if not self._owned("", aid) and tid not in (app_tokens or {}):
                    cleaned[tid] = tval
            for tid, tval in app_tokens.items():
                cleaned[tid] = tval
            if cleaned:
                content = replace_section_block(content, "AppTokens", [
                    f"  {tid}: {tval}" for tid, tval in sort_ids(cleaned)
                ])

        if not self.sls.write(content):
            return {"ok": False, "error": "Failed to write SLSsteam config"}

        self._heal_acf_if_needed(aid, manifest_ids)

        active_keys = [
            d for d in keyed
            if (allowed_keys is None or d in allowed_keys)
            and (d == aid or owner_of.get(d, "") == "" or owner_of.get(d, "") in enabled)
        ]
        logger.info(
            "Projected %s (%s): %d depot(s), %d key(s), %d DLC(s)",
            game_name, aid, len(selected), len(active_keys), len(enabled),
        )
        return {
            "ok": True,
            "app_id": aid,
            "name": game_name,
            "depots_added": sort_ids(selected),
            "keys_added": sort_ids(active_keys),
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
            resolved_name = name

            if manifest_res.get("ok"):
                hubcap_keys = dict(manifest_res.get("depot_keys", {}))
                depot_keys.update(hubcap_keys)
                if hubcap_keys:
                    self.library.save_local_depot_keys(app_id, hubcap_keys)
                status["depot_keys"] = sort_ids(depot_keys.keys())
                status["manifests"] = manifest_res.get("manifests", [])
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
                candidate_depots=candidate_depots,
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
        known |= {d for d in (sanitize_id(x) for x in (details.get("dlc_all") or [])) if d}
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

    def apply_depot_selection(
        self,
        app_id: str,
        depot_ids=None,
        dlc_ids=None,
        key_ids=None,
        use_hubcap: bool = True,
    ) -> dict:
        """Mount exactly the depot, DLC, and key set the Advanced selector ticked.

        This is the direct counterpart to ASSella's depot picker: the ticked
        depot ids become AdditionalDepots, the ticked DLC AppIDs become
        AdditionalApps, and the ticked keys are written into DecryptionKeys.
        The whole config is rewritten in one inode-preserving pass, so SLSsteam's
        inotify watcher sees a single coherent change.
        """
        aid = sanitize_id(app_id)
        if not aid:
            return {"ok": False, "error": "Invalid AppID"}
        if self.ctx.sls_config() is None:
            return {"ok": False, "error": "SLSsteam config not found"}

        record = self.library.load().get(aid) or {}
        depot_keys, owner_map, details = self._depot_keys_for(aid, record, use_hubcap)
        name = details.get("name") or record.get("name") or f"App {aid}"

        owner_of: dict[str, str] = {}
        for owner, ids in (owner_map or {}).items():
            if owner == "base":
                continue
            for did in ids or ():
                clean = sanitize_id(did)
                if clean and clean != aid:
                    owner_of.setdefault(clean, str(owner))

        wanted = {d for d in (sanitize_id(x) for x in (depot_ids or ())) if d and d != aid} if depot_ids is not None else None
        wanted_keys = {d for d in (sanitize_id(x) for x in (key_ids or ())) if d} if key_ids is not None else None

        if dlc_ids is not None:
            enabled = {d for d in (sanitize_id(x) for x in dlc_ids) if d and d != aid}
        else:
            # A ticked depot owned by a DLC means that DLC is enabled, which is what
            # puts its AppID into AdditionalApps.
            enabled = {owner_of[d] for d in (wanted or ()) if owner_of.get(d)}

        result = self._project_config(
            aid,
            name,
            depot_keys,
            owner_map,
            enabled,
            candidate_depots={str(d) for d in (record.get("depots") or [])},
            selected_depots=wanted,
            selected_dlcs=enabled,
            selected_keys=wanted_keys,
        )
        if result.get("ok"):
            depots_added = result.get("depots_added", [])
            self.library.register(
                aid,
                result.get("name") or name,
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

    def refetch_game(self, app_id: str) -> dict:
        """Force-fetch fresh manifests from Hubcap, ignoring previous depot selections.

        This is the hail-mary recovery action:
          1. Force-downloads the latest bundle from Hubcap API (bypassing cache).
          2. Overwrites existing keys/tokens for this game with fresh values.
          3. Enables all DLCs that have keys or depots in Hubcap.
          4. Injects ALL Hubcap-keyed depots + root AppKey in an atomic batch.
          5. Never injects depots/keys not present in Hubcap (respects PICS/SteamCMD).
          6. Additively merges pre-existing local entries outside of Hubcap.
        """
        aid = sanitize_id(app_id)
        if not aid:
            return {"ok": False, "error": "Invalid AppID"}
        if self.ctx.sls_config() is None:
            return {"ok": False, "error": "SLSsteam config not found"}

        # 1. Fetch fresh bundle from Hubcap (forces fresh download)
        res = self.manifests.fetch(aid, persist_config=False)
        if not res.get("ok"):
            return {"ok": False, "error": res.get("error", "Hubcap fetch failed")}

        record = self.library.load().get(aid) or {}
        details = self.steam.app_details(aid)
        if not isinstance(details, dict):
            details = {}

        resolved_name = (
            res.get("game_name")
            or details.get("name")
            or record.get("name")
            or f"App {aid}"
        )

        # 2. Gather owner map
        installed_depots = (
            (self.steam.install_info(aid) or {}).get("installed_depots") or {}
        )
        owner_map = self.library.app_to_depots(
            aid,
            record=record,
            depot_dlc=details.get("depot_dlc") or {},
            installed_depots=installed_depots,
        )

        # 3. Keys: start with fresh keys from Hubcap
        depot_keys: dict[str, str] = {
            str(d): str(k) for d, k in (res.get("depot_keys") or {}).items()
        }
        # Additive merge: keep pre-existing local entries not covered by Hubcap
        for did, key in self.library.local_depot_keys(aid).items():
            depot_keys.setdefault(str(did), str(key))
        depot_keys = self._merge_existing_keys(
            aid, depot_keys, set(owner_map.get("base", ()))
        )

        # 4. Enable all DLCs found in Hubcap or Steam that have keyed depots
        dlcs = {d for d in (sanitize_id(x) for x in (res.get("dlc_appids") or [])) if d and d != aid}
        steam_dlcs = (details.get("dlc_all") or []) if self.ctx.read_setting("add_delisted_dlcs", True) else (details.get("dlc") or [])
        for d in (sanitize_id(x) for x in steam_dlcs):
            if d and d != aid and (d in owner_map or d in depot_keys):
                dlcs.add(d)

        # 5. Project config ignoring custom selections (selected_depots=None, selected_keys=None)
        # Only candidates with keys in depot_keys (or shared redists) will be mounted
        result = self._project_config(
            aid,
            resolved_name,
            depot_keys,
            owner_map,
            enabled_dlc_ids=dlcs,
            candidate_depots={str(d) for d in (record.get("depots") or [])},
            selected_depots=None,
            selected_dlcs=dlcs,
            selected_keys=None,
        )
        if result.get("ok"):
            depots_added = result.get("depots_added", [])
            self.library.register(
                aid,
                resolved_name,
                depots_added,
                depot_keys,
                installdir=record.get("installdir", ""),
                depot_names={d: self.ctx.depot_names.get(d, "") for d in depots_added},
                dlc_appids=record.get("dlc_appids", []),
                enabled_dlc_appids=sort_ids(dlcs),
            )
            signal_api("RELOAD", logger)
            result["name"] = resolved_name
            result["dlcs_added"] = sort_ids(dlcs)
        return result

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

        include_delisted = bool(self.ctx.read_setting("add_delisted_dlcs", True))

        details = self.steam.app_details(aid)
        if include_delisted:
            candidate_list = (details or {}).get("dlc_all") or (details or {}).get("dlc") or []
        else:
            candidate_list = (details or {}).get("dlc") or []

        dlcs = {d for d in (sanitize_id(x) for x in candidate_list) if d and d != aid}
        if include_delisted or not dlcs:
            res = self.manifests.fetch(aid, persist_config=False)
            if res.get("ok"):
                dlcs |= {d for d in (sanitize_id(x) for x in (res.get("dlc_appids") or [])) if d and d != aid}
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

        include_delisted = bool(self.ctx.read_setting("add_delisted_dlcs", True))
        record = self.library.load().get(aid) or {}
        details = self.steam.app_details(aid)
        if not isinstance(details, dict):
            details = {}
        source_dlcs = (details.get("dlc_all") or []) if include_delisted else (details.get("dlc") or [])
        dlcs = {d for d in (sanitize_id(x) for x in source_dlcs) if d}
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
