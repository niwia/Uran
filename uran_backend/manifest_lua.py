"""Comment-aware Lua manifest parsing.

Hubcap's Lua mixes live statements with commented-out ones. Commented entries
are how the generator disables depots it cannot serve:

    -- addappid(5136471, 1, "MISSING_KEY") -- no key available
    -- addappid(1042553)                   -- empty depot

A naive finditer matches those too, which injects dead depots into
AdditionalApps/AdditionalDepots and (worse) treats a keyless `addappid(<id>)`
as a license-only DLC. Every scan here is therefore comment-aware.
"""

import bisect
import re

MISSING_KEY_SENTINEL = "MISSING_KEY"
_PLACEHOLDER_KEYS = {MISSING_KEY_SENTINEL, "", "0", "NULL", "NONE", "UNKNOWN"}

_DEPOT_ID_RE = re.compile(r"^[0-9]{1,12}$")
_MANIFEST_GID_RE = re.compile(r"^[0-9]{1,24}$")

_LIVE_APPID_RE = re.compile(
    r'addappid\(\s*(\d+)\s*(?:,\s*(\d+))?(?:\s*,\s*["\']([^"\']*)["\'])?\s*\)(.*)',
    re.IGNORECASE,
)
_LIVE_SETMANIFEST_RE = re.compile(
    r'setManifestid\(\s*(\d+)\s*,\s*["\']([^"\']+)["\']', re.IGNORECASE
)


def lua_comment_spans(content: str) -> list[tuple[int, int]]:
    """(start, end) index pairs for every Lua `--` line comment.

    String-aware, so a `--` inside a quoted key is not treated as a comment.
    """
    spans = []
    length = len(content)
    index = 0
    quote = None
    while index < length:
        char = content[index]
        if quote is not None:
            if char == "\\" and quote == '"':
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char == "-" and content.startswith("--", index):
            end = content.find("\n", index)
            if end == -1:
                end = length
            spans.append((index, end))
            index = end
            continue
        index += 1
    return spans


def iter_live_matches(content: str, pattern: re.Pattern, flags: int = 0):
    """Yield matches that are NOT inside a Lua line comment."""
    spans = lua_comment_spans(content)
    if not spans:
        yield from re.finditer(pattern, content, flags)
        return
    starts = [s for s, _ in spans]
    for match in re.finditer(pattern, content, flags):
        pos = match.start()
        slot = bisect.bisect_right(starts, pos) - 1
        if slot >= 0 and pos < spans[slot][1]:
            continue
        yield match


def is_placeholder_key(value: str) -> bool:
    """True when a generator sentinel was used instead of a real AES key."""
    text = str(value).strip().strip("\"'")
    if not text:
        return True
    return text.upper() in _PLACEHOLDER_KEYS


def coerce_depot_id(value) -> str | None:
    """Clean numeric AppID/DepotID, or None. Guards against path injection.

    Remote Lua identifiers get interpolated into depotcache filenames and config
    values, so anything non-numeric is rejected here.
    """
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text if _DEPOT_ID_RE.match(text) else None


def coerce_manifest_gid(value) -> str | None:
    text = str(value).strip() if isinstance(value, (str, int)) else ""
    return text if _MANIFEST_GID_RE.match(text) else None


def parse(lua_text: str, sanitize_key=None) -> dict:
    """Parse a Hubcap Lua into its appid, keys, DLCs, manifests and depots.

    Mirrors ASSella's `ProcessZipTask._parse_lua` semantics:
      - only live (non-commented) addappid() statements count
      - the FIRST live addappid is the main application (its 3rd arg is the AppKey)
      - an addappid with no key is a DLC (license-only), not a depot
      - MISSING_KEY / placeholder values are never treated as keys
    """
    result = {
        "appid": None,
        "name": None,
        "app_key": None,
        "keys": {},
        "dlcs": [],
        "manifests": {},
        "depots": [],
    }
    if not lua_text:
        return result

    first = True
    for match in iter_live_matches(lua_text, _LIVE_APPID_RE):
        did = coerce_depot_id(match.group(1))
        if not did:
            continue
        key = (match.group(3) or "").strip()
        tail = match.group(4) or ""

        if first:
            first = False
            result["appid"] = did
            named = re.search(r"--\s*(.*)", tail)
            if named and named.group(1).strip():
                result["name"] = named.group(1).strip()
            if key and not is_placeholder_key(key):
                result["app_key"] = key
                result["keys"][did] = key
                result["depots"].append(did)
            continue

        if key and not is_placeholder_key(key):
            # A real depot with a usable key.
            clean = sanitize_key(key) if sanitize_key else key
            if clean:
                result["keys"][did] = clean
                result["depots"].append(did)
                continue
        if not key:
            # No key argument => license-only DLC entry.
            result["dlcs"].append(did)

    for match in iter_live_matches(lua_text, _LIVE_SETMANIFEST_RE):
        did = coerce_depot_id(match.group(1))
        gid = coerce_manifest_gid(match.group(2))
        if did and gid:
            result["manifests"][did] = gid

    return result


def harvest_depot_names(lua_text: str, cache: dict, sanitize=None) -> int:
    """Cache depot descriptions from live setManifestid/addappid comments."""
    found = 0
    for match in iter_live_matches(lua_text, _LIVE_APPID_RE):
        did = coerce_depot_id(match.group(1))
        named = re.search(r"--\s*(.*)", match.group(4) or "")
        label = (named.group(1).strip() if named else "").replace("\n", " ")
        if not label or not did:
            continue
        if sanitize:
            label = sanitize(label)
        if label and cache.get(did) != label:
            cache[did] = label
            found += 1
    return found