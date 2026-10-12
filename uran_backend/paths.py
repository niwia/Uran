"""Filesystem and application-config path discovery.

Everything that answers "where does this live?" lives here: SLSsteam's config,
Steam's library roots, ACCELA's data dir, and the INI file Uran shares with
ASSella. Resolution is deliberately generous about location because Steam runs
natively on some systems and as a Flatpak on others, and Decky runs as root
while SLSsteam runs as the user.
"""

import logging
import os
import re
import time
from pathlib import Path

logger = logging.getLogger("Uran")

# Steamworks shared redistributables. Shared by every game, so ASSella tags them
# with a magic ownership comment that exempts them from uninstall cleanup. Uran
# mirrors that exactly so both tools agree on ownership.
SHARED_REDISTS: set[str] = {
    "228980", "1034630", "228981", "228982", "228983", "228984", "228985",
    "228986", "228987", "228988", "228989", "228990", "229000", "229001",
    "229002", "229003", "229004", "229005", "229006", "229007", "229010",
    "229011", "229012", "229020", "229030", "229031", "229032",
}
# Magic ownership marker read back by ASSella's cleanup heuristics.
SHARED_COMMENT = "Steamworks Shared"

SLSSTEAM_API_PIPE = "/tmp/SLSsteam.API"


def user_home(decky_user_home: str | None = None) -> Path:
    """Resolve the active user home, even under Decky's root daemon."""
    if decky_user_home:
        return Path(decky_user_home)
    decky_user = os.environ.get("DECKY_USER")
    if decky_user:
        candidate = Path(f"/home/{decky_user}")
        if candidate.is_dir():
            return candidate
    if Path("/home/deck").is_dir():
        return Path("/home/deck")
    return Path.home()


def sls_config(user_home_path: Path) -> Path | None:
    """Find the active SLSsteam config.yaml."""
    candidates = [
        user_home_path / ".config" / "SLSsteam" / "config.yaml",
        user_home_path / ".var/app/com.valvesoftware.Steam/.config/SLSsteam/config.yaml",
        user_home_path / ".local/share/SLSsteam/config.yaml",
        Path("/home/deck/.config/SLSsteam/config.yaml"),
        Path.home() / ".config" / "SLSsteam" / "config.yaml",
    ]
    for path in candidates:
        if path.exists():
            return path
    standard_dir = user_home_path / ".config" / "SLSsteam"
    if standard_dir.is_dir():
        return standard_dir / "config.yaml"
    return None


