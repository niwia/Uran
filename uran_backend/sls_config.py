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
from .paths import SLSSTEAM_API_PIPE

_HEX_64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_NUMERIC_ID_RE = re.compile(r"^\d+$")
_TOP_LEVEL_KEY_RE = re.compile(r"^['\"]?[A-Za-z0-9_]+['\"]?[ \t]*:", re.MULTILINE)


def sanitize_comment(comment) -> str:
    """Strip newlines/control chars from a comment to prevent YAML line injection."""
    if not comment:
        return ""
    cleaned = str(comment).replace("\r", " ").replace("\n", " ").strip()
    return re.sub(r"[ \t]+", " ", cleaned)


def sanitize_id(item_id) -> str | None:
    """Validate an AppID/DepotID and return it as a bare numeric string."""
    if item_id is None:
        return None
    text = str(item_id).strip()
    return text if _NUMERIC_ID_RE.match(text) else None


def sanitize_key(key) -> str | None:
    """Validate a 64-char AES hex decryption key. Returns it VERBATIM.

    Canary rule: valid 64-hex keys must be written to DecryptionKeys 100% of
    the time and never sanitized. Hex is case-insensitive to Steam, so we
    deliberately do NOT normalize case here. Only whitespace is stripped.
    """
    if not key:
        return None
    text = str(key).strip()
    return text if _HEX_64_RE.match(text) else None


def validate_yaml(content: str, log) -> bool:
    """Refuse to write malformed YAML, or YAML with duplicate top-level keys.

    PyYAML silently keeps only the first of two duplicate keys, so a duplicate
    section makes an edit a silent no-op. It is not bundled with Decky, so the
    duplicate scan runs unconditionally and the syntax parse is best-effort.
    """
    try:
        import yaml  # type: ignore

        yaml.safe_load(content)
    except ImportError:
        pass  # PyYAML unavailable; the duplicate scan below still runs
    except Exception as exc:  # noqa: BLE001
        log.error("Refusing to write invalid YAML to config: %s", exc)
        return False

    top_keys = re.findall(r"^['\"]?([A-Za-z0-9_]+)['\"]?(?=[ \t]*:)", content, re.MULTILINE)
    seen: set[str] = set()
    dupes: set[str] = set()
    for key in top_keys:
        if key in seen:
            dupes.add(key)
        seen.add(key)
    if dupes:
        log.error("Refusing to write config with duplicate top-level keys: %s", dupes)
        return False
    return True


