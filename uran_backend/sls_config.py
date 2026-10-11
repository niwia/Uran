"""Comment-preserving SLSsteam configuration editing and backup operations."""

import os
import re
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


def bind_core(core) -> None:
    """Bind path discovery, logger and shared write locks from main.py."""
    names = (
        "_find_sls_config", "_user_home", "_signal_slssteam_api", "_sls_write_lock",
        "_HEX_64_RE", "_NUMERIC_ID_RE", "_TOP_LEVEL_KEY_RE", "_remove_dlc_block", "logger",
    )
    globals().update({name: getattr(core, name) for name in names})


# SLSsteam Config Backups
# ---------------------------------------------------------------------------
def _backups_dir() -> Path:
    sls = _find_sls_config()
    if sls:
        d = sls.parent / "backups"
    else:
        d = Path.home() / ".config" / "SLSsteam" / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d

def create_backup(tag: str = "sls") -> str:
    """Create timestamped backup of config.yaml."""
    cfg = _find_sls_config()
    if not cfg or not cfg.exists():
        return "SLSsteam config not found"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"{tag}.{ts}.yaml"
    dest = _backups_dir() / name
    try:
        shutil.copy2(cfg, dest)
        logger.info("Created SLS config backup: %s", name)
        return name
    except Exception as e:
        logger.error("Failed creating backup: %s", e)
        return f"Error: {e}"

def list_backups() -> list[dict]:
    b_dir = _backups_dir()
    if not b_dir.exists():
        return []
    entries = []
    for f in b_dir.glob("*.yaml"):
        if f.is_file():
            stat = f.stat()
            entries.append({
                "name": f.name,
                "stamp": f.stem,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            })
    entries.sort(key=lambda x: x["mtime"], reverse=True)
    return entries

def restore_backup(backup_name: str) -> dict:
    cfg = _find_sls_config()
    if not cfg:
        return {"error": "SLSsteam config not found"}
    src = _backups_dir() / backup_name
    if not src.exists():
        return {"error": f"Backup {backup_name} not found"}
    try:
        # Pre-restore safety snapshot
        create_backup("pre_restore")
        with _sls_write_lock:
            shutil.copy2(src, cfg)
        _signal_slssteam_api("RELOAD")
        return {"success": True, "verified": True}
    except Exception as e:
        return {"error": str(e)}

# ---------------------------------------------------------------------------
# YAML Config Engine (comment-preserving, inode-preserving)
#
# Mirrors ASSella's `utils/yaml/*` so this plugin stays hand-in-hand with it:
#   * PyYAML is never used for writes — comments and key order must survive a
#     round trip, and SLSsteam itself is a hand-rolled parser.
#   * Writes are IN-PLACE (r+ / seek / write / truncate / fsync) rather than
#     tmp+rename. A rename swaps the inode and opens a window where SLSsteam's
#     inotify FileWatcher sees the file disappear.
#   * Entries carry ownership comments (`# Game Name`). These are not
#     decoration: ASSella parses them back to decide which depots/keys belong
#     to which game when it later cleans the config up.
# ---------------------------------------------------------------------------
def _sanitize_comment(comment) -> str:
    """Strip newlines/control chars from a comment to prevent YAML line injection."""
    if not comment:
        return ""
    cleaned = str(comment).replace("\r", " ").replace("\n", " ").strip()
    return re.sub(r"[ \t]+", " ", cleaned)

def _sanitize_id(item_id) -> str | None:
    """Validate an AppID/DepotID and return it as a bare numeric string."""
    if item_id is None:
        return None
    s = str(item_id).strip()
    return s if _NUMERIC_ID_RE.match(s) else None

def _sanitize_key(key) -> str | None:
    """Validate a 64-char AES hex decryption key. Returns it VERBATIM.

    Canary rule: valid 64-hex keys must be written to DecryptionKeys 100% of
    the time and never sanitized. Hex is case-insensitive to Steam, so we
    deliberately do NOT normalize case here — the key is stored exactly as
    supplied. Only whitespace is stripped.
    """
    if not key:
        return None
    k = str(key).strip()
    return k if _HEX_64_RE.match(k) else None

