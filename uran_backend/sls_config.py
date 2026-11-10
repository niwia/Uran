"""Comment-preserving SLSsteam configuration editing and backup operations.

Mirrors ASSella's `utils/yaml/*` so this plugin stays hand-in-hand with it:
  * PyYAML is never used for writes — comments and key order must survive a
    round trip, and SLSsteam itself is a hand-rolled parser.
  * Writes are IN-PLACE (r+ / seek / write / truncate / fsync) rather than
    tmp+rename. A rename swaps the inode and opens a window where SLSsteam's
    inotify FileWatcher sees the file disappear.
  * Entries carry ownership comments (`# Game Name`). These are not decoration:
    ASSella parses them back to decide which depots/keys belong to which game
    when it later cleans the config up.
"""

import logging
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from .context import Context
from assella_shared.sls_yaml import (  # noqa: F401  re-exported for existing imports
    sanitize_comment,
    sanitize_id,
    sanitize_key,
    validate_yaml,
    signal_api,
    section_bounds,
    _section_insert_pos,
    upsert_in_memory,
    remove_in_memory,
    parse_list_section,
    parse_key_section,
    parse_manifest_section,
    parse_app_token_section,
    replace_section_block,
    sort_ids,
    ensure_plugins_enabled,
    ensure_smart_tickets,
    ensure_section_header,
    ensure_required_sections,
    remove_dlc_block,
    _HEX_64_RE,
    _NUMERIC_ID_RE,
    _TOP_LEVEL_KEY_RE,
)


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------
class SlsConfig:
    """Owns the SLSsteam config file: discovery, editing, writing, backups."""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.log = logging.getLogger("Uran")

    @property
    def config_path(self) -> Path | None:
        return self.ctx.sls_config()

    def readiness(self, config_path: Path | None = None) -> dict:
        """Describe whether an existing SLS config is safe to consume or edit.

        Missing configuration is not an invitation for Uran to create it: SLSsteam
        owns the file and creates its canonical template.
        """
        cfg = config_path or self.config_path
        if cfg is None:
            return {"ok": False, "status": "missing", "path": None, "error": "SLSsteam config not found"}
        try:
            if not cfg.exists():
                return {"ok": False, "status": "missing", "path": str(cfg), "error": "SLSsteam config not found"}
            if not cfg.is_file():
                return {"ok": False, "status": "invalid", "path": str(cfg), "error": "SLSsteam config is not a regular file"}
            content = cfg.read_text(encoding="utf-8")
        except UnicodeError as exc:
            return {"ok": False, "status": "invalid", "path": str(cfg), "error": f"SLSsteam config is not valid UTF-8: {exc}"}
        except OSError as exc:
            return {"ok": False, "status": "unreadable", "path": str(cfg), "error": f"Could not read SLSsteam config: {exc}"}

        if not validate_yaml(content, self.log):
            return {"ok": False, "status": "invalid", "path": str(cfg), "error": "SLSsteam config contains invalid YAML"}
        return {"ok": True, "status": "ready", "path": str(cfg), "error": ""}

    # -- backups -------------------------------------------------------------
    def backups_dir(self) -> Path:
        sls = self.config_path
        base = sls.parent if sls else self.ctx.home / ".config" / "SLSsteam"
        path = base / "backups"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create_backup(self, tag: str = "sls") -> str:
        cfg = self.config_path
        if not cfg or not cfg.exists():
            return "SLSsteam config not found"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = f"{tag}.{stamp}.yaml"
        try:
            shutil.copy2(cfg, self.backups_dir() / name)
            self.log.info("Created SLS config backup: %s", name)
            return name
        except Exception as exc:  # noqa: BLE001
            self.log.error("Failed creating backup: %s", exc)
            return f"Error: {exc}"

    def list_backups(self) -> list[dict]:
        entries = []
        for item in self.backups_dir().glob("*.yaml"):
            if item.is_file():
                stat = item.stat()
                entries.append({
                    "name": item.name,
                    "stamp": item.stem,
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                })
        entries.sort(key=lambda e: e["mtime"], reverse=True)
        return entries

    def restore_backup(self, backup_name: str) -> dict:
        cfg = self.config_path
        readiness = self.readiness(cfg)
        if not readiness["ok"]:
            return {"error": readiness["error"]}
        if Path(backup_name).name != backup_name or not backup_name.endswith(".yaml"):
            return {"error": "Invalid SLS config backup name"}
        source = self.backups_dir() / backup_name
        if not source.exists():
            return {"error": f"Backup {backup_name} not found"}
        try:
            content = source.read_text(encoding="utf-8")
            if not validate_yaml(content, self.log):
                return {"error": f"Backup {backup_name} contains invalid YAML"}
            backup_result = self.create_backup("pre_restore")
            if backup_result.startswith("Error:") or backup_result == "SLSsteam config not found":
                return {"error": f"Could not create pre-restore backup: {backup_result}"}
            if not self.write(content, notify=False):
                return {"error": "Could not restore SLS config backup"}
            if not self.readiness(cfg)["ok"] or self.read() != content:
                return {"error": "Could not verify restored SLS config"}
            signal_api("RELOAD", self.log)
            return {"success": True, "verified": True}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    # -- low-level write -----------------------------------------------------
    def write(self, content: str, notify: bool = True) -> bool:
        """Atomically write config.yaml in place, preserving the inode."""
        cfg = self.config_path
        readiness = self.readiness(cfg)
        if not readiness["ok"]:
            self.log.error(
                "Refusing to write %s: %s",
                cfg,
                readiness["error"],
            )
            return False
        if not validate_yaml(content, self.log):
            return False
        with self.ctx.sls_lock:
            try:
                with open(cfg, "r+", encoding="utf-8") as handle:
                    handle.seek(0)
                    handle.write(content)
                    handle.truncate()
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.chmod(cfg, 0o600)
                except OSError:
                    pass
            except Exception as exc:  # noqa: BLE001
                self.log.error("Failed writing %s: %s", cfg, exc)
                return False
        if notify:
            signal_api("RELOAD", self.log)
        return True

    # -- read helpers --------------------------------------------------------
    def read(self) -> str:
        cfg = self.config_path
        if not cfg or not cfg.exists():
            return ""
        return cfg.read_text(encoding="utf-8", errors="replace")

    def edit(self, config_path: Path | None = None):
        return _SlsConfigEditor(self, config_path)


