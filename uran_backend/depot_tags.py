"""Depot metadata enrichment and tagging utilities for AT0-M.

Ports ASSella's depot tag helpers to the Decky plugin backend:
  - Platform OS normalization (Windows, Linux, macOS, Android)
  - Architecture detection (x64, x86) from metadata fields or text patterns
  - Language code extraction mapped to standard 2-letter uppercase badges
  - DLC tag detection and AppID binding
  - Name cleaning to strip redundant scraped platform/architecture brackets
  - Human byte formatting for depot sizes
"""

import re
from typing import Any, Optional

STEAM_LANG_TO_CODE: dict[str, str] = {
    "arabic": "AR",
    "brazilian": "BR",
    "portuguese-brazil": "BR",
    "bulgarian": "BG",
    "czech": "CS",
    "danish": "DA",
    "dutch": "NL",
    "english": "EN",
    "finnish": "FI",
    "french": "FR",
    "german": "DE",
    "greek": "EL",
    "hungarian": "HU",
    "indonesian": "ID",
    "italian": "IT",
    "japanese": "JA",
    "koreana": "KO",
    "korean": "KO",
    "latam": "ES-419",
    "norwegian": "NO",
    "polish": "PL",
    "portuguese": "PT",
    "romanian": "RO",
    "russian": "RU",
    "schinese": "ZH-CN",
    "simplified chinese": "ZH-CN",
    "spanish": "ES",
    "swedish": "SV",
    "tchinese": "ZH-TW",
    "traditional chinese": "ZH-TW",
    "thai": "TH",
    "turkish": "TR",
    "ukrainian": "UK",
    "vietnamese": "VI",
}

_LANG_REGEX_PATTERNS = [
    (
        re.compile(
            r"\[(ar|bg|cs|da|de|el|en|es|fi|fr|hu|id|it|ja|ko|nl|no|pl|pt|pt-br|br|ro|ru|sv|th|tr|uk|vi|zh|zh-cn|zh-tw)\]",
            re.IGNORECASE,
        ),
        1,
    ),
    (
        re.compile(
            r"\b(arabic|brazilian|czech|danish|dutch|english|finnish|french|german|greek|hungarian|indonesian|italian|japanese|korean|norwegian|polish|portuguese|romanian|russian|spanish|swedish|thai|turkish|ukrainian|vietnamese)\s+(?:voice|audio|language|subs|subtitles)\b",
            re.IGNORECASE,
        ),
        1,
    ),
    (
        re.compile(
            r"(?:voice|audio|language)\s+pack\s*[-–:]\s*(arabic|brazilian|czech|danish|dutch|english|finnish|french|german|greek|hungarian|indonesian|italian|japanese|korean|norwegian|polish|portuguese|romanian|russian|spanish|swedish|thai|turkish|ukrainian|vietnamese)",
            re.IGNORECASE,
        ),
        1,
    ),
]


def extract_language_code(depot_data: dict[str, Any] | None, desc: str = "") -> Optional[str]:
    """Detect standard language code (e.g. 'EN', 'FR', 'DE', 'JA') from metadata or description."""
    if not isinstance(depot_data, dict):
        depot_data = {}

    # 1. Direct language metadata field
    lang_field = str(depot_data.get("language") or "").strip().lower()
    if lang_field and lang_field not in ("all", "none", "shared"):
        if lang_field in STEAM_LANG_TO_CODE:
            return STEAM_LANG_TO_CODE[lang_field]
        if len(lang_field) in (2, 5):
            return lang_field.upper()

    # 2. Check description and name
    text = f"{desc} {depot_data.get('name', '')} {depot_data.get('desc', '')}"
    for pat, group_idx in _LANG_REGEX_PATTERNS:
        m = pat.search(text)
        if m:
            val = m.group(group_idx).lower()
            if val in STEAM_LANG_TO_CODE:
                return STEAM_LANG_TO_CODE[val]
            return val.upper()

    return None


