"""SLSsteam config.yaml text editing shared by ASSella, Uran and Epsilon.

Pure functions only: no Decky, Qt or path discovery. Writes are the caller's
job; these helpers take and return the file's text. Comments, key order and
ownership tags (``# Game Name``) survive every edit, because ASSella parses the
tags back to decide which entries belong to which game.
"""

import re
from pathlib import Path

SLSSTEAM_API_PIPE = "/tmp/SLSsteam.API"


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
        if not _fallback_yaml_syntax_valid(content):
            log.error("Refusing to write config with invalid YAML syntax (PyYAML is unavailable)")
            return False
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


def _fallback_yaml_syntax_valid(content: str) -> bool:
    """Validate the mapping/list YAML subset used by SLSsteam configs.

    Decky does not ship PyYAML. This conservative fallback catches malformed
    structure, indentation tabs, unterminated quotes, and unbalanced flow
    collections without rejecting ordinary block collections or scalars.
    """
    top_key = re.compile(r"^(?:[A-Za-z0-9_.-]+|'(?:[^']|'')+'|\"[^\"]+\")\s*:(?:\s|$)")
    child_key = re.compile(r"^(?:-\s+)?(?:[A-Za-z0-9_.-]+|'(?:[^']|'')+'|\"[^\"]+\")\s*:(?:\s|$)")
    block_scalar = re.compile(r"^(?:[^:#]+):\s*[|>][+-]?(?:[1-9])?\s*(?:#.*)?$")
    stack: list[str] = []
    quote: str | None = None
    has_root_mapping = False
    block_indent: int | None = None

    for raw in content.splitlines():
        leading = len(raw) - len(raw.lstrip(" "))
        if "\t" in raw[:leading] or (leading < len(raw) and raw[leading] == "\t"):
            return False
        text = raw[leading:]
        if not text.strip() or text.startswith("#"):
            continue
        if block_indent is not None:
            if leading > block_indent:
                continue
            block_indent = None

        if not stack and quote is None:
            if leading == 0:
                if text in {"---", "..."}:
                    continue
                if not top_key.match(text):
                    return False
                has_root_mapping = True
            elif not has_root_mapping:
                return False
            elif text != "-" and not text.startswith("- ") and not child_key.match(text):
                return False

        index = 0
        while index < len(text):
            char = text[index]
            if quote:
                if quote == '"' and char == "\\":
                    index += 2
                    continue
                if char == quote:
                    if quote == "'" and index + 1 < len(text) and text[index + 1] == "'":
                        index += 2
                        continue
                    quote = None
            elif char in {"'", '"'}:
                quote = char
            elif char == "#" and (index == 0 or text[index - 1].isspace()):
                break
            elif char in "[{":
                stack.append("]" if char == "[" else "}")
            elif char in "]}":
                if not stack or stack.pop() != char:
                    return False
            index += 1

        if block_scalar.match(text):
            block_indent = leading

    return has_root_mapping and not stack and quote is None


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