def signal_api(command: str = "RELOAD", log=None) -> bool:
    """Signal /tmp/SLSsteam.API pipe for zero-restart instant hot reload."""
    pipe = Path(SLSSTEAM_API_PIPE)
    if not pipe.exists():
        return False
    try:
        with open(pipe, "w") as handle:
            handle.write(command.strip() + "\n")
            handle.flush()
        if log:
            log.info("Signaled SLSsteam.API: %s", command)
        return True
    except OSError:
        return False


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
        if not cfg:
            return {"error": "SLSsteam config not found"}
        source = self.backups_dir() / backup_name
        if not source.exists():
            return {"error": f"Backup {backup_name} not found"}
        try:
            self.create_backup("pre_restore")
            with self.ctx.sls_lock:
                shutil.copy2(source, cfg)
            signal_api("RELOAD", self.log)
            return {"success": True, "verified": True}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    # -- low-level write -----------------------------------------------------
    def write(self, content: str, notify: bool = True) -> bool:
        """Atomically write config.yaml in place, preserving the inode."""
        cfg = self.config_path
        if cfg is None or not cfg.exists():
            self.log.error(
                "Refusing to write %s: file does not exist. SLSsteam must generate config.yaml first.",
                cfg,
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
def section_bounds(content: str, section_name: str) -> tuple[int, int, int] | None:
    """Return (header_start, content_start, section_end) for a top-level section."""
    header = re.compile(
        r"^[ \t]*['\"]?" + re.escape(section_name) + r"['\"]?[ \t]*:[ \t]*(?:\[[ \t]*\]|\{[ \t]*\})?[ \t]*(?:#[^\r\n]*)?$",
        re.MULTILINE,
    )
    match = header.search(content)
    if not match:
        return None
    header_start, content_start = match.start(), match.end()
    if content_start < len(content) and content[content_start] == "\r":
        content_start += 1
    if content_start < len(content) and content[content_start] == "\n":
        content_start += 1
    after = content[content_start:]
    next_key = _TOP_LEVEL_KEY_RE.search(after)
    return header_start, content_start, (content_start + next_key.start()) if next_key else len(content)


def _section_insert_pos(content: str, content_start: int, section_end: int) -> int:
    """Index just after the last list/map item in a section (never under a trailing comment)."""
    offset = 0
    last_item_end = 0
    for line in content[content_start:section_end].splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("-") or re.match(r"^['\"]?[A-Za-z0-9_]+['\"]?\s*:", stripped):
            last_item_end = offset + len(line)
        offset += len(line)
    return content_start + last_item_end


def upsert_in_memory(
    content: str, section: str, key: str, value: str = "", comment: str = ""
) -> tuple[str, bool]:
    """Add/update a section entry entirely in memory. Returns (content, changed).

    value == "" -> list item:  "  - {key} # {comment}"
    value != "" -> map item:   "  {key}: {value} # {comment}"
    """
    clean = sanitize_id(key)
    if not clean:
        return content, False
    comment = sanitize_comment(comment)
    entry = f"  {clean}: {value} # {comment}" if value else f"  - {clean} # {comment}"

    bounds = section_bounds(content, section)
    if bounds is None:
        return content.rstrip() + f"\n\n{section}:\n{entry}\n", True

    _, content_start, section_end = bounds
    sec = content[content_start:section_end]
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

    match = pattern.search(sec)
    if match:
        # For map entries an identical value already present is a no-op, so
        # repeated injects stay idempotent instead of rewriting the file.
        if value and (match.group(1) or "").strip().lower() == value.strip().lower():
            return content, False
        # lambda avoids backslash/group expansion in the replacement
        new_sec = pattern.sub(lambda _m: entry, sec, count=1)
        return content[:content_start] + new_sec + content[section_end:], True

    pos = _section_insert_pos(content, content_start, section_end)
    return content[:pos] + entry + "\n" + content[pos:], True


def remove_in_memory(
    content: str, section: str, key: str, is_list: bool | None = None
) -> tuple[str, bool]:
    """Remove a section entry entirely in memory. Returns (content, removed)."""
    clean = sanitize_id(key)
    if not clean:
        return content, False
    bounds = section_bounds(content, section)
    if bounds is None:
        return content, False
    _, content_start, section_end = bounds
    sec = content[content_start:section_end]
    if is_list is None:
        is_list = bool(re.search(r"^[ \t]*-[ \t]*\d+", sec, re.MULTILINE))
    if is_list:
        pattern = re.compile(
            rf"^[ \t]*-[ \t]*{re.escape(clean)}[ \t]*(?:#[^\r\n]*)?\r?\n?", re.MULTILINE
        )
    else:
        pattern = re.compile(
            rf"^[ \t]*['\"]?{re.escape(clean)}['\"]?[ \t]*:[^\r\n]*\r?\n?", re.MULTILINE
        )
    new_sec, count = pattern.subn("", sec, count=1)
    if not count:
        return content, False
    return content[:content_start] + new_sec + content[section_end:], True


def parse_list_section(content: str, section: str) -> dict[str, str]:
    """Parse a `  - 123 # comment` list section into {id: comment}."""
    out: dict[str, str] = {}
    bounds = section_bounds(content, section)
    if not bounds:
        return out
    for line in content[bounds[1]:bounds[2]].splitlines():
        match = re.match(r"^[ \t]*-[ \t]*(\d+)(?:[ \t]*#[ \t]*(.*))?$", line)
        if match:
            out[match.group(1)] = (match.group(2) or "").strip()
    return out


def parse_key_section(content: str, section: str) -> tuple[dict[str, str], dict[str, str]]:
    """Parse a `  123: <64hex> # comment` map section into ({id: key}, {id: comment})."""
    keys: dict[str, str] = {}
    comments: dict[str, str] = {}
    bounds = section_bounds(content, section)
    if not bounds:
        return keys, comments
    for match in re.finditer(
        r"^[ \t]*['\"]?(\d+)['\"]?[ \t]*:[ \t]*['\"]?([a-fA-F0-9]{64})['\"]?(?:[ \t]*#[ \t]*(.*))?$",
        content[bounds[1]:bounds[2]],
        re.MULTILINE,
    ):
        keys[match.group(1)] = match.group(2)
        comments[match.group(1)] = (match.group(3) or "").strip()
    return keys, comments


def parse_manifest_section(content: str) -> tuple[dict[str, str], dict[str, str]]:
    """Parse a `  123: 456789 # comment` ManifestIds section into ({id: gid}, {id: comment})."""
    gids: dict[str, str] = {}
    comments: dict[str, str] = {}
    bounds = section_bounds(content, "ManifestIds")
    if not bounds:
        return gids, comments
    for match in re.finditer(
        r"^[ \t]*['\"]?(\d+)['\"]?[ \t]*:[ \t]*['\"]?(\d+)['\"]?(?:[ \t]*#[ \t]*(.*))?$",
        content[bounds[1]:bounds[2]],
        re.MULTILINE,
    ):
        gids[match.group(1)] = match.group(2)
        comments[match.group(1)] = (match.group(3) or "").strip()
    return gids, comments


def parse_app_token_section(content: str) -> tuple[dict[str, str], dict[str, str]]:
    """Parse a `  123: token_value # comment` AppTokens section into ({id: token}, {id: comment})."""
    tokens: dict[str, str] = {}
    comments: dict[str, str] = {}
    bounds = section_bounds(content, "AppTokens")
    if not bounds:
        return tokens, comments
    for match in re.finditer(
        r"^[ \t]*['\"]?(\d+)['\"]?[ \t]*:[ \t]*([^\r\n#]+)(?:[ \t]*#[ \t]*(.*))?$",
        content[bounds[1]:bounds[2]],
        re.MULTILINE,
    ):
        app_id = match.group(1)
        token_val = match.group(2).strip().strip("\"'")
        if app_id and token_val:
            tokens[app_id] = token_val
            comments[app_id] = (match.group(3) or "").strip()
    return tokens, comments


def replace_section_block(content: str, section: str, body_lines: list[str]) -> str:
    """Replace (or append) a whole top-level section, sorting entries numerically."""
    block = "\n".join([f"{section}:"] + body_lines) + "\n"
    bounds = section_bounds(content, section)
    if bounds:
        old_block = content[bounds[0]:bounds[2]]
        # Keep the blank-line separation that followed the old section so the
        # file keeps the same visual layout it had before the rewrite.
        trailing = len(old_block) - len(old_block.rstrip("\n"))
        if trailing:
            block += "\n" * (trailing - 1)
        return content[:bounds[0]] + block + content[bounds[2]:]
    return content.rstrip() + "\n\n" + block


def sort_ids(ids) -> list[str]:
    return sorted(ids, key=lambda x: int(x) if x.isdigit() else 0)


def ensure_plugins_enabled(content: str) -> str:
    """Force `Plugins: yes` — the library-inject plugin loader requires it."""
    if re.search(r"^[ \t]*Plugins[ \t]*:[ \t]*(?:yes|true)\b", content, re.MULTILINE | re.IGNORECASE):
        return content
    if re.search(r"^[ \t]*Plugins[ \t]*:", content, re.MULTILINE):
        return re.sub(r"^[ \t]*Plugins[ \t]*:.*$", "Plugins: yes", content, flags=re.MULTILINE)
    return "Plugins: yes\n" + content


def ensure_smart_tickets(content: str) -> str:
    """Ensure `SmartTickets: 0x1` is present, mirroring ASSella's AT0M path."""
    match = re.search(r"^([ \t]*)SmartTickets[ \t]*:[ \t]*([^\r\n#]+)(.*)$", content, re.MULTILINE)
    if not match:
        return content.rstrip() + "\n\nSmartTickets: 0x1\n"
    if match.group(2).strip().lower() == "0x1":
        return content
    comment = f" {match.group(3).strip()}" if match.group(3).strip() else ""
    return re.sub(
        r"^[ \t]*SmartTickets[ \t]*:[^\r\n#]*",
        f"{match.group(1)}SmartTickets: 0x1{comment}",
        content,
        count=1,
        flags=re.MULTILINE,
    )


def ensure_section_header(content: str, section: str) -> str:
    """Ensure a top-level section header exists in YAML content without modifying existing entries."""
    if section_bounds(content, section) is not None:
        return content
    stripped = content.rstrip()
    if not stripped:
        return f"{section}:\n"
    return f"{stripped}\n\n{section}:\n"


def ensure_required_sections(content: str) -> str:
    """Ensure Plugins: yes, AdditionalDepots:, and DecryptionKeys: headers are present."""
    updated = ensure_plugins_enabled(content)
    updated = ensure_section_header(updated, "AdditionalDepots")
    updated = ensure_section_header(updated, "DecryptionKeys")
    return updated


def remove_dlc_block(content: str, app_id: str) -> str | None:
    """Remove a game's whole nested DlcData block (and its child lines).

    Returns the new content, or None when nothing matched.
    """
    bounds = section_bounds(content, "DlcData")
    if not bounds:
        return None
    _, content_start, section_end = bounds
    sec = content[content_start:section_end]
    pattern = re.compile(
        rf"^[ \t]{{1,4}}['\"]?{re.escape(app_id)}['\"]?[ \t]*:[^\r\n]*(?:\r?\n(?:^[ \t]+[^\r\n]*\r?\n)*)?",
        re.MULTILINE,
    )
    new_sec, count = pattern.subn("", sec, count=1)
    if not count:
        return None
    return content[:content_start] + new_sec + content[section_end:]


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
        if cfg is None or not cfg.exists():
            self.content = ""
            self.has_changes = False
            self.committed_successfully = False
            return self
        self.content = cfg.read_text(encoding="utf-8", errors="replace")
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