"""Filesystem and application-config path discovery.

Everything that answers "where does this live?" lives here: SLSsteam's config,
Steam's library roots, ACCELA's data dir, and the INI file Uran shares with
ASSella. User locations come from Decky/account/process discovery; install
locations follow the selected Native or Flatpak Steam installation.
"""

import logging
import os
import pwd
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
    """Resolve the Steam user's home without assuming a distro-specific path."""
    explicit_home = decky_user_home or os.environ.get("DECKY_USER_HOME")
    if explicit_home:
        return Path(explicit_home)

    decky_user = os.environ.get("DECKY_USER")
    if decky_user:
        try:
            return Path(pwd.getpwnam(decky_user).pw_dir)
        except KeyError:
            logger.warning("DECKY_USER %r is not present in the system account database", decky_user)

    # Decky commonly runs as root, so its own HOME is not the Steam user's.
    # Prefer the owner of the live Steam process when Decky did not provide the
    # user explicitly.
    proc_root = Path("/proc")
    try:
        for process in sorted(proc_root.iterdir(), key=lambda item: item.name):
            if not process.name.isdigit():
                continue
            try:
                if (process / "comm").read_text(encoding="utf-8").strip() != "steam":
                    continue
                account = pwd.getpwuid(process.stat().st_uid)
                home = Path(account.pw_dir)
                if home.is_dir():
                    return home
            except (OSError, KeyError):
                continue
    except OSError:
        pass

    # If Steam is not running, use an unambiguous account with a Steam install.
    installed_homes: list[Path] = []
    try:
        for account in pwd.getpwall():
            home = Path(account.pw_dir)
            if home.is_dir() and _has_steam_install(home) and home not in installed_homes:
                installed_homes.append(home)
    except (OSError, AttributeError):
        pass
    if len(installed_homes) == 1:
        return installed_homes[0]

    return Path.home()


def _has_steam_install(home: Path) -> bool:
    flatpak_root = home / ".var" / "app" / "com.valvesoftware.Steam"
    return any(path.is_dir() for path in (
        home / ".steam" / "steam",
        home / ".local" / "share" / "Steam",
        flatpak_root / ".steam" / "steam",
        flatpak_root / "data" / "Steam",
    ))


def flatpak_steam_root(user_home_path: Path) -> Path:
    """Return Flatpak Steam's per-user data root used by Headcrab detection."""
    return user_home_path / ".var" / "app" / "com.valvesoftware.Steam"


def is_flatpak_steam(user_home_path: Path) -> bool:
    """Match Headcrab: prefer Flatpak when its Steam install directory exists."""
    flatpak_root = flatpak_steam_root(user_home_path)
    return any(
        path.is_dir()
        for path in (
            flatpak_root / ".steam" / "steam",
            flatpak_root / "data" / "Steam",
        )
    )


def sls_config(user_home_path: Path) -> Path | None:
    """Find SLSsteam config.yaml for the user's detected Steam installation."""
    if is_flatpak_steam(user_home_path):
        config_dir = flatpak_steam_root(user_home_path) / ".config" / "SLSsteam"
    else:
        config_dir = user_home_path / ".config" / "SLSsteam"
    config = config_dir / "config.yaml"
    if config.is_file() or config_dir.is_dir():
        return config
    return None


def sls_plugins_dirs(user_home_path: Path) -> list[Path]:
    """Resolve only the plugin directory belonging to the detected Steam install."""
    config = sls_config(user_home_path)
    return [config.parent / "plugins"] if config is not None else []


def sls_data_dir(user_home_path: Path) -> Path:
    """SLSsteam's per-install data directory, matching Headcrab's layout."""
    if is_flatpak_steam(user_home_path):
        return flatpak_steam_root(user_home_path) / ".local" / "share" / "SLSsteam"
    return user_home_path / ".local" / "share" / "SLSsteam"


def sls_binary_candidates(user_home_path: Path) -> list[Path]:
    """Known SLSsteam binary locations for the selected install and system package."""
    if is_flatpak_steam(user_home_path):
        flatpak_root = flatpak_steam_root(user_home_path)
        candidates = [
            sls_data_dir(user_home_path) / "SLSsteam.so",
            flatpak_root / "data" / "SLSsteam" / "SLSsteam.so",
        ]
    else:
        candidates = [sls_data_dir(user_home_path) / "SLSsteam.so"]
    # The system package location is fixed by SLSsteam's Linux packaging, not
    # by the user's home or Steam installation.
    candidates.append(Path("/usr/lib32/libSLSsteam.so"))
    return candidates


def steam_root(user_home_path: Path) -> Path | None:
    """Locate the active Steam root, preferring Flatpak exactly as Headcrab does."""
    flatpak_root = flatpak_steam_root(user_home_path)
    if is_flatpak_steam(user_home_path):
        candidates = [
            flatpak_root / ".steam" / "steam",
            flatpak_root / "data" / "Steam",
            flatpak_root / ".local" / "share" / "Steam",
        ]
    else:
        candidates = [
            user_home_path / ".steam" / "steam",
            user_home_path / ".local" / "share" / "Steam",
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
        xdg_path = Path(xdg)
        # A root-run Decky process can inherit root's XDG path while operating
        # on another user's files. Do not let that redirect ACCELA into /root.
        try:
            xdg_path.relative_to(Path.home())
            belongs_to_runtime_home = True
        except ValueError:
            belongs_to_runtime_home = False
        if not (Path.home() != user_home_path and belongs_to_runtime_home):
            return xdg_path / "ACCELA"
    return user_home_path / ".local" / "share" / "ACCELA"


def accela_data_dirs(user_home_path: Path) -> list[Path]:
    """Known ACCELA data roots for this user, with the active XDG root first."""
    flatpak_root = flatpak_steam_root(user_home_path)
    candidates = [
        accela_base(user_home_path),
        user_home_path / ".local" / "share" / "ACCELA",
        flatpak_root / "data" / "ACCELA",
        flatpak_root / ".local" / "share" / "ACCELA",
    ]
    seen: set[str] = set()
    result: list[Path] = []
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


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
    candidates.extend([
        user_home_path / ".config" / "Tachibana Labs" / "ACCELA.conf",
        flatpak_steam_root(user_home_path) / "config" / "Tachibana Labs" / "ACCELA.conf",
        user_home_path / ".var" / "app" / "com.tachibanalabs.accela" / "config" / "Tachibana Labs" / "ACCELA.conf",
        user_home_path / ".config" / "ACCELA" / "Settings.conf",
        user_home_path / ".config" / "ACCELA" / "ACCELA.conf",
        user_home_path / ".config" / "ACCELA" / "ASSella.conf",
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
