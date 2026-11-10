"""A plugin install must work on a setup that has no plugins yet.

Regression guard for the deadlock where installing plugins was gated behind a
check that itself required a plugin to already be present.
"""

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uran_backend.plugins import PluginManager


class FakeSls:
    def __init__(self):
        self.written = []

    def write(self, content):
        self.written.append(content)
        return True


def manager(home: Path, config: Path | None):
    state = {"disabled": []}
    ctx = SimpleNamespace(
        home=home,
        runtime_dir=home / "runtime",
        plugin_dir=Path(__file__).resolve().parent.parent,
        sls_config=lambda: config,
        read_setting=lambda key, default=None: list(state["disabled"]),
        write_setting=lambda key, value: state.__setitem__("disabled", list(value)),
    )
    return PluginManager(ctx, FakeSls()), ctx, state


def run():
    root = Path(__file__).resolve().parent.parent
    plugins = root / "plugins"

    # 1. No config.yaml and no plugins: installing must not be blocked.
    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp)
        mgr, _, _ = manager(home, None)
        target = home / ".config" / "SLSsteam" / "plugins"
        result = mgr.install("styx.lua")
        assert result["ok"], result
        assert (target / "styx.lua").is_file(), "plugin not written to the default dir"
        assert mgr.sls.written == [], "nothing to enable without a config"

    # 2. Config with Plugins: no: install flips it to yes and keeps other sections.
    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp)
        config = home / ".config" / "SLSsteam" / "config.yaml"
        config.parent.mkdir(parents=True)
        config.write_text("Plugins: no\nDecryptionKeys:\n  '1': abc\n", encoding="utf-8")
        mgr, ctx, state = manager(home, config)
        mgr.install_essentials()
        assert len(mgr.sls.written) == 1, mgr.sls.written
        updated = mgr.sls.written[0]
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
        mgr, ctx, state = manager(home, None)
        mgr.install("lettuce.lua")
        mgr.set_enabled("lettuce.lua", False)
        row = next(r for r in mgr.status()["plugins"] if r["filename"] == "lettuce.lua")
        assert row["installed"] and not row["enabled"], row
        assert row["status"] == "off", row
        mgr.set_enabled("lettuce.lua", True)
        row = next(r for r in mgr.status()["plugins"] if r["filename"] == "lettuce.lua")
        assert row["installed"] and row["enabled"] and row["status"] == "installed", row

    assert plugins.is_dir()
    print("all plugin manager checks pass")


if __name__ == "__main__":
    run()
