"""ACCELA plugin_library.json — the AT0-M game registry.

ASSella's AT0-M mode registers every native-Steam game here. If we inject into
config.yaml without writing this record, ASSella does not see the game as
AT0-M managed: it will not offer AT0-M updates, and its cleanup cannot tell
which depots belong to the game. So we write the same file, in the same
location, with the same schema.
"""

import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path

from .context import Context
from .paths import SHARED_REDISTS
from .sls_config import (
    SlsConfig,
    _HEX_64_RE,
    parse_key_section,
    parse_list_section,
    remove_in_memory,
    sanitize_comment,
    sanitize_id,
    section_bounds,
    signal_api,
)

logger = logging.getLogger("Uran")

PLUGIN_LIBRARY_FILENAME = "plugin_library.json"


class PluginLibrary:
    """Reads/writes ACCELA's plugin_library.json and the local depot key cache."""

    def __init__(self, ctx: Context, sls: SlsConfig):
        self.ctx = ctx
        self.sls = sls

    # -- file access ---------------------------------------------------------
    def path(self) -> Path:
        """Path to plugin_library.json (db/ dir, with legacy fallback)."""
        base = self.ctx.accela_base()
        target = base / "db" / PLUGIN_LIBRARY_FILENAME
        if target.exists():
            return target
        legacy = base / PLUGIN_LIBRARY_FILENAME
        if legacy.exists():
            return legacy
        return target

    def load(self) -> dict:
        """Load the plugin library. Returns {} when missing or corrupt."""
        path = self.path()
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed reading %s: %s", path, exc)
            return {}

    def save(self, data: dict) -> bool:
        """Persist atomically (tmp + replace, sorted keys).

        Matches ASSella's save_plugin_library so the file stays byte-compatible
        with what ASSella writes and reads.
        """
        path = self.path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed saving %s: %s", path, exc)
            return False

    # -- registration --------------------------------------------------------
    def register(
        self,
        appid: str,
        name: str,
        depot_ids: list,
        decryption_keys: dict,
        installdir: str = "",
        depot_names: dict | None = None,
        dlc_appids: list | None = None,
        enabled_dlc_appids: list | None = None,
    ) -> bool:
        """Register a game in the AT0-M library.

        Schema is taken verbatim from ASSella's register_plugin_game so ASSella
        treats games injected here identically to games it injected itself.
        ``enabled_dlc_appids`` records the DLC layers a base-game install has
        switched on (distinct from ``dlc_appids``, ASSella's DLC-only mode); a
        later uninstall removes both sets.
        """
        appid_str = str(appid).strip()
        if not appid_str.isdigit() or appid_str in ("0", "N/A", "unknown"):
            logger.warning("Invalid AppID '%s' for plugin registration", appid)
            return False

        clean_dlc = [str(d).strip() for d in (dlc_appids or []) if str(d).strip().isdigit()]
        clean_enabled = sorted({
            str(d).strip() for d in (enabled_dlc_appids or []) if str(d).strip().isdigit()
        })
        clean_depots = [
            str(d).strip() for d in (depot_ids or [])
            if str(d).strip().isdigit()
            and str(d).strip() != appid_str
            and str(d).strip() not in clean_dlc
            and str(d).strip() not in clean_enabled
        ]

        clean_keys = {
            str(did).strip(): str(key).strip()
            for did, key in (decryption_keys or {}).items()
            if str(did).strip().isdigit() and _HEX_64_RE.match(str(key).strip())
        }

        # Only depots that have a key (or are shared redists) are safe to
        # register; otherwise Steam fails the download with DepotWithoutKey.
        valid = set(clean_keys) | SHARED_REDISTS
        excluded = [d for d in clean_depots if d not in valid]
        if excluded:
            logger.warning(
                "Excluded %d unkeyed depot(s) for %s: %s", len(excluded), appid_str, excluded
            )
            clean_depots = [d for d in clean_depots if d in valid]

        clean_names = {
            str(did).strip(): str(dname).strip()
            for did, dname in (depot_names or {}).items()
            if str(did).strip().isdigit() and dname and str(did).strip() != appid_str
        }

        lib = self.load()
        lib[appid_str] = {
            "appid": appid_str,
            "name": name,
            "installdir": installdir,
            "depots": clean_depots,
            "keys": clean_keys,
            "depot_names": clean_names,
            "dlc_only": bool(clean_dlc),
            "dlc_appids": clean_dlc,
            "enabled_dlc_appids": clean_enabled,
            "updated_at": int(time.time()),
            "source": "plugin_native",
        }
        return self.save(lib)

    def get(self, appid: str) -> dict | None:
        """Return an AT0-M library record for this appid, if registered."""
        return self.load().get(str(appid).strip())

    @staticmethod
    def _owned_comment(comment: str, appid: str, game_name: str) -> bool:
        """True when an ownership comment belongs to this game.

        Matches the paren-guarded AppID Uran writes (``(620)``), the legacy
        ``uran:dlc:620`` marker, or a whole-word game-name prefix (ASSella writes
        ``"{name} - {depot} ({did})"``). A bare substring is never used: AppIDs
        share a numeric namespace, so ``620`` must not match another game's
        ``(6207)``, and unregistering ``Portal`` must not claim every
        ``Portal 2 …`` line.
        """
        c = (comment or "").strip()
        if not c:
            return False
        if f"({appid})" in c or f"uran:dlc:{appid}" in c:
            return True
        g = (game_name or "").strip()
        return bool(g) and len(g) > 3 and (
            c == g or c.startswith(g + " -") or c.startswith(g + " [")
        )

    def unregister(self, appid: str, keep_in_additional_apps: bool = False) -> bool:
        """Remove a game from the AT0-M library and clean every config trace.

        Mirrors ASSella's unregister_plugin_game: removes the AppID and its DLC
        AppIDs from AdditionalApps, drops FakeAppIds / LaunchOptions / DlcData,
        strips the secondary sections, and removes depots + keys that no other
        game still needs. Shared redistributables are never removed.

        All edits land in ONE batched write so SLSsteam never observes a
        half-purged config.
        """
        appid_str = str(appid).strip()
        lib = self.load()
        record = lib.get(appid_str)
        if record is None:
            return False

        dlc_appids = {str(d) for d in (record.get("dlc_appids") or [])}
        dlc_appids |= {str(d) for d in (record.get("enabled_dlc_appids") or [])}
        target_depots = {str(d) for d in (record.get("depots") or [])}
        target_keys = {str(d) for d in (record.get("keys") or {})}
        target_keys.add(appid_str)  # the root AppKey lives under the AppID

        # Ownership comment scan: pick up entries ASSella attributed to this game.
        cfg = self.ctx.sls_config()
        if cfg and cfg.exists():
            try:
                content = cfg.read_text(encoding="utf-8", errors="replace")
                gname = sanitize_comment(record.get("name") or "")
                for section in ("AdditionalDepots", "DecryptionKeys"):
                    bounds = section_bounds(content, section)
                    if not bounds:
                        continue
                    for line in content[bounds[1]:bounds[2]].splitlines():
                        match = re.match(
                            r"^[ \t]*-[ \t]*['\"]?(\d+)['\"]?[ \t]*(?:#[ \t]*(.*))?$", line
                        ) or re.match(
                            r"^[ \t]*['\"]?(\d+)['\"]?[ \t]*:[ \t]*[^#\r\n]*#[ \t]*(.*)$", line
                        )
                        if not match:
                            continue
                        item_id, comment = match.group(1), match.group(2) or ""
                        if item_id in SHARED_REDISTS:
                            continue
                        if self._owned_comment(comment, appid_str, gname):
                            (target_depots if section == "AdditionalDepots" else target_keys).add(item_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("ownership scan failed for %s: %s", appid_str, exc)

        # Depots/keys still referenced by the OTHER registered games.
        remaining_depots: set[str] = set()
        remaining_keys: set[str] = set()
        for other_id, other in lib.items():
            if other_id == appid_str:
                continue
            remaining_depots |= {str(d) for d in (other.get("depots") or [])}
            remaining_keys |= {str(d) for d in (other.get("keys") or {})}

        secondary_sections = (
            "GameTitles", "ManifestIds", "DepotBlacklist", "CDKeys",
            "FakeOffline", "SubscriptionTimestamps", "DenuvoGames",
        )

        with self.sls.edit() as editor:
            if keep_in_additional_apps:
                # AT0-M -> ACCELA conversion: keep the AppID, drop DLCs we own.
                editor.add_app(appid_str, comment=sanitize_comment(record.get("name") or ""))
                for dlc_id in dlc_appids:
                    editor.remove_app(dlc_id)
                    editor.remove_fake_app_id(dlc_id)
                    editor.remove_launch_option(dlc_id)
            else:
                for dlc_id in dlc_appids:
                    editor.remove_app(dlc_id)
                    editor.remove_fake_app_id(dlc_id)
                    editor.remove_launch_option(dlc_id)
                if not record.get("dlc_only"):
                    editor.remove_app(appid_str)

                editor.remove_fake_app_id(appid_str)
                editor.remove_launch_option(appid_str)
                editor.remove_dlc(appid_str)

            # Secondary sections for the app, its DLCs and its depots.
            ids = [appid_str] + sorted(dlc_appids) + sorted(target_depots)
            for section in secondary_sections:
                for item in ids:
                    editor.apply(*remove_in_memory(editor.content, section, item, is_list=None))

            for did in sorted(target_depots):
                if did in SHARED_REDISTS or did in remaining_depots:
                    continue
                editor.remove_depot(did)
            for did in sorted(target_keys):
                if did in SHARED_REDISTS or did in remaining_keys:
                    continue
                editor.remove_key(did)

        if not editor.committed_successfully:
            logger.error("Failed to clean SLSsteam config while unregistering %s", appid_str)
            return False

        lib.pop(appid_str, None)
        if not self.save(lib):
            return False
        signal_api("RELOAD", logger)
        return True

    # -- local depot key cache -------------------------------------------------
    def _db_candidates(self, db_name: str) -> list[Path]:
        """Prioritized candidate paths for an ACCELA SQLite database."""
        base = self.ctx.accela_base()
        candidates = [
            base / "db" / db_name,
            base / db_name,
            self.ctx.home / ".local/share/ACCELA/db" / db_name,
            self.ctx.home / ".local/share/ACCELA" / db_name,
            self.ctx.home / ".var/app/com.valvesoftware.Steam/data/ACCELA/db" / db_name,
            self.ctx.home / ".var/app/com.valvesoftware.Steam/.local/share/ACCELA/db" / db_name,
            Path("/home/deck/.local/share/ACCELA/db") / db_name,
        ]
        seen: set[str] = set()
        deduped: list[Path] = []
        for candidate in candidates:
            key = str(candidate.resolve()) if candidate.exists() else str(candidate)
            if key not in seen:
                seen.add(key)
                deduped.append(candidate)
        return deduped

    def _steam_headers_db(self) -> Path | None:
        """First existing ACCELA steam_headers.db, or None when absent."""
        for db_path in self._db_candidates("steam_headers.db"):
            if db_path.exists():
                return db_path
        return None

    def _accela_dirs(self) -> list[Path]:
        """Likely ACCELA data roots, most specific first (deduped)."""
        base = self.ctx.accela_base()
        candidates = [
            base,
            self.ctx.home / ".local/share/ACCELA",
            self.ctx.home / ".var/app/com.valvesoftware.Steam/data/ACCELA",
            self.ctx.home / ".var/app/com.valvesoftware.Steam/.local/share/ACCELA",
            Path("/home/deck/.local/share/ACCELA"),
        ]
        seen: set[str] = set()
        out: list[Path] = []
        for candidate in candidates:
            key = str(candidate.resolve()) if candidate.exists() else str(candidate)
            if key not in seen:
                seen.add(key)
                out.append(candidate)
        return out

    def cached_lua_depots(self, app_id: str) -> dict[str, str] | None:
        """Depot -> owning AppID from ASSella's cached_luas/<appid>.lua.

        Hubcap's generated Lua groups depots by owner: a "-- MAIN APPLICATION"
        marker returns ownership to the base game, each "-- <name> (AppID: N)"
        header claims the ``addappid()`` lines beneath it, and the shared /
        empty / excluded / unreleased sections claim nothing. Plain text, so it
        needs no dependency at all, and it works for any game ASSella has
        cached — even one whose DB row is not DLC-expanded.
        """
        aid = sanitize_id(app_id)
        if not aid:
            return None
        for base in self._accela_dirs():
            path = base / "cached_luas" / f"{aid}.lua"
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                return None
            owner: str | None = None
            out: dict[str, str] = {}
            for raw in text.splitlines():
                line = raw.strip()
                if not line:
                    continue
                header = re.search(r"\(AppID:\s*(\d+)\)", line, re.IGNORECASE)
                if header:
                    owner = "" if header.group(1) == aid else header.group(1)
                    continue
                if line.startswith("-- MAIN APP") or line.startswith("-- MAIN GAME"):
                    owner = ""
                    continue
                if (
                    line.startswith("-- SHARED")
                    or line.startswith("-- DLCS WITHOUT")
                    or line.startswith("-- EXCLUDED")
                    or line.startswith("-- DLCS EXCLUDED")
                    or line.startswith("-- EMPTY")
                    or line.startswith("-- UNRELEASED")
                ):
                    owner = None
                    continue
                if owner is None:
                    continue
                entry = re.match(r"addappid\((\d+)", line)
                if entry and entry.group(1) != aid:
                    out.setdefault(entry.group(1), owner)
            return out or None
        return None

    def steam_app_depots(self, app_id: str, require_expanded: bool = True) -> dict | None:
        """ASSella's cached depot map for an AppID, as a local metadata tier.

        ``apps.depots_json`` is a zstandard-compressed JSON blob of
        ``{depot_id: {name, oslist, osarch, language, size, dlcappid, is_dlc}}``
        plus the DLC AppID list under ``listofdlc`` — the same attribution the
        SteamCMD API exposes, so it can seed Uran's metadata cache with no
        network call.

        Only rows ASSella has actually DLC-expanded (``dlcs_expanded``) are
        returned by default: for those the ``dlcappid`` map is authoritative. An
        unexpanded row has an empty ``dlcappid`` that would make Uran misread
        DLC depots as base-game content, so it is treated as "no local data"
        and the caller falls back to the network. Pass ``require_expanded=False``
        for the narrower use of reading one DLC's own depot row during mapping.

        Returns ``None`` when there is no usable row (no ASSella DB, no
        ``zstandard`` installed, or an undecodable blob). Read-only: Uran never
        writes ASSella's database.
        """
        aid = sanitize_id(app_id)
        if not aid:
            return None
        try:
            import zstandard  # type: ignore  # optional; Uran stays dependency-free
        except ImportError:
            return None
        db_path = self._steam_headers_db()
        if db_path is None or not self._has_table(db_path, "apps"):
            return None
        try:
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT name, depots_json, last_updated FROM apps WHERE appid = ?",
                    (aid,),
                ).fetchone()
        except sqlite3.Error as exc:
            logger.debug("apps row read failed for %s: %s", aid, exc)
            return None
        if row is None or not row[1]:
            return None
        try:
            parsed = json.loads(
                zstandard.ZstdDecompressor().decompress(bytes(row[1])).decode("utf-8")
            )
        except Exception as exc:  # noqa: BLE001 — any blob problem means "no local data"
            logger.debug("depots_json decode failed for %s: %s", aid, exc)
            return None
        if not isinstance(parsed, dict):
            return None
        if require_expanded and not parsed.get("dlcs_expanded"):
            return None
        depots = {
            str(did): info
            for did, info in parsed.items()
            if str(did).isdigit() and isinstance(info, dict)
        }
        if not depots:
            return None
        dlc = sorted(
            {
                part.strip()
                for part in str(parsed.get("listofdlc") or "").split(",")
                if part.strip().isdigit()
            }
        )
        return {
            "at": float(row[2] or 0),
            "name": str(row[0] or ""),
            "depots": depots,
            "dlc": dlc,
        }

    def local_depot_keys(self, app_id: str, candidate_depots: set | None = None) -> dict[str, str]:
        """Cached depot keys from the local depot_keys.db for an AppID."""
        aid = sanitize_id(app_id)
        if not aid:
            return {}
        keys: dict[str, str] = {}
        for db_path in self._db_candidates("depot_keys.db"):
            if not db_path.exists():
                continue
            try:
                with sqlite3.connect(db_path) as conn:
                    cursor = conn.cursor()
                    rows = cursor.execute(
                        "SELECT depot_id, aes_key FROM depot_keys WHERE appid = ? OR depot_id = ?",
                        (aid, aid),
                    ).fetchall()
                    for did, key in rows:
                        if did and key:
                            keys[str(did)] = str(key).strip()
                    for did in candidate_depots or ():
                        clean = sanitize_id(did)
                        if clean and clean not in keys:
                            row = cursor.execute(
                                "SELECT aes_key FROM depot_keys WHERE depot_id = ? LIMIT 1",
                                (clean,),
                            ).fetchone()
                            if row and row[0]:
                                keys[clean] = str(row[0]).strip()
                if keys:
                    break
            except Exception as exc:  # noqa: BLE001
                logger.debug("depot_keys.db query on %s failed: %s", db_path, exc)
        return keys

    def save_local_depot_keys(self, app_id: str, keys: dict[str, str]) -> None:
        """Cache newly harvested depot keys into the local depot_keys.db."""
        aid = sanitize_id(app_id)
        if not aid or not keys:
            return
        for db_path in self._db_candidates("depot_keys.db"):
            if not db_path.exists():
                continue
            try:
                now = int(time.time())
                with sqlite3.connect(db_path) as conn:
                    cursor = conn.cursor()
                    for did, key in keys.items():
                        clean_depot = sanitize_id(did)
                        clean_key = str(key).strip()
                        if clean_depot and clean_key:
                            cursor.execute(
                                "INSERT OR REPLACE INTO depot_keys (appid, depot_id, aes_key, updated_at) VALUES (?, ?, ?, ?)",
                                (aid, clean_depot, clean_key, now),
                            )
                    conn.commit()
                break
            except Exception as exc:  # noqa: BLE001
                logger.debug("Failed saving keys to %s: %s", db_path, exc)

    def depot_enrichments(self, app_id: str) -> dict[str, dict]:
        """Depot name / DLC / oslist / osarch / size rows for an AppID.

        Tolerates an older enrichment table that lacks the osarch / size
        columns — a missing column blanks those fields rather than dropping
        every row for the AppID.
        """
        db_path = self._steam_headers_db()
        out: dict[str, dict] = {}
        if db_path is None:
            return out
        full_cols = "depot_id, name, is_dlc, oslist, osarch, size_str, size_bytes"
        base_cols = "depot_id, name, is_dlc, oslist"
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                try:
                    rows = cursor.execute(
                        f"SELECT {full_cols} FROM depot_enrichments WHERE appid = ?",
                        (app_id,),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = cursor.execute(
                        f"SELECT {base_cols} FROM depot_enrichments WHERE appid = ?",
                        (app_id,),
                    ).fetchall()
                for row in rows:
                    out[str(row[0])] = {
                        "name": str(row[1] or ""),
                        "is_dlc": bool(row[2]),
                        "oslist": str(row[3] or ""),
                        "osarch": str(row[4] or "") if len(row) > 4 else "",
                        "size_str": str(row[5] or "") if len(row) > 5 else "",
                        "size_bytes": (row[6] or 0) if len(row) > 6 else 0,
                    }
        except Exception as exc:  # noqa: BLE001
            logger.debug("depot_enrichments error: %s", exc)
        return out

    def dlc_depot_ids(self, app_id: str, extra_depot: str = "") -> set[str]:
        """Depots classified as DLC for an AppID."""
        db_path = self._steam_headers_db()
        if db_path is None:
            return set()
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.cursor().execute(
                    "SELECT depot_id FROM depot_enrichments WHERE appid = ? AND (is_dlc = 1 OR name LIKE '%[DLC%')",
                    (app_id,),
                ).fetchall()
                ids = {str(row[0]) for row in rows}
            if extra_depot:
                ids.add(str(extra_depot))
            return ids
        except Exception as exc:  # noqa: BLE001
            logger.debug("DLC depot lookup failed for %s: %s", app_id, exc)
            return set()

    def app_to_depots(
        self,
        app_id: str,
        record: dict | None = None,
        depot_dlc: dict | None = None,
        installed_depots: dict | None = None,
    ) -> dict[str, set[str]]:
        """Attribute every depot this machine knows for a game to its owner.

        Returns ``{owner: {depot_ids}}`` where ``owner`` is ``"base"`` for the
        base game or a DLC AppID. This is what lets the UI toggle whole apps
        instead of individual depots: turning a DLC off removes exactly the
        depots that DLC owns.

        Mirrors ASSella's multi-source mapping so attribution still works with
        no network — an installed game, an existing ASSella cache, and Uran's
        own records all feed it. Sources, in priority order (first claim wins):
          1. A per-depot ``dlcappid`` from SteamCMD / ASSella's ``depots_json``
             (passed as ``depot_dlc``) — authoritative.
          2. ``InstalledDepots`` from this game's appmanifest (``installed_depots``).
          3. ASSella's cached Lua ``(AppID: N)`` sections.
          4. Each known DLC's own depot row in ASSella's DB.
          5. A DLC whose AppID doubles as its depot ID.
          6. ``[DLC NNN]`` in an enrichment name.
        Anything unattributable is treated as base-game content: mounting a
        surplus keyed depot is harmless, hiding a needed one is not.
        """
        aid = sanitize_id(app_id)
        if not aid:
            return {}
        if record is None:
            record = self.load().get(aid) or {}
        enrich = self.depot_enrichments(aid)
        lua = self.cached_lua_depots(aid) or {}

        def owner_id(value) -> str:
            clean = sanitize_id(value)
            return clean if clean and clean != aid else ""

        dlc_ids: set[str] = {str(d) for d in (record.get("dlc_appids") or [])}
        dlc_ids |= {str(d) for d in (record.get("enabled_dlc_appids") or [])}
        dlc_ids |= {d for d, info in enrich.items() if info.get("is_dlc")}
        dlc_ids |= {
            owner_id(info.get("dlcappid"))
            for info in (installed_depots or {}).values()
            if isinstance(info, dict)
        }
        dlc_ids |= {owner_id(v) for v in lua.values()}
        dlc_ids |= {owner_id(v) for v in (depot_dlc or {}).values()}
        dlc_ids.discard(aid)
        dlc_ids.discard("")

        owners: dict[str, set[str]] = {"base": set()}
        placed: set[str] = set()

        def place(owner: str, did) -> None:
            clean = sanitize_id(did)
            if not clean or clean == aid or clean in SHARED_REDISTS or clean in placed:
                return
            placed.add(clean)
            owners.setdefault(str(owner), set()).add(clean)

        # 1. Authoritative: per-depot dlcappid (SteamCMD / ASSella depots_json).
        for did, dlc in (depot_dlc or {}).items():
            place(owner_id(dlc) or "base", did)

        # 2. This machine's appmanifest InstalledDepots. Only a real dlcappid is
        #    an attribution here: a depot with none is left to the more specific
        #    tiers below (Lua grouping, "[DLC NNN]" name) and the base fallback,
        #    so an installed depot cannot preempt them by claiming base first.
        for did, info in (installed_depots or {}).items():
            dlc = owner_id(info.get("dlcappid")) if isinstance(info, dict) else ""
            if dlc:
                place(dlc, did)

        # 3. ASSella's cached Lua grouping.
        for did, dlc in lua.items():
            place(owner_id(dlc) or "base", did)

        # 4. Each known DLC's own depot row in ASSella's DB.
        for dlc in sorted(dlc_ids):
            row = self.steam_app_depots(dlc, require_expanded=False)
            for did in (row or {}).get("depots") or {}:
                place(dlc, did)

        # 5. A DLC-owner depot is sometimes stored under the DLC's own AppID.
        for dlc in dlc_ids:
            place(dlc, dlc)

        # 6. ASSella tags DLC depots in the enrichment name as "[DLC NNN]".
        for did, info in enrich.items():
            match = re.search(r"\[DLC\s*(\d+)\]", info.get("name") or "", re.IGNORECASE)
            place(match.group(1) if match else "base", did)

        # Everything else we know about is base-game content.
        known = {str(d) for d in (record.get("depots") or [])}
        known |= {str(k) for k in (record.get("keys") or {}).keys()}
        known |= set(enrich)
        known |= {str(d) for d in (depot_dlc or {})}
        known |= {str(d) for d in (installed_depots or {})}
        known |= set(lua)
        known |= {str(d) for d in self.local_depot_keys(aid)}
        for did in known:
            place("base", did)

        return {owner: ids for owner, ids in owners.items() if ids}

    # -- ASSella's update-check cache ----------------------------------------
    #
    # ASSella already computes and persists this exact answer in
    # `at0m_update_status`. Reading it means a check Uran has already paid for
    # costs zero network calls, and both tools agree by construction.
    #
    # Read-only: Uran never writes here, so the two tools can never disagree in
    # a way that corrupts ASSella's state.
    UP_TO_DATE_TTL = 24 * 3600
    KEY_PENDING_COOLDOWN = 6 * 3600

    def _has_table(self, db_path: Path | None, table: str) -> bool:
        if db_path is None or not db_path.exists():
            return False
        try:
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
            return row is not None
        except sqlite3.Error:
            return False

    def cached_update_status(self, app_id: str) -> dict | None:
        """ASSella's last recorded status for this appid, if still trustworthy.

        Returns None when the row is absent, malformed, or past the point where
        its answer is still meaningful. Mirrors At0mUpdateChecker's tier-1
        rules: a key_pending row inside its cooldown is authoritative, and an
        up_to_date row is only trusted for UP_TO_DATE_TTL.
        """
        aid = str(app_id).strip()
        if not aid.isdigit():
            return None

        db_path = self._steam_headers_db()
        if not self._has_table(db_path, "at0m_update_status"):
            return None

        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT appid, game_title, last_timeupdated, last_checked, "
                    "status, new_depots, cooldown_until "
                    "FROM at0m_update_status WHERE appid = ?",
                    (aid,),
                ).fetchone()
        except sqlite3.Error as exc:
            logger.debug("at0m_update_status read failed: %s", exc)
            return None

        if row is None:
            return None

        try:
            new_depots = json.loads(row["new_depots"] or "[]")
        except Exception:  # noqa: BLE001 - a bad cell must not break the check
            new_depots = []
        if not isinstance(new_depots, list):
            new_depots = []

        now = int(time.time())
        status = (row["status"] or "").strip()
        cooldown_until = int(row["cooldown_until"] or 0)
        last_checked = int(row["last_checked"] or 0)

        # A pending key is still pending until the cooldown expires; re-asking
        # Hubcap before then is exactly the traffic the cooldown exists to stop.
        if status == "key_pending" and now < cooldown_until:
            return {
                "appid": aid,
                "game_title": row["game_title"] or "",
                "status": status,
                "new_depots": new_depots,
                "last_checked": last_checked,
                "cooldown_until": cooldown_until,
                "from": "assella_cache",
            }

        if status == "up_to_date" and last_checked and (now - last_checked) < self.UP_TO_DATE_TTL:
            return {
                "appid": aid,
                "game_title": row["game_title"] or "",
                "status": status,
                "new_depots": new_depots,
                "last_checked": last_checked,
                "from": "assella_cache",
            }

        # update_available is never cached: it is an actionable state and the
        # user should be told the moment it is computed.
        return None

    def pending_hubcap_depots(self, app_id: str) -> list[dict]:
        """ASSella's record of depots Hubcap could not supply yet."""
        aid = str(app_id).strip()
        if not aid.isdigit():
            return []

        db_path = self._steam_headers_db()
        if not self._has_table(db_path, "missing_hubcap_depots"):
            return []

        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT depot_id, manifest_id, depot_name FROM missing_hubcap_depots "
                    "WHERE appid = ?",
                    (aid,),
                ).fetchall()
        except sqlite3.Error as exc:
            logger.debug("missing_hubcap_depots read failed: %s", exc)
            return []

        return [
            {
                "id": str(r["depot_id"]),
                "name": r["depot_name"] or f"Depot {r['depot_id']}",
                "manifest_id": r["manifest_id"] or "",
            }
            for r in rows
        ]

    def known_depots_for(self, app_id: str, record: dict) -> set[str]:
        """Every depot ID this machine already knows about for an appid.

        Mirrors At0mUpdateChecker.get_locally_known_depots: the registry record,
        config.yaml (DecryptionKeys and AdditionalDepots both count) and the
        local key cache. Reading config.yaml matters because ASSella writes
        there too, so a game it registered can be absent from the record.
        """
        aid = str(app_id).strip()
        known = {str(d) for d in (record.get("depots") or [])}
        known |= {str(k) for k in (record.get("keys") or {}).keys()}

        cfg = self.ctx.sls_config()
        if cfg and cfg.exists():
            try:
                content = cfg.read_text(encoding="utf-8", errors="replace")
                keys, _ = parse_key_section(content, "DecryptionKeys")
                depots = parse_list_section(content, "AdditionalDepots")
                known |= {str(k) for k in keys.keys()}
                known |= {str(d) for d in depots.keys()}
            except Exception as exc:  # noqa: BLE001
                logger.debug("config depot scan failed for %s: %s", aid, exc)

        known |= {str(d) for d in self.local_depot_keys(aid).keys()}

        # Shared redistributables belong to every game and are never a delta.
        known.difference_update(SHARED_REDISTS)
        return known

    def depot_name(self, depot_id: str) -> str:
        """Best available human name for a depot.

        Prefers the cache filled during a manifest parse, then ASSella's
        enrichment table, then the ID itself.
        """
        did = str(depot_id)
        cached = self.ctx.depot_names.get(did)
        if cached:
            return cached
        return self.enrichment_name(did) or f"Depot {did}"

    def enrichment_name(self, depot_id: str) -> str:
        """Depot name from ASSella's enrichment table, if it has one."""
        db_path = self._steam_headers_db()
        if not self._has_table(db_path, "depot_enrichments"):
            return ""
        try:
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT name FROM depot_enrichments WHERE depot_id = ?",
                    (str(depot_id),),
                ).fetchone()
            return str(row[0]) if row and row[0] else ""
        except sqlite3.Error as exc:
            logger.debug("depot_enrichments name lookup failed for %s: %s", depot_id, exc)
            return ""