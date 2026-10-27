"""Offline tests for SLSsteam plugin verification and deployment."""

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uran_backend import plugin_deploy


class FakeResponse:
    status = 200

    def __init__(self, content):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, limit):
        return self.content[:limit]


class FakeSls:
    def __init__(self, config):
        self.config = config

    def read(self):
        return self.config.read_text(encoding="utf-8")

    def write(self, content):
        self.config.write_text(content, encoding="utf-8")
        return True


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print(f"ok  {label}")


def run():
    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp)
        config = home / ".config/SLSsteam/config.yaml"
        plugins = config.parent / "plugins"
        config.parent.mkdir(parents=True)
        config.write_text("Plugins: no\nSmartTickets: 0x0\n", encoding="utf-8")
        plugins.mkdir()
        ctx = SimpleNamespace(
            home=home,
            runtime_dir=home / "runtime",
            sls_config=lambda: config,
            _settings={},
            read_setting=lambda key, default=None: ctx._settings.get(key, default),
            write_setting=lambda key, value: ctx._settings.update({key: value}),
        )
        sls = FakeSls(config)
        content = {
            "download.lua": b"-- standard plugin\n",
            "spacebunny1.5.lua": b"-- spacebunny plugin\n",
            "spliced-tickets.lua": b"-- spliced plugin\n",
        }
        manifest = {
            "plugins": {
                name: {"sha256": hashlib.sha256(data).hexdigest(), "version": "1.0.0"}
                for name, data in content.items()
            }
        }

        def fake_urlopen(request, timeout):
            url = request.full_url
            if url.endswith("plugins_manifest.json"):
                return FakeResponse(json.dumps(manifest).encode())
            name = url.rsplit("/", 1)[-1]
            return FakeResponse(content[name])

        plugin_deploy.urllib.request.urlopen = fake_urlopen
        deployer = plugin_deploy.PluginDeployer(ctx, sls)

        status = deployer.status()
        check("all plugins initially missing", all(
            item["state"] == "missing" for item in status["plugins"].values()
        ))

        check("disable plugin succeeds", deployer.disable_plugin("hubcap.lua")["ok"])
        check("disabled state is reported", deployer.status()["plugins"]["hubcap.lua"]["user_disabled"])
        check("enable plugin succeeds", deployer.enable_plugin("hubcap.lua")["ok"])
        check("enabled state is reported", not deployer.status()["plugins"]["hubcap.lua"]["user_disabled"])

        result = deployer.deploy("download.lua")
        check("standard deploy succeeds", result["ok"])
        check("plugins toggle enabled", "Plugins: yes" in sls.read())
        check("standard is active", deployer.status()["plugins"]["download.lua"]["active"])

        (plugins / ".hidden.lua").write_text("-- hidden", encoding="utf-8")
        check("hidden Lua files are not active interceptors", deployer._active_interceptor([plugins]) == "download.lua")
        (plugins / ".hidden.lua").unlink()

        manifest["plugins"] = {}
        unverified = deployer.status()["plugins"]["download.lua"]
        check("missing manifest hash does not count as verified", unverified["state"] == "unknown" and unverified["active"])
        manifest["plugins"] = {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "version": "1.0.0"}
            for name, data in content.items()
        }

        result = deployer.deploy("spacebunny1.5.lua")
        check("switch to SpaceBunny succeeds", result["ok"])
        check("old interceptor archived", (plugins / "download.lua.bak").read_bytes() == content["download.lua"])
        check("only selected interceptor is active", not (plugins / "download.lua").exists() and (plugins / "spacebunny1.5.lua").is_file())

        result = deployer.deploy("spliced-tickets.lua")
        check("Spliced Tickets deploy succeeds", result["ok"])
        check("SmartTickets enabled", "SmartTickets: 0x1" in sls.read())
        check("Spliced coexists with interceptor", (plugins / "spacebunny1.5.lua").is_file() and (plugins / "spliced-tickets.lua").is_file())

        check("unknown filenames rejected", not deployer.deploy("../other.lua")["ok"])

        # Companion preservation tests (Hubcap, Lobster, Spliced)
        (plugins / "hubcap.lua").write_text("-- hubcap companion\n")
        (plugins / "lobster.lua").write_text("-- lobster companion\n")

        check("companion files are not treated as active interceptors",
              deployer._active_interceptor([plugins]) == "spacebunny1.5.lua")

        # Deploy download.lua interceptor: companion plugins must NOT be archived
        result = deployer.deploy("download.lua")
        check("switch back to Standard succeeds", result["ok"])
        check("download.lua is active interceptor", (plugins / "download.lua").is_file())
        check("hubcap.lua was NOT archived", (plugins / "hubcap.lua").is_file() and not (plugins / "hubcap.lua.bak").exists())
        check("lobster.lua was NOT archived", (plugins / "lobster.lua").is_file() and not (plugins / "lobster.lua.bak").exists())
        check("spliced-tickets.lua was NOT archived", (plugins / "spliced-tickets.lua").is_file() and not (plugins / "spliced-tickets.lua.bak").exists())

        st = deployer.status()["plugins"]
        check("hubcap is active companion", st["hubcap.lua"]["active"] and st["hubcap.lua"]["kind"] == "companion")
        check("lobster is active companion", st["lobster.lua"]["active"] and st["lobster.lua"]["kind"] == "companion")

        (plugins / "hubcap.lua").unlink()
        (plugins / "lobster.lua").unlink()

        # Auto-migration tests for legacy spacebunny1.5.lua
        # 1. Switch to spacebunny1.5.lua
        deployer.deploy("spacebunny1.5.lua")
        check("spacebunny1.5.lua is active interceptor", deployer._active_interceptor([plugins]) == "spacebunny1.5.lua")

        # 2. If user disabled spacebunny.lua, auto-migration must NOT run
        deployer.disable_plugin("spacebunny.lua")
        r_mig = deployer.ensure_default_interceptor()
        check("migration skipped when target is user_disabled", r_mig["ok"] and r_mig.get("active") == "spacebunny1.5.lua")
        check("spacebunny1.5.lua stays active", (plugins / "spacebunny1.5.lua").is_file())
        deployer.enable_plugin("spacebunny.lua")

        # 3. If spacebunny.lua deploy fails (missing from manifest), legacy plugin remains active
        old_sb = manifest["plugins"].pop("spacebunny.lua", None)
        r_mig_fail = deployer.ensure_default_interceptor()
        check("migration failure falls back safely", r_mig_fail["ok"] and r_mig_fail.get("active") == "spacebunny1.5.lua")
        check("spacebunny1.5.lua still active on failure", (plugins / "spacebunny1.5.lua").is_file())
        if old_sb:
            manifest["plugins"]["spacebunny.lua"] = old_sb


if __name__ == "__main__":
    run()