def extract_arch_code(depot_data: dict[str, Any] | None, desc: str = "") -> str:
    """Detect architecture tag ('x64' or 'x86') from metadata or text."""
    if not isinstance(depot_data, dict):
        depot_data = {}

    arch = str(
        depot_data.get("osarch")
        or (depot_data.get("config", {}).get("osarch") if isinstance(depot_data.get("config"), dict) else None)
        or ""
    ).strip().lower()

    if arch in ("64", "x64", "amd64", "x86_64", "win64", "linux64"):
        return "x64"
    if arch in ("32", "86", "x86", "win32", "i386", "i686"):
        return "x86"

    text = f"{desc} {depot_data.get('name', '')} {depot_data.get('desc', '')}".lower()
    if any(k in text for k in ("64-bit", "64 bit", "x64", "win64", "[64]", "[x64]")):
        return "x64"
    if any(k in text for k in ("32-bit", "32 bit", "x86", "win32", "[32]", "[x86]")):
        return "x86"

    return ""


def extract_os_list(oslist: Optional[str]) -> list[str]:
    """Parse platform string into normalized list: ['windows', 'linux', 'macos', 'android']."""
    if not oslist:
        return []
    os_str = str(oslist).strip().lower()
    platforms: list[str] = []
    if "windows" in os_str or "win" in os_str:
        platforms.append("windows")
    if "linux" in os_str:
        platforms.append("linux")
    if any(k in os_str for k in ("macos", "macosx", "apple", "osx")):
        platforms.append("macos")
    if "android" in os_str:
        platforms.append("android")

    if not platforms and "all" in os_str:
        platforms = ["windows", "linux"]

    return platforms


def format_bytes(num_bytes: int | float | str | None) -> str:
    """Format raw byte count into human-readable string (e.g. '12.68 GB', '512.00 MB')."""
    if not num_bytes:
        return ""
    try:
        val = float(num_bytes)
        if val <= 0:
            return ""
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if val < 1024.0 or unit == "TB":
                if unit == "B":
                    return f"{int(val)} B"
                return f"{val:.2f} {unit}"
            val /= 1024.0
    except (ValueError, TypeError):
        pass
    return ""


def clean_depot_name(depot_id: str, raw_name: str, fallback_name: str = "") -> str:
    """Strip redundant bracketed platform/arch/dlc tags to reveal clean depot title."""
    cleaned = raw_name or ""
    # Strip [Windows], [Linux], [macOS], etc.
    cleaned = re.sub(
        r"\[(?:Windows|Linux|macOS|Android|iOS|SteamDeck|Deck|All)(?:,\s*(?:Windows|Linux|macOS|Android|iOS|SteamDeck|Deck|All))*\]\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Strip [x64], [x86], [32-bit], etc.
    cleaned = re.sub(r"\[(?:x64|x86|64-bit|32-bit|64|32)\]\s*", "", cleaned, flags=re.IGNORECASE)
    # Strip [DLC ...], DLC ...
    cleaned = re.sub(r"\[DLC(?:\s+\d+)?\]\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^DLC\s+\d+\s*[-–:]?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()

    # If the cleaned name is just generic ("Windows", "Depot 12345", or empty), try fallback
    if not cleaned or cleaned.lower() in ("windows", "linux", "macos", "content") or re.fullmatch(r"Depot\s+\d+", cleaned, re.IGNORECASE):
        if fallback_name and not re.fullmatch(r"Depot\s+\d+", fallback_name, re.IGNORECASE):
            return clean_depot_name(depot_id, fallback_name, "")
        return cleaned or f"Depot {depot_id}"

    return cleaned


_PLACEHOLDER_DLC_NAMES = {"", "unknown", "-", "n/a", "none", "dlc"}


def is_placeholder_dlc_name(name: str, dlc_id: str) -> bool:
    """True when `name` is empty or a stand-in for a DLC we have no title for."""
    n = (name or "").strip()
    if n.lower() in _PLACEHOLDER_DLC_NAMES:
        return True
    if n.lower() == f"dlc {dlc_id}".lower():
        return True
    if n == str(dlc_id):
        return True
    return False


def qualify_dlc_name(name: str, dlc_id: str, game_name: str) -> str:
    """Prefix a placeholder DLC name with the parent game's name.

    When a DLC's name is 'Unknown', 'DLC <id>' or the id itself, gets formatted as
    '<game> - <placeholder>', making it obvious which game it belongs to.
    """
    name = (name or "").strip()
    if not is_placeholder_dlc_name(name, dlc_id):
        return name
    placeholder = name or f"DLC {dlc_id}"
    game_name = (game_name or "").strip()
    if not game_name:
        return placeholder
    return f"{game_name} - {placeholder}"