def steam_root(user_home_path: Path) -> Path | None:
    """Locate the Steam installation root."""
    candidates = [
        user_home_path / ".steam" / "steam",
        user_home_path / ".local/share/Steam",
        user_home_path / ".var/app/com.valvesoftware.Steam/data/Steam",
        Path("/home/deck/.steam/steam"),
        Path("/home/deck/.local/share/Steam"),
        Path.home() / ".steam" / "steam",
        Path.home() / ".local/share/Steam",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return None


def depotcache(user_home_path: Path) -> Path | None:
    """Steam's depotcache dir, created on demand."""
    root = steam_root(user_home_path)
    if root is None:
        return None
    cache = root / "depotcache"
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return cache


def accela_base(user_home_path: Path) -> Path:
    """ACCELA's XDG data dir, matching ASSella's utils.helpers.get_base_path()."""
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg and Path(xdg).is_absolute():
        return Path(xdg) / "ACCELA"
    return user_home_path / ".local" / "share" / "ACCELA"


# ---------------------------------------------------------------------------
# ASSella / ACCELA INI handling
#
# Uran shares one Hubcap API key with ASSella by writing morrenus_api_key into
# ASSella's own config, which ASSella reads via QSettings("Tachibana Labs",
# "ACCELA"). The file also holds QVariant blobs whose escaped form configparser
# would mangle, so every edit here is a targeted line replacement that leaves
# every other byte untouched.
# ---------------------------------------------------------------------------
def accela_conf_candidates(user_home_path: Path) -> list[Path]:
    """Config files ACCELA may store morrenus_api_key in, newest layout first."""
    candidates: list[Path] = []
    for home in (user_home_path, Path.home(), Path("/home/deck")):
        candidates.extend([
            home / ".config" / "Tachibana Labs" / "ACCELA.conf",
            home / ".var" / "app" / "com.valvesoftware.Steam" / "config" / "Tachibana Labs" / "ACCELA.conf",
            home / ".var" / "app" / "com.tachibanalabs.accela" / "config" / "Tachibana Labs" / "ACCELA.conf",
            home / ".config" / "ACCELA" / "Settings.conf",
            home / ".config" / "ACCELA" / "ACCELA.conf",
            home / ".config" / "ACCELA" / "ASSella.conf",
        ])
    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def read_ini_value(path: Path, key: str) -> str:
    """Read a scalar from an INI file, ignoring section headers and comments.

    Handles `key=value` and `key = value` (ACCELA writes the spaced form inside
    a [General] section), plus quoted values and inline `;` comments.
    """
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith((";", "#", "[")):
                continue
            if "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip().lower() != key.lower():
                continue
            value = value.strip()
            if ";" in value and not value.startswith(("\"", "'")):
                value = value.split(";", 1)[0].strip()
            value = value.strip().strip('"').strip("'").strip()
            if value:
                return value
    except Exception as exc:  # noqa: BLE001 - a missing/unreadable file is empty
        logger.debug("Failed reading %s from %s: %s", key, path, exc)
    return ""


def _build_ini_entry(original: str, key: str, value: str) -> str:
    """Return `original` with `key` set to `value`, preserving Qt's ordering."""
    entry = f"{key}={value}"

    # Replace an existing line (any section) in place to keep ordering.
    pattern = re.compile(rf"^[ \t]*{re.escape(key)}[ \t]*=.*$", re.MULTILINE)
    if pattern.search(original):
        return pattern.sub(lambda _m: entry, original, count=1)

    # Insert into [General] in alphabetical order, like Qt would.
    lines = original.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().lower() == "[general]":
            start = i
            break
    if start is None:
        return f"[General]\n{entry}\n" + original

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("["):
            end = i
            break
    pos = end
    for i in range(start + 1, end):
        name = lines[i].split("=", 1)[0].strip().lower()
        if name and name > key:
            pos = i
            break
    lines.insert(pos, entry)
    return "\n".join(lines) + ("\n" if original.endswith("\n") else "")


def write_accela_api_key(key: str, user_home_path: Path) -> tuple[bool, str]:
    """Write morrenus_api_key into ASSella's ACCELA.conf so BOTH apps share it.

    Returns (ok, message).
    """
    key = str(key or "").strip()
    if not key:
        return False, "No key to write."
    # A key must never contain a newline or '=' - that would corrupt the INI.
    if "\n" in key or "\r" in key or "=" in key:
        return False, "Key contains illegal characters."

    for path in accela_conf_candidates(user_home_path):
        try:
            if not path.exists():
                continue
            if read_ini_value(path, "morrenus_api_key") == key:
                return True, f"Key already present in {path}"

            original = path.read_text(encoding="utf-8", errors="replace")
            new_text = _build_ini_entry(original, "morrenus_api_key", key)
            if new_text == original:
                return True, f"No change needed in {path}"

            # Back up before touching another application's config.
            try:
                path.with_suffix(f".conf.decky-backup-{int(time.time())}").write_bytes(
                    path.read_bytes()
                )
            except OSError as exc:
                logger.debug("Could not back up ACCELA.conf: %s", exc)

            # Write in place to preserve permissions, hardlinks and the inode.
            with open(path, "r+", encoding="utf-8") as handle:
                handle.seek(0)
                handle.write(new_text)
                handle.truncate()
                handle.flush()
                os.fsync(handle.fileno())
            logger.info("Wrote morrenus_api_key into ACCELA config: %s", path)
            return True, f"Key saved to {path} (shared with ASSella)"
        except Exception as exc:  # noqa: BLE001 - try the next candidate
            logger.error("Failed writing ACCELA key to %s: %s", path, exc)
            continue

    try:
        primary = user_home_path / ".config" / "Tachibana Labs" / "ACCELA.conf"
        primary.parent.mkdir(parents=True, exist_ok=True)
        primary.write_text(f"[General]\nmorrenus_api_key={key}\n", encoding="utf-8")
        logger.info("Created ACCELA config at %s and saved morrenus_api_key", primary)
        return True, f"Key saved to {primary} (shared with ASSella)"
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed creating ACCELA.conf: %s", exc)
    return False, "Could not locate or create a writable ACCELA.conf."