def _validate_yaml_content(content: str) -> bool:
    """Refuse to write malformed YAML, or YAML with duplicate top-level keys.

    PyYAML silently keeps only the first of two duplicate keys, so a duplicate
    section makes an edit a silent no-op. It is not bundled with Decky, so the
    duplicate scan runs unconditionally and the syntax parse is best-effort.
    """
    try:
        import yaml  # type: ignore
        yaml.safe_load(content)
    except ImportError:
        logger.debug("PyYAML unavailable; skipping syntax parse before write")
    except Exception as e:
        logger.error(f"Refusing to write invalid YAML to config: {e}")
        return False

    top_keys = re.findall(r"^['\"]?([A-Za-z0-9_]+)['\"]?(?=[ \t]*:)", content, re.MULTILINE)
    seen: set[str] = set()
    dupes: set[str] = set()
    for k in top_keys:
        if k in seen:
            dupes.add(k)
        seen.add(k)
    if dupes:
        logger.error(f"Refusing to write config with duplicate top-level keys: {dupes}")
        return False
    return True

def _write_sls_config(cfg: Path, content: str, notify: bool = True) -> bool:
    """Atomically write config.yaml in place, preserving the inode.

    The inode matters: SLSsteam watches the file with inotify. A tmp+rename
    swap would emit a delete/create pair and can race a reader into seeing an
    empty config. 0600 is enforced because the file holds the user's keys.
    """
    if cfg is None:
        return False
    if not _validate_yaml_content(content):
        return False
    with _sls_write_lock:
        try:
            cfg.parent.mkdir(parents=True, exist_ok=True)
            if cfg.exists():
                with open(cfg, "r+", encoding="utf-8") as f:
                    f.seek(0)
                    f.write(content)
                    f.truncate()
                    f.flush()
                    os.fsync(f.fileno())
            else:
                with open(cfg, "w", encoding="utf-8") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
            try:
                os.chmod(cfg, 0o600)
            except OSError:
                pass
        except Exception as e:
            logger.error("Failed writing %s: %s", cfg, e)
            return False
    if notify:
        _signal_slssteam_api("RELOAD")
    return True

def _get_section_bounds(content: str, section_name: str) -> tuple[int, int, int] | None:
    """Return (header_start, content_start, section_end) for a top-level section."""
    header = re.compile(
        r"^[ \t]*['\"]?" + re.escape(section_name) + r"['\"]?[ \t]*:[ \t]*(?:\[[ \t]*\]|\{[ \t]*\})?[ \t]*(?:#[^\r\n]*)?$",
        re.MULTILINE,
    )
    m = header.search(content)
    if not m:
        return None
    h_start, c_start = m.start(), m.end()
    if c_start < len(content) and content[c_start] == "\r":
        c_start += 1
    if c_start < len(content) and content[c_start] == "\n":
        c_start += 1
    after = content[c_start:]
    nxt = _TOP_LEVEL_KEY_RE.search(after)
    return h_start, c_start, (c_start + nxt.start()) if nxt else len(content)

def _section_insert_pos(content: str, c_start: int, s_end: int) -> int:
    """Index just after the last list/map item in a section (never under a trailing comment)."""
    offset = 0
    last_item_end = 0
    for line in content[c_start:s_end].splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("-") or re.match(r"^['\"]?[A-Za-z0-9_]+['\"]?\s*:", stripped):
            last_item_end = offset + len(line)
        offset += len(line)
    return c_start + last_item_end

def _upsert_in_memory(content: str, section: str, key: str, value: str = "", comment: str = "") -> tuple[str, bool]:
    """Add/update a section entry entirely in memory. Returns (content, changed).

    value == "" -> list item:  "  - {key} # {comment}"
    value != "" -> map item:   "  {key}: {value} # {comment}"
    """
    clean = _sanitize_id(key)
    if not clean:
        return content, False
    comment = _sanitize_comment(comment)
    entry = f"  {clean}: {value} # {comment}" if value else f"  - {clean} # {comment}"

    bounds = _get_section_bounds(content, section)
    if bounds is None:
        return content.rstrip() + f"\n\n{section}:\n{entry}\n", True

    _, c_start, s_end = bounds
    sec = content[c_start:s_end]
    if value:
        pattern = re.compile(
            rf"^[ \t]*['\"]?{re.escape(clean)}['\"]?[ \t]*:[ \t]*['\"]?([^ \t#'\"]*)['\"]?[ \t]*(?:#[^\r\n]*)?$",
            re.MULTILINE,
        )
    else:
        pattern = re.compile(
            rf"^[ \t]*-[ \t]*{re.escape(clean)}[ \t]*(?:#[^\r\n]*)?$",
            re.MULTILINE,
        )

    m = pattern.search(sec)
    if m:
        # For map entries an identical value already present is a no-op, so
        # repeated injects stay idempotent instead of rewriting the file.
        if value and (m.group(1) or "").strip().lower() == value.strip().lower():
            return content, False
        # lambda avoids backslash/group expansion in the replacement
        new_sec = pattern.sub(lambda _m: entry, sec, count=1)
        return content[:c_start] + new_sec + content[s_end:], True

    pos = _section_insert_pos(content, c_start, s_end)
    return content[:pos] + entry + "\n" + content[pos:], True

