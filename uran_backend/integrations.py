"""Per-game integrations: SLSonline, NetSock and the EOS proxy.

  SLSonline  -> FakeAppIds section (maps the game to Spacewar 480)
  NetSock    -> LaunchOptions section (env LD_AUDIT=...)
  EOS Proxy  -> filesystem swap of EOSSDK-Win64-Shipping.dll/.yes

Semantics follow ASSella so both tools operate on identical config.
"""

import hashlib
import logging
import os
import re
import shutil
from pathlib import Path

from .context import Context
from .http import requests
from .sls_config import (
    SlsConfig,
    ensure_plugins_enabled,
    parse_list_section,
    parse_key_section,
    remove_in_memory,
    sanitize_comment,
    sanitize_id,
    section_bounds,
    signal_api,
    upsert_in_memory,
)
from .steammeta import SteamMeta, sls_config_dir

logger = logging.getLogger("Uran")

_EOS_DLL = "eossdk-win64-shipping.dll"
_EOS_YES = "eossdk-win64-shipping.yes"
_EOS_PROXY_URL = (
    "https://github.com/yesyes0649/eos-proxy/releases/download/v1.0.0/"
    "EOSSDK-Win64-Shipping.dll"
)
_NETSOCK_URL = (
    "https://github.com/yesyes0649/steamnetsock-patch/releases/download/latest/fix.so"
)
_EOS_PRUNE_DIRS = {
    ".depotdownloader", "__pycache__", "content", "paks", "pak", "assets",
    "sound", "sounds", "audio", "music", "media", "video", "videos", "movies",
    "textures", "cache", "saves", "screenshots", "shadercache",
    "streamingassets", "node_modules", ".git",
}


