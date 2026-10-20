"""Steam-aware SLSsteam path discovery tests."""

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uran_backend import paths


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"ok  {label}")


def run() -> None:
    original_decky_home = os.environ.get("DECKY_USER_HOME")
    original_decky_user = os.environ.get("DECKY_USER")
    original_xdg_data_home = os.environ.get("XDG_DATA_HOME")
    original_getpwnam = paths.pwd.getpwnam
    with tempfile.TemporaryDirectory() as temp:
        explicit_home = Path(temp) / "custom-user-home"
        explicit_home.mkdir()
        os.environ["DECKY_USER_HOME"] = str(explicit_home)
        os.environ.pop("DECKY_USER", None)
        check("Decky-provided user home is honored", paths.user_home() == explicit_home)

        account_home = Path(temp) / "renamed-account-home"
        account_home.mkdir()
        paths.pwd.getpwnam = lambda _name: SimpleNamespace(pw_dir=str(account_home))
        os.environ.pop("DECKY_USER_HOME", None)
        os.environ["DECKY_USER"] = "deck-user"
        check("DECKY_USER resolves through the account database", paths.user_home() == account_home)

        os.environ.pop("DECKY_USER", None)
        os.environ["XDG_DATA_HOME"] = str(Path.home() / ".local" / "share")
        check(
            "root-owned XDG data does not override the Steam user's home",
            paths.accela_base(account_home) == account_home / ".local/share/ACCELA",
        )

        custom_xdg = Path(temp) / "custom-xdg-data"
        os.environ["XDG_DATA_HOME"] = str(custom_xdg)
        check("custom absolute XDG data home is honored", paths.accela_base(account_home) == custom_xdg / "ACCELA")

    paths.pwd.getpwnam = original_getpwnam
    if original_decky_home is None:
        os.environ.pop("DECKY_USER_HOME", None)
    else:
        os.environ["DECKY_USER_HOME"] = original_decky_home
    if original_decky_user is None:
        os.environ.pop("DECKY_USER", None)
    else:
        os.environ["DECKY_USER"] = original_decky_user
    if original_xdg_data_home is None:
        os.environ.pop("XDG_DATA_HOME", None)
    else:
        os.environ["XDG_DATA_HOME"] = original_xdg_data_home

    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp)
        native_root = home / ".steam" / "steam"
        native_root.mkdir(parents=True)
        native_config = home / ".config" / "SLSsteam" / "config.yaml"
        native_config.parent.mkdir(parents=True)
        native_config.touch()

        check("native Steam selects native SLS config", paths.sls_config(home) == native_config)
        check(
            "native Steam selects only native plugin directory",
            paths.sls_plugins_dirs(home) == [native_config.parent / "plugins"],
        )
        check("native Steam root is selected", paths.steam_root(home) == native_root)

        flatpak_root = home / ".var" / "app" / "com.valvesoftware.Steam"
        flatpak_steam = flatpak_root / ".steam" / "steam"
        flatpak_steam.mkdir(parents=True)
        flatpak_config = flatpak_root / ".config" / "SLSsteam" / "config.yaml"
        flatpak_config.parent.mkdir(parents=True)
        flatpak_config.touch()

        check("Flatpak Steam takes precedence when both installs exist", paths.is_flatpak_steam(home))
        check("Flatpak Steam selects Flatpak SLS config", paths.sls_config(home) == flatpak_config)
        check(
            "Flatpak Steam selects only Flatpak plugin directory",
            paths.sls_plugins_dirs(home) == [flatpak_config.parent / "plugins"],
        )
        check("Flatpak Steam root is selected", paths.steam_root(home) == flatpak_steam)

    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp)
        stale_native_config = home / ".config" / "SLSsteam" / "config.yaml"
        stale_native_config.parent.mkdir(parents=True)
        stale_native_config.touch()
        flatpak_root = home / ".var" / "app" / "com.valvesoftware.Steam"
        (flatpak_root / "data" / "Steam").mkdir(parents=True)
        check(
            "Flatpak detection does not fall back to another install's config",
            paths.sls_config(home) is None,
        )


if __name__ == "__main__":
    run()
