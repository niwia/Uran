#!/usr/bin/env python3
"""Health checks: pure helpers plus the service behind stub collaborators.

Dependency-free like the rest of the suite: no network, no Decky.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uran_backend.health import (  # noqa: E402
    Health,
    compare_sls_version,
    local_config_issues,
    top_level_keys,
)


class _Settings:
    def __init__(self, path):
        self.path = path


class _StubCtx:
    def __init__(self, home):
        self.home = Path(home)


class _StubSls:
    def __init__(self, config_path=None, content=""):
        self.config_path = Path(config_path) if config_path else None
        self._content = content

    def read(self):
        return self._content


def check(name, cond):
    print(("ok  " if cond else "FAIL") + " " + name)
    if not cond:
        raise SystemExit(f"failed: {name}")


def main():
    # -- version comparison ------------------------------------------------
    check("outdated when mtime older than release",
          compare_sls_version(1000.0, 2000.0) == "outdated")
    check("up to date within tolerance",
          compare_sls_version(2000.0 - 60.0, 2000.0) == "up_to_date")
    check("up to date when newer", compare_sls_version(3000.0, 2000.0) == "up_to_date")

    # -- key helpers --------------------------------------------------------
    text = "Plugins: yes\nAdditionalApps:\n  - 480 # Spacewar\n"
    check("top_level_keys finds sections",
          top_level_keys(text) == {"Plugins", "AdditionalApps"})
    check("clean config has no local issues", local_config_issues(text) == [])

    messy = "Plugins: yes   \nPlugins: no\n  - 480   # Spacewar\n"
    issues = local_config_issues(messy)
    check("trailing whitespace flagged",
          any("trailing whitespace" in i for i in issues))
    check("duplicate top-level key flagged",
          any("Duplicate top-level key: Plugins" in i for i in issues))
    check("extra spaces before comment flagged",
          any("extra spaces before inline comment" in i for i in issues))

    # -- plugins check behind stubs -----------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        cfg_dir = home / ".config" / "SLSsteam"
        plug_dir = cfg_dir / "plugins"
        plug_dir.mkdir(parents=True)
        cfg = cfg_dir / "config.yaml"
        cfg.write_text("Plugins: yes\nAdditionalApps:\n", encoding="utf-8")
        (plug_dir / "download.lua").write_text("-- stub", encoding="utf-8")
        (plug_dir / "notes.txt").write_text("not a plugin", encoding="utf-8")

        health = Health(_StubCtx(home), _StubSls(cfg, cfg.read_text()))
        res = health.check_plugins()
        check("lists actual lua files only",
              res["plugins"] == ["download.lua"])
        check("Plugins flag read", res["plugins_enabled"] is True)

        (plug_dir / "spliced-tickets.lua").write_text("-- stub", encoding="utf-8")
        check("lists both plugins sorted",
              health.check_plugins()["plugins"] == [
                  "download.lua", "spliced-tickets.lua",
              ])

    # -- config check offline -------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        cfg = home / "config.yaml"
        cfg.write_text("Plugins: yes\n", encoding="utf-8")
        res = Health(_StubCtx(home), _StubSls(cfg)).check_config(online=False)
        check("healthy config offline",
              res["ok"] and res["needs_attention"] is False)

        missing = Health(_StubCtx(home), _StubSls(home / "nope.yaml")).check_config(online=False)
        check("missing config reports not-found", missing["ok"] is False)

    # -- template-exempt keys ------------------------------------------------
    from uran_backend.health import TEMPLATE_EXEMPT_KEYS  # noqa: E402
    check("plugin keys exempt from template diff",
          {"AdditionalDepots", "DecryptionKeys"} <= set(TEMPLATE_EXEMPT_KEYS))

    # -- SLS version with no binary -------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        res = Health(_StubCtx(Path(tmp)), _StubSls()).check_sls_version()
        check("no binary -> no_local", res["status"] == "no_local")

    print("\nall health checks pass")


if __name__ == "__main__":
    main()