class Integrations:
    """Toggles that write into config.yaml or swap files on disk."""

    def __init__(self, ctx: Context, sls: SlsConfig, steam: SteamMeta):
        self.ctx = ctx
        self.sls = sls
        self.steam = steam

    # -- SLSonline (FakeAppIds) ----------------------------------------------
    def get_fake_appid(self, app_id: str) -> str:
        """Read the FakeAppIds target for an AppID ("" when not mapped)."""
        cfg = self.ctx.sls_config()
        if not cfg or not cfg.exists():
            return ""
        try:
            content = cfg.read_text(encoding="utf-8", errors="replace")
            bounds = section_bounds(content, "FakeAppIds")
            if not bounds:
                return ""
            match = re.search(
                rf"^[ \t]*['\"]?{re.escape(app_id)}['\"]?[ \t]*:[ \t]*(\d+)",
                content[bounds[1]:bounds[2]],
                re.MULTILINE,
            )
            return match.group(1) if match else ""
        except Exception as exc:  # noqa: BLE001
            logger.debug("get_fake_appid(%s) failed: %s", app_id, exc)
            return ""

    def set_fake_appid(self, app_id: str, fake_appid: str, game_name: str = "") -> dict:
        """Add/update/remove a FakeAppIds entry (SLSonline toggle).

        Comment suffix matches ASSella: "<name> -> Spacewar" for 480, else
        "<name> -> SLSonline". Removal when fake_appid is "".
        """
        if self.ctx.sls_config() is None:
            return {"ok": False, "error": "SLSsteam config not found"}
        app_id = sanitize_id(app_id)
        if not app_id:
            return {"ok": False, "error": "Invalid AppID"}

        name = sanitize_comment(game_name)
        with self.sls.edit() as editor:
            if fake_appid:
                target = sanitize_id(fake_appid)
                if not target:
                    return {"ok": False, "error": "Invalid fake AppID"}
                suffix = "Spacewar" if target == "480" else "SLSonline"
                editor.add_fake_app_id(app_id, target, comment=f"{name} -> {suffix}" if name else "")
            else:
                editor.remove_fake_app_id(app_id)

        if not editor.committed_successfully:
            return {"ok": False, "error": "Failed to write config"}
        return {"ok": True, "fake_appid": fake_appid}

    def global_slsonline_enabled(self) -> bool:
        """True if `0: 480` is mapped, applying SLSonline to every game."""
        return self.get_fake_appid("0") == "480"

    def set_global_slsonline(self, enabled: bool) -> dict:
        result = (
            self.set_fake_appid("0", "480", game_name="Global")
            if enabled
            else self.set_fake_appid("0", "")
        )
        signal_api("RELOAD", logger)
        return {"ok": result.get("ok", False), "enabled": enabled}

    def list_fake_app_ids(self) -> dict:
        cfg = self.ctx.sls_config()
        if not cfg or not cfg.exists():
            return {"ok": True, "ids": []}
        ids: list[str] = []
        in_section = False
        for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped == "FakeAppIds:":
                in_section = True
                continue
            if not in_section:
                continue
            if not line.startswith((" ", "\t")):
                break
            if ":" in stripped and not stripped.startswith("#"):
                name = stripped.split(":", 1)[0].strip()
                if name.isdigit():
                    ids.append(name)
        return {"ok": True, "ids": ids}

    def add_fake_app_id(self, app_id: str) -> dict:
        with self.sls.edit() as editor:
            inserted = editor.add_fake_app_id(app_id, "480")
        return {
            "ok": editor.committed_successfully,
            "message": "Updated" if inserted else "Already up to date",
        }

    def remove_fake_app_id(self, app_id: str) -> dict:
        with self.sls.edit() as editor:
            removed = editor.apply(
                *remove_in_memory(editor.content, "FakeAppIds", app_id, is_list=False)
            )
        return {
            "ok": editor.committed_successfully,
            "message": "Removed" if removed else "Not found",
        }

    # -- NetSock (LaunchOptions) ---------------------------------------------
    def _netsock_tools_dir(self) -> Path:
        return sls_config_dir(self.ctx) / "tools" / "netsock"

    def _find_existing_netsock_so(self) -> Path | None:
        candidates = [
            self._netsock_tools_dir() / "netsock.so",
            self.ctx.home / ".config/SLSsteam/tools/netsock/netsock.so",
            self.ctx.home / ".local/share/SLSsteam/tools/netsock/netsock.so",
            self.ctx.home / ".var/app/com.valvesoftware.Steam/.config/SLSsteam/tools/netsock/netsock.so",
        ]
        for candidate in candidates:
            try:
                if candidate.is_file() and candidate.stat().st_size > 0:
                    return candidate
            except OSError:
                continue
        return None

    def _netsock_launch_path(self) -> str:
        """Path as it must appear in launch options (Steam runtime view)."""
        xdg = os.environ.get("XDG_CONFIG_HOME", "")
        if xdg and Path(xdg).is_absolute():
            return str(Path(xdg) / "SLSsteam" / "tools" / "netsock" / "netsock.so")
        return str(self.ctx.home / ".config" / "SLSsteam" / "tools" / "netsock" / "netsock.so")

    def ensure_netsock_binary(self) -> bool:
        """Ensure netsock.so exists, downloading fix.so if missing."""
        target_dir = self._netsock_tools_dir()
        target_so = target_dir / "netsock.so"
        existing = self._find_existing_netsock_so()
        if existing:
            if existing != target_so:
                try:
                    target_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(existing, target_so)
                    os.chmod(target_so, 0o755)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Could not copy netsock.so: %s", exc)
            return True
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            resp = requests.get(_NETSOCK_URL, timeout=30)
            if not resp.ok or not resp.content:
                return False
            target_so.write_bytes(resp.content)
            os.chmod(target_so, 0o755)
            # Mirror to the native config dir so Flatpak/host both resolve it.
            native = self.ctx.home / ".config" / "SLSsteam" / "tools" / "netsock" / "netsock.so"
            if native != target_so and not native.exists():
                try:
                    native.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target_so, native)
                    os.chmod(native, 0o755)
                except Exception:  # noqa: BLE001
                    pass
            logger.info("Downloaded netsock.so (%d bytes)", len(resp.content))
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to download netsock.so: %s", exc)
            return False

    def get_launch_option(self, app_id: str) -> str:
        cfg = self.ctx.sls_config()
        if not cfg or not cfg.exists():
            return ""
        try:
            content = cfg.read_text(encoding="utf-8", errors="replace")
            bounds = section_bounds(content, "LaunchOptions")
            if not bounds:
                return ""
            match = re.search(
                rf"^[ \t]*['\"]?{re.escape(app_id)}['\"]?[ \t]*:[ \t]*(.+)$",
                content[bounds[1]:bounds[2]],
                re.MULTILINE,
            )
            return match.group(1).strip() if match else ""
        except Exception:  # noqa: BLE001
            return ""

    def netsock_active(self, app_id: str) -> bool:
        option = self.get_launch_option(app_id)
        return bool(option and "netsock.so" in option)

    def set_netsock(self, app_id: str, enabled: bool) -> dict:
        """Toggle the NetSock LaunchOptions entry."""
        if self.ctx.sls_config() is None:
            return {"ok": False, "error": "SLSsteam config not found"}
        app_id = sanitize_id(app_id)
        if not app_id:
            return {"ok": False, "error": "Invalid AppID"}

        with self.sls.edit() as editor:
            if enabled:
                if not self.ensure_netsock_binary():
                    return {"ok": False, "error": "Could not obtain netsock.so"}
                # Same shape ASSella writes: quoted, with escaped inner quotes.
                cmd = f'"env LD_AUDIT=\\"{self._netsock_launch_path()}\\" %command%"'
                editor.apply(*upsert_in_memory(editor.content, "LaunchOptions", app_id, value=cmd))
            else:
                editor.remove_launch_option(app_id)

        if not editor.committed_successfully:
            return {"ok": False, "error": "Failed to write config"}
        return {"ok": True, "enabled": enabled}

    # -- EOS Proxy (filesystem DLL swap) --------------------------------------
    def _eos_proxy_dll(self) -> Path | None:
        """Locate (or download) the EOS proxy DLL."""
        deps = self.ctx.accela_base() / "deps" / "EOSSDK-Win64-Shipping.dll"
        if deps.is_file():
            return deps
        try:
            deps.parent.mkdir(parents=True, exist_ok=True)
            resp = requests.get(_EOS_PROXY_URL, timeout=30)
            if resp.ok and resp.content:
                deps.write_bytes(resp.content)
                return deps
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch EOS proxy DLL: %s", exc)
        return None

    def _find_eos_dlls(self, game_dir: Path, max_depth: int = 4) -> list[Path]:
        found: list[Path] = []
        if not game_dir.is_dir():
            return found
        base_depth = len(game_dir.parts)
        for root, dirs, files in os.walk(game_dir):
            if len(Path(root).parts) - base_depth >= max_depth:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d.lower() not in _EOS_PRUNE_DIRS and not d.startswith(".")]
            for name in files:
                if name.lower() in (_EOS_DLL, _EOS_YES):
                    found.append(Path(root) / name)
        return found

    def eos_status(self, game_dir: Path) -> str:
        """none | inactive | stale | active — mirrors ASSella's EOSDetector."""
        dlls = self._find_eos_dlls(game_dir)
        if not dlls:
            return "none"
        by_dir: dict[Path, dict[str, Path]] = {}
        for path in dlls:
            slot = "yes" if path.suffix.lower() == ".yes" else "dll"
            by_dir.setdefault(path.parent, {})[slot] = path
        if not any("yes" in v for v in by_dir.values()):
            return "inactive" if any("dll" in v for v in by_dir.values()) else "none"

        proxy = self._eos_proxy_dll()
        proxy_hash = _file_sha256(proxy) if proxy else ""
        for slots in by_dir.values():
            if "yes" in slots:
                dll = slots.get("dll")
                if not dll or not dll.exists():
                    return "stale"
                if proxy_hash and _file_sha256(dll) != proxy_hash:
                    return "stale"
        return "active"

    def apply_eos_proxy(self, game_dir: Path) -> bool:
        proxy = self._eos_proxy_dll()
        if not proxy or not game_dir.is_dir():
            return False
        applied = False
        try:
            for root, _dirs, files in os.walk(game_dir):
                if ".DepotDownloader" in Path(root).parts:
                    continue
                dll_src = None
                yes_present = None
                for name in files:
                    lowered = name.lower()
                    if lowered == _EOS_DLL:
                        dll_src = Path(root) / name
                    elif lowered == _EOS_YES:
                        yes_present = Path(root) / name
                dll_target = Path(root) / "EOSSDK-Win64-Shipping.dll"
                yes_target = Path(root) / "EOSSDK-Win64-Shipping.yes"
                if dll_src:
                    if yes_present and yes_present.exists():
                        try:
                            yes_present.unlink()
                        except OSError:
                            pass
                    dll_src.rename(yes_target)
                    shutil.copy2(proxy, dll_target)
                    applied = True
                elif yes_present and not dll_src:
                    shutil.copy2(proxy, dll_target)
                    applied = True
        except Exception as exc:  # noqa: BLE001
            logger.error("apply_eos_proxy failed: %s", exc, exc_info=True)
            return False
        return applied

    def remove_eos_proxy(self, game_dir: Path) -> bool:
        if not game_dir.is_dir():
            return False
        removed = False
        try:
            for root, _dirs, files in os.walk(game_dir):
                if ".DepotDownloader" in Path(root).parts:
                    continue
                yes_present = None
                dll_present = None
                for name in files:
                    lowered = name.lower()
                    if lowered == _EOS_YES:
                        yes_present = Path(root) / name
                    elif lowered == _EOS_DLL:
                        dll_present = Path(root) / name
                if yes_present:
                    if dll_present and dll_present.exists():
                        try:
                            dll_present.unlink()
                        except OSError:
                            pass
                    yes_present.rename(Path(root) / "EOSSDK-Win64-Shipping.dll")
                    removed = True
        except Exception as exc:  # noqa: BLE001
            logger.error("remove_eos_proxy failed: %s", exc, exc_info=True)
            return False
        return removed

    def set_eos_proxy(self, app_id: str, enabled: bool) -> dict:
        app_id = sanitize_id(app_id)
        if not app_id:
            return {"ok": False, "error": "Invalid AppID"}
        install = self.steam.install_info(app_id)
        game_dir = Path(install.get("install_path") or "")
        if not install.get("installed") or not game_dir.is_dir():
            return {"ok": False, "error": "Game is not installed locally"}
        try:
            if enabled:
                if not self.apply_eos_proxy(game_dir):
                    return {
                        "ok": False,
                        "error": "Could not apply the EOS proxy (no EOS binaries found?)",
                    }
            elif not self.remove_eos_proxy(game_dir):
                return {"ok": False, "error": "No EOS proxy was applied"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "status": self.eos_status(game_dir)}


def _file_sha256(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:  # noqa: BLE001
        return ""