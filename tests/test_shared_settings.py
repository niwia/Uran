"""One settings file per machine: Uran, Epsilon and ASSella must agree.

Uran runs inside Decky, Epsilon runs standalone (or as Decky's loopback) and
ASSella edits the same JSON from Settings -> Companions. Before this, each side
resolved a different file, so a toggle flipped in one tool was invisible to the
other and the AT0-M console token shown in the UI could be one the bridge
rejects. These checks pin the resolution, the layered read and the mirrored
write, plus the "newest token wins" rule used by ASSella's rotation.
"""

import json
import os
import shutil
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uran_backend import paths
from uran_backend.console_api import ensure_console_token
from uran_backend.context import build_context
from uran_backend.settings import Settings

ROOT = Path("/tmp/uran-shared-settings-test")
fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"FAIL {label}\n     got  {got!r}\n     want {want!r}")
    else:
        print(f"ok  {label}")


def write(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def fresh(name: str) -> Path:
    home = ROOT / name
    shutil.rmtree(home, ignore_errors=True)
    home.mkdir(parents=True)
    return home


class FakeDecky(types.ModuleType):
    def __init__(self, **attrs):
        super().__init__("decky_plugin")
        for key, value in attrs.items():
            setattr(self, key, value)


def test_no_decky_keeps_epsilon_own_file():
    home = fresh("no-decky")
    resolved = paths.companion_settings_paths(home)
    check(
        "no Decky: only Epsilon's own file",
        resolved,
        [home / ".config" / "assella-decky" / "settings.json"],
    )


def test_uran_installed_is_canonical():
    home = fresh("decky")
    plugin = home / "homebrew" / "plugins" / "Uran"
    write(plugin / "plugin.json", {"name": "Uran", "version": "0.8.1"})

    resolved = paths.companion_settings_paths(home)
    check(
        "Decky: Uran's file first, Epsilon's file as the mirror",
        resolved,
        [
            home / "homebrew" / "settings" / "Uran" / "settings.json",
            home / ".config" / "assella-decky" / "settings.json",
        ],
    )


def test_renamed_plugin_folder_is_found():
    home = fresh("decky-renamed")
    write(home / "homebrew" / "plugins" / "com.example.uran" / "plugin.json", {"name": "Uran"})
    resolved = paths.companion_settings_paths(home)
    check(
        "Decky: a store install with another folder name still resolves",
        resolved[0],
        home / "homebrew" / "settings" / "com.example.uran" / "settings.json",
    )


def test_layered_read_newest_wins():
    home = fresh("layered")
    write(home / "homebrew" / "plugins" / "Uran" / "plugin.json", {"name": "Uran"})
    canonical, mirror = paths.companion_settings_paths(home)
    write(canonical, {"hubcap_gateway": "proxy", "notification_mode": "steam"})
    write(mirror, {"hubcap_gateway": "direct", "add_delisted_dlcs": False})

    # The other copy was saved last, so its value is the current intent.
    os.utime(canonical, (1000, 1000))
    os.utime(mirror, (2000, 2000))

    settings = Settings(canonical.parent, mirrors=[mirror])
    check("layered: the most recently saved file wins", settings.get("hubcap_gateway"), "direct")
    check(
        "layered: newest file's own keys apply",
        settings.get("add_delisted_dlcs"),
        False,
    )
    check(
        "layered: a key only the older copy has still applies",
        settings.get("notification_mode"),
        "steam",
    )


def test_upgrade_keeps_the_existing_token():
    """A machine that already had Epsilon: the token lives in the old file."""
    home = fresh("upgrade")
    write(home / "homebrew" / "plugins" / "Uran" / "plugin.json", {"name": "Uran"})
    canonical, mirror = paths.companion_settings_paths(home)
    old_token = "at0m_" + "a" * 64
    write(mirror, {"epsilon_console_token": old_token})

    settings = Settings(canonical.parent, mirrors=[mirror])
    check("upgrade: the existing token is adopted", ensure_console_token(settings), old_token)
    check(
        "upgrade: the canonical file now holds the same token",
        json.loads(canonical.read_text()).get("epsilon_console_token"),
        old_token,
    )
    check(
        "upgrade: the old copy keeps it too",
        json.loads(mirror.read_text()).get("epsilon_console_token"),
        old_token,
    )
    check("upgrade: no second token was minted", ensure_console_token(settings), old_token)


def test_newest_token_wins_across_files():
    """ASSella rotates the token by rewriting one file; the bridge must follow."""
    home = fresh("rotation")
    write(home / "homebrew" / "plugins" / "Uran" / "plugin.json", {"name": "Uran"})
    canonical, mirror = paths.companion_settings_paths(home)
    write(canonical, {"epsilon_console_token": "at0m_shared"})
    write(mirror, {"epsilon_console_token": "at0m_shared"})

    # Rotated in the canonical file (ASSella's normal path): accepted.
    write(canonical, {"epsilon_console_token": "at0m_rotated_canonical"})
    os.utime(mirror, (1000, 1000))
    os.utime(canonical, (2000, 2000))
    settings = Settings(canonical.parent, mirrors=[mirror])
    check("rotation: canonical file wins when newest", ensure_console_token(settings), "at0m_rotated_canonical")

    # Rotated in the older copy by a build that has not been updated yet.
    write(mirror, {"epsilon_console_token": "at0m_rotated_legacy"})
    os.utime(canonical, (1000, 1000))
    os.utime(mirror, (3000, 3000))
    settings = Settings(canonical.parent, mirrors=[mirror])
    check("rotation: the older build's rotation still takes effect", ensure_console_token(settings), "at0m_rotated_legacy")

    # A stale copy must never win once copies have diverged again.
    write(canonical, {"epsilon_console_token": "at0m_canonical_fresh"})
    write(mirror, {"epsilon_console_token": "at0m_legacy_stale"})
    os.utime(mirror, (500, 500))
    os.utime(canonical, (4000, 4000))
    settings = Settings(canonical.parent, mirrors=[mirror])
    check("rotation: a stale copy does not override a newer one", ensure_console_token(settings), "at0m_canonical_fresh")


def test_writes_mirror_into_existing_files():
    home = fresh("mirror-write")
    write(home / "homebrew" / "plugins" / "Uran" / "plugin.json", {"name": "Uran"})
    canonical, mirror = paths.companion_settings_paths(home)
    write(canonical, {"hubcap_gateway": "auto"})
    write(mirror, {"manifest_api_key": "smm_keep_me", "hubcap_gateway": "direct"})
    # The user last changed the gateway in the older tool: that choice stands.
    os.utime(canonical, (1000, 1000))
    os.utime(mirror, (2000, 2000))

    settings = Settings(canonical.parent, mirrors=[mirror])
    settings.set("notification_mode", "desktop")

    check("mirror write: canonical updated", json.loads(canonical.read_text())["notification_mode"], "desktop")
    mirror_data = json.loads(mirror.read_text())
    check("mirror write: other copy updated", mirror_data["notification_mode"], "desktop")
    check("mirror write: unrelated key kept", mirror_data["manifest_api_key"], "smm_keep_me")
    check(
        "mirror write: the newer tool's value is not reverted",
        mirror_data["hubcap_gateway"],
        "direct",
    )
    check(
        "mirror write: both files now agree",
        json.loads(canonical.read_text())["hubcap_gateway"],
        "direct",
    )


def test_missing_copy_is_not_created():
    home = fresh("no-create")
    write(home / "homebrew" / "plugins" / "Uran" / "plugin.json", {"name": "Uran"})
    canonical, mirror = paths.companion_settings_paths(home)

    settings = Settings(canonical.parent, mirrors=[mirror])
    settings.set("fetch_dlcs_on_inject", False)

    check("no-create: canonical written", canonical.exists(), True)
    check("no-create: unused legacy file not created", mirror.exists(), False)


def test_unwritable_canonical_falls_back_to_mirror():
    """Decky's settings dir can be root-owned on a SteamOS install."""
    home = fresh("readonly")
    write(home / "homebrew" / "plugins" / "Uran" / "plugin.json", {"name": "Uran"})
    canonical, mirror = paths.companion_settings_paths(home)
    canonical.parent.mkdir(parents=True)
    canonical.parent.chmod(0o500)
    try:
        settings = Settings(canonical.parent, mirrors=[mirror])
        token = ensure_console_token(settings)
        check("read-only canonical: a token is still produced", token.startswith("at0m_"), True)
        check(
            "read-only canonical: the token is persisted in the user's own file",
            json.loads(mirror.read_text()).get("epsilon_console_token"),
            token,
        )
        check("read-only canonical: token reusable", ensure_console_token(settings), token)
    finally:
        canonical.parent.chmod(0o700)


def test_context_uses_shared_file_but_keeps_caches():
    home = fresh("context")
    write(home / "homebrew" / "plugins" / "Uran" / "plugin.json", {"name": "Uran"})
    decky = FakeDecky(
        DECKY_USER_HOME=str(home),
        DECKY_PLUGIN_DIR=str(home / "homebrew" / "plugins" / "Uran"),
        # No DECKY_PLUGIN_SETTINGS_DIR: this is the standalone/Epsilon shape.
    )
    ctx = build_context(decky)
    check(
        "context: settings resolve to Uran's file",
        str(ctx.settings.path),
        str(home / "homebrew" / "settings" / "Uran" / "settings.json"),
    )
    check(
        "context: manifest cache stays in the stable state dir",
        str(ctx.runtime_dir),
        str(home / ".config" / "assella-decky"),
    )
    check(
        "context: the old file is still read",
        [str(path) for path in ctx.settings.mirror_paths],
        [str(home / ".config" / "assella-decky" / "settings.json")],
    )


def test_explicit_decky_settings_dir_wins():
    home = fresh("explicit")
    write(home / "homebrew" / "plugins" / "Uran" / "plugin.json", {"name": "Uran"})
    explicit = home / "custom-settings"
    decky = FakeDecky(
        DECKY_USER_HOME=str(home),
        DECKY_PLUGIN_SETTINGS_DIR=str(explicit),
    )
    ctx = build_context(decky)
    check("explicit dir: Decky's answer is canonical", str(ctx.settings.path), str(explicit / "settings.json"))
    check(
        "explicit dir: both discovered files remain readable",
        [Path(path).name for path in ctx.settings.mirror_paths],
        ["settings.json", "settings.json"],
    )


test_no_decky_keeps_epsilon_own_file()
test_uran_installed_is_canonical()
test_renamed_plugin_folder_is_found()
test_layered_read_newest_wins()
test_upgrade_keeps_the_existing_token()
test_newest_token_wins_across_files()
test_writes_mirror_into_existing_files()
test_missing_copy_is_not_created()
test_unwritable_canonical_falls_back_to_mirror()
test_context_uses_shared_file_but_keeps_caches()
test_explicit_decky_settings_dir_wins()

print()
if fails:
    print("\n".join(fails))
    sys.exit(1)
print("all shared settings checks pass")
