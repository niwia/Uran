"""Plugin actions must respect SLS config ownership and readiness.

Installing may enable Plugins in an existing valid config, but Uran must not
create SLSsteam's config.yaml on behalf of SLSsteam.
"""

import sys
import threading
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uran_backend.plugins import PluginManager
from uran_backend.sls_config import SlsConfig


def manager(home: Path, config: Path | None):
    state = {"disabled": []}
    ctx = SimpleNamespace(
        home=home,
        runtime_dir=home / "runtime",
        plugin_dir=Path(__file__).resolve().parent.parent,
        sls_config=lambda: config,
        sls_lock=threading.RLock(),
        read_setting=lambda key, default=None: list(state["disabled"]),
        write_setting=lambda key, value: state.__setitem__("disabled", list(value)),
    )
    return PluginManager(ctx, SlsConfig(ctx)), ctx, state


def run():
    root = Path(__file__).resolve().parent.parent
    plugins = root / "plugins"

    # 1. No config.yaml: install fails before creating plugin/config files.
    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp)
        mgr, _, _ = manager(home, None)
        target = home / ".config" / "SLSsteam" / "plugins"
        try:
            mgr.install("styx.lua")
        except RuntimeError:
            pass
        else:
            raise AssertionError("install should require SLSsteam config.yaml")
        assert not (target / "styx.lua").exists(), "plugin was written without config"

    # 2. Config with Plugins: no: install flips it to yes and keeps other sections.
    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp)
        config = home / ".config" / "SLSsteam" / "config.yaml"
        config.parent.mkdir(parents=True)
        config.write_text("Plugins: no\nDecryptionKeys:\n  '1': abc\n", encoding="utf-8")
        mgr, ctx, state = manager(home, config)
        mgr.install_essentials()
        updated = config.read_text(encoding="utf-8")
        assert "Plugins: yes" in updated, updated
        assert updated.count("DecryptionKeys:") == 1, "section duplicated"
        installed = sorted(p.name for p in (config.parent / "plugins").glob("*.lua"))
        assert installed == ["lobster.lua", "spacebunny.lua", "styx.lua"], installed
        assert state["disabled"] == [], "install must clear the disabled flag"

    # 3. An unknown or traversal filename never reaches the filesystem.
    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp)
        mgr, _, _ = manager(home, None)
        for bad in ("../../etc/passwd", "katamari.lua", "spacebunny.lua.bak"):
            try:
                mgr.remove(bad)
            except ValueError:
                continue
            raise AssertionError(f"{bad} was accepted")
        assert not any((home / ".config").rglob("*.removed.bak"))

    # 4. A disabled plugin still reports installed/enabled truthfully.
    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp)
        config = home / ".config" / "SLSsteam" / "config.yaml"
        config.parent.mkdir(parents=True)
        config.write_text("Plugins: yes\n", encoding="utf-8")
        mgr, ctx, state = manager(home, config)
        mgr.install("lettuce.lua")
        mgr.set_enabled("lettuce.lua", False)
        row = next(r for r in mgr.status()["plugins"] if r["filename"] == "lettuce.lua")
        assert row["installed"] and not row["enabled"], row
        assert row["status"] == "off", row
        mgr.set_enabled("lettuce.lua", True)
        row = next(r for r in mgr.status()["plugins"] if r["filename"] == "lettuce.lua")
        assert row["installed"] and row["enabled"] and row["status"] == "installed", row

    # 5. Empty-policy manifest: no required: true entries only suggests deployable plugins.
    from assella_shared.plugin_manifest import Manifest

    empty_policy_data = {
        "manifest_version": 2,
        "serial": 20261110000000,
        "plugins": {
            "styx.lua": {
                "name": "Styx",
                "sha256": "3527b1525b2a7850ae9dfa7654bc243587b568b340e32e62d819eacca9fca2f7",
                "required": False,  # no plugin has required: True
                "deployable": True,
            },
            "custom.lua": {
                "name": "Custom",
                "sha256": "0" * 64,
                "required": False,
                "deployable": False,
            },
        },
    }
    m = Manifest(empty_policy_data, "cache")
    # spacebunny and lobster are not in this manifest, so required_plugins must only return styx.lua
    req = m.required_plugins()
    assert req == ["styx.lua"], f"Expected ['styx.lua'], got {req}"

    # The UI and destructive actions must honor the same fallback-required set.
    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp)
        mgr, _, _ = manager(home, None)
        mgr.store = SimpleNamespace(load_local=lambda: m, load=lambda: m)
        styx_row = next(row for row in mgr.status()["plugins"] if row["filename"] == "styx.lua")
        assert styx_row["required"], styx_row
        for action in (lambda: mgr.remove("styx.lua"), lambda: mgr.set_enabled("styx.lua", False)):
            try:
                action()
            except ValueError as exc:
                assert "Required plugins" in str(exc), exc
            else:
                raise AssertionError("fallback-required plugin should be protected")

    assert plugins.is_dir()
    print("all plugin manager checks pass")


if __name__ == "__main__":
    run()