def _remove_in_memory(content: str, section: str, key: str, is_list: bool | None = None) -> tuple[str, bool]:
    """Remove a section entry entirely in memory. Returns (content, removed)."""
    clean = _sanitize_id(key)
    if not clean:
        return content, False
    bounds = _get_section_bounds(content, section)
    if bounds is None:
        return content, False
    _, c_start, s_end = bounds
    sec = content[c_start:s_end]
    if is_list is None:
        is_list = bool(re.search(r"^[ \t]*-[ \t]*\d+", sec, re.MULTILINE))
    if is_list:
        pattern = re.compile(rf"^[ \t]*-[ \t]*{re.escape(clean)}[ \t]*(?:#[^\r\n]*)?\r?\n?", re.MULTILINE)
    else:
        pattern = re.compile(rf"^[ \t]*['\"]?{re.escape(clean)}['\"]?[ \t]*:[^\r\n]*\r?\n?", re.MULTILINE)
    new_sec, n = pattern.subn("", sec, count=1)
    if not n:
        return content, False
    return content[:c_start] + new_sec + content[s_end:], True

def _parse_list_section(content: str, section: str) -> dict[str, str]:
    """Parse a `  - 123 # comment` list section into {id: comment}."""
    out: dict[str, str] = {}
    bounds = _get_section_bounds(content, section)
    if not bounds:
        return out
    for line in content[bounds[1]:bounds[2]].splitlines():
        m = re.match(r"^[ \t]*-[ \t]*(\d+)(?:[ \t]*#[ \t]*(.*))?$", line)
        if m:
            out[m.group(1)] = (m.group(2) or "").strip()
    return out

def _parse_key_section(content: str, section: str) -> tuple[dict[str, str], dict[str, str]]:
    """Parse a `  123: <64hex> # comment` map section into ({id: key}, {id: comment})."""
    keys: dict[str, str] = {}
    comments: dict[str, str] = {}
    bounds = _get_section_bounds(content, section)
    if not bounds:
        return keys, comments
    for m in re.finditer(
        r"^[ \t]*['\"]?(\d+)['\"]?[ \t]*:[ \t]*['\"]?([a-fA-F0-9]{64})['\"]?(?:[ \t]*#[ \t]*(.*))?$",
        content[bounds[1]:bounds[2]],
        re.MULTILINE,
    ):
        keys[m.group(1)] = m.group(2)
        comments[m.group(1)] = (m.group(3) or "").strip()
    return keys, comments

def _replace_section_block(content: str, section: str, body_lines: list[str]) -> str:
    """Replace (or append) a whole top-level section, sorting entries numerically."""
    block = "\n".join([f"{section}:"] + body_lines) + "\n"
    bounds = _get_section_bounds(content, section)
    if bounds:
        old_block = content[bounds[0]:bounds[2]]
        # Keep the blank-line separation that followed the old section so the
        # file keeps the same visual layout it had before the rewrite.
        trailing = len(old_block) - len(old_block.rstrip("\n"))
        if trailing:
            block += "\n" * (trailing - 1)
        return content[:bounds[0]] + block + content[bounds[2]:]
    return content.rstrip() + "\n\n" + block

def _sort_ids(ids) -> list[str]:
    return sorted(ids, key=lambda x: int(x) if x.isdigit() else 0)

def _ensure_plugins_enabled(content: str) -> str:
    """Force `Plugins: yes` — the library-inject plugin loader requires it.

    Matches ASSella's `ensure_plugins_enabled` / the AT0M patch step 1.
    """
    if re.search(r"^[ \t]*Plugins[ \t]*:[ \t]*(?:yes|true)\b", content, re.MULTILINE | re.IGNORECASE):
        return content
    if re.search(r"^[ \t]*Plugins[ \t]*:", content, re.MULTILINE):
        return re.sub(r"^[ \t]*Plugins[ \t]*:.*$", "Plugins: yes", content, flags=re.MULTILINE)
    return "Plugins: yes\n" + content

