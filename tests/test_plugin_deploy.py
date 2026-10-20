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


if __name__ == "__main__":
    run()