# ---------------------------------------------------------------------------
# Section helpers (pure functions over the config text)
# ---------------------------------------------------------------------------


class _SlsConfigEditor:
    """One read -> many in-memory edits -> one validated in-place write.

    Mirrors ASSella's `batch_config_edit` context manager. Batching matters:
    per-entry writes mean a config reread+rewrite per entry, a backup per
    entry, and a reload notification per entry — SLSsteam would reload the
    whole library dozens of times for a single game.
    """

    def __init__(self, sls: SlsConfig, config_path: Path | None = None):
        self.sls = sls
        self.config_path = config_path
        self.content = ""
        self.has_changes = False
        self.committed_successfully = True

    def __enter__(self) -> "_SlsConfigEditor":
        cfg = self.config_path or self.sls.config_path
        readiness = self.sls.readiness(cfg)
        if not readiness["ok"]:
            self.content = ""
            self.has_changes = False
            self.committed_successfully = False
            return self
        self.content = cfg.read_text(encoding="utf-8")
        self.has_changes = False
        self.committed_successfully = True
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.committed_successfully = False
            return False
        if self.has_changes:
            self.committed_successfully = self.sls.write(self.content)
            if not self.committed_successfully:
                return False
        return True

    def apply(self, content: str, changed: bool) -> bool:
        if changed:
            self.content = content
            self.has_changes = True
        return changed

    def add_app(self, app_id: str, comment: str = "") -> bool:
        return self.apply(*upsert_in_memory(self.content, "AdditionalApps", app_id, comment=comment))

    def remove_app(self, app_id: str) -> bool:
        return self.apply(*remove_in_memory(self.content, "AdditionalApps", app_id, is_list=True))

    def add_depot(self, depot_id: str, comment: str = "") -> bool:
        return self.apply(*upsert_in_memory(self.content, "AdditionalDepots", depot_id, comment=comment))

    def remove_depot(self, depot_id: str) -> bool:
        return self.apply(*remove_in_memory(self.content, "AdditionalDepots", depot_id, is_list=True))

    def add_key(self, depot_id: str, key: str, comment: str = "") -> bool:
        clean = sanitize_key(key)
        if not clean:
            self.sls.log.warning("Refusing to write invalid AES key for depot %s", depot_id)
            return False
        return self.apply(*upsert_in_memory(self.content, "DecryptionKeys", depot_id, value=clean, comment=comment))

    def remove_key(self, depot_id: str) -> bool:
        return self.apply(*remove_in_memory(self.content, "DecryptionKeys", depot_id, is_list=False))

    def add_manifest_id(self, depot_id: str, manifest_id: str) -> bool:
        mid = str(manifest_id).strip()
        if not mid or not _NUMERIC_ID_RE.match(mid):
            return False
        return self.apply(*upsert_in_memory(self.content, "ManifestIds", depot_id, value=mid))

    def add_fake_app_id(self, app_id: str, target_id: str, comment: str = "") -> bool:
        return self.apply(*upsert_in_memory(self.content, "FakeAppIds", app_id, value=str(target_id), comment=comment))

    def remove_fake_app_id(self, app_id: str) -> bool:
        return self.apply(*remove_in_memory(self.content, "FakeAppIds", app_id, is_list=False))

    def add_app_token(self, app_id: str, token: str, comment: str = "") -> bool:
        clean = sanitize_id(app_id)
        if not clean or not token:
            return False
        return self.apply(*upsert_in_memory(self.content, "AppTokens", clean, value=token.strip(), comment=comment))

    def remove_app_token(self, app_id: str) -> bool:
        return self.apply(*remove_in_memory(self.content, "AppTokens", app_id, is_list=False))

    def remove_launch_option(self, app_id: str) -> bool:
        return self.apply(*remove_in_memory(self.content, "LaunchOptions", app_id, is_list=False))

    def remove_dlc(self, app_id: str) -> bool:
        changed = remove_dlc_block(self.content, app_id)
        if changed is None:
            return False
        return self.apply(changed, True)