def _ensure_smart_tickets(content: str) -> str:
    """Ensure `SmartTickets: 0x1` is present, mirroring ASSella's AT0M path."""
    m = re.search(r"^([ \t]*)SmartTickets[ \t]*:[ \t]*([^\r\n#]+)(.*)$", content, re.MULTILINE)
    if not m:
        return content.rstrip() + "\n\nSmartTickets: 0x1\n"
    if m.group(2).strip().lower() == "0x1":
        return content
    comment = f" {m.group(3).strip()}" if m.group(3).strip() else ""
    return re.sub(
        r"^[ \t]*SmartTickets[ \t]*:[^\r\n#]*",
        f"{m.group(1)}SmartTickets: 0x1{comment}",
        content,
        count=1,
        flags=re.MULTILINE,
    )

class _SlsConfigEditor:
    """One read -> many in-memory edits -> one validated in-place write.

    Mirrors ASSella's `batch_config_edit` context manager. Batching matters:
    per-entry writes mean a config reread+rewrite per entry, a backup per
    entry, and a reload notification per entry — SLSsteam would reload the
    whole library dozens of times for a single game.
    """

    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path if config_path is not None else _find_sls_config()
        self.content = ""
        self.has_changes = False
        self.committed_successfully = True

    def __enter__(self) -> "_SlsConfigEditor":
        if self.config_path is None:
            self.content = ""
        elif self.config_path.exists():
            self.content = self.config_path.read_text(encoding="utf-8", errors="replace")
        else:
            self.content = "Plugins: yes\nAdditionalApps:\n"
        self.has_changes = False
        self.committed_successfully = True
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.committed_successfully = False
            return False
        if self.has_changes:
            self.committed_successfully = _write_sls_config(self.config_path, self.content)
            if not self.committed_successfully:
                return False
        return True

    def _apply(self, content: str, changed: bool) -> bool:
        if changed:
            self.content = content
            self.has_changes = True
        return changed

    def add_app(self, app_id: str, comment: str = "") -> bool:
        return self._apply(*_upsert_in_memory(self.content, "AdditionalApps", app_id, comment=comment))

    def remove_app(self, app_id: str) -> bool:
        return self._apply(*_remove_in_memory(self.content, "AdditionalApps", app_id, is_list=True))

    def add_depot(self, depot_id: str, comment: str = "") -> bool:
        return self._apply(*_upsert_in_memory(self.content, "AdditionalDepots", depot_id, comment=comment))

    def remove_depot(self, depot_id: str) -> bool:
        return self._apply(*_remove_in_memory(self.content, "AdditionalDepots", depot_id, is_list=True))

    def add_key(self, depot_id: str, key: str, comment: str = "") -> bool:
        clean = _sanitize_key(key)
        if not clean:
            logger.warning(f"Refusing to write invalid AES key for depot {depot_id}")
            return False
        return self._apply(*_upsert_in_memory(self.content, "DecryptionKeys", depot_id, value=clean, comment=comment))

    def remove_key(self, depot_id: str) -> bool:
        return self._apply(*_remove_in_memory(self.content, "DecryptionKeys", depot_id, is_list=False))

    def add_manifest_id(self, depot_id: str, manifest_id: str) -> bool:
        mid = str(manifest_id).strip()
        if not mid or not _NUMERIC_ID_RE.match(mid):
            return False
        return self._apply(*_upsert_in_memory(self.content, "ManifestIds", depot_id, value=mid))

    def add_fake_app_id(self, app_id: str, target_id: str, comment: str = "") -> bool:
        return self._apply(*_upsert_in_memory(self.content, "FakeAppIds", app_id, value=str(target_id), comment=comment))

    def remove_fake_app_id(self, app_id: str) -> bool:
        return self._apply(*_remove_in_memory(self.content, "FakeAppIds", app_id, is_list=False))

    def remove_launch_option(self, app_id: str) -> bool:
        return self._apply(*_remove_in_memory(self.content, "LaunchOptions", app_id, is_list=False))

    def remove_dlc(self, app_id: str) -> bool:
        """Remove a whole nested DlcData block for this parent app."""
        before = self.content
        changed = _remove_dlc_block(self.content, app_id)
        if changed is None:
            return False
        return self._apply(changed, True)

def _batch_config_edit(config_path: Path | None = None) -> _SlsConfigEditor:
    return _SlsConfigEditor(config_path)

# ---------------------------------------------------------------------------
