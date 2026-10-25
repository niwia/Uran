"""Tests for operational gates: config.yaml non-generation, required sections,
SpaceBunny auto-deployment, and spacebunny.conf.lua sync.
"""

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uran_backend.guards import GuardService
from uran_backend.plugin_deploy import PluginDeployer
from uran_backend.sls_config import SlsConfig, ensure_required_sections, ensure_section_header


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print(f"ok  {label}")


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


def run():
    # 1. SlsConfig never creates config.yaml if it does not exist
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        ctx = SimpleNamespace(
            home=home,
            sls_config=lambda: home / ".config" / "SLSsteam" / "config.yaml",
            sls_lock=SimpleNamespace(__enter__=lambda self: None, __exit__=lambda *a: None),
        )
        sls = SlsConfig(ctx)
        check("read returns empty on missing config", sls.read() == "")
        check("write fails on missing config", sls.write("Plugins: yes\n") is False)
        check("config file was not created", not (home / ".config" / "SLSsteam" / "config.yaml").exists())

    # 2. ensure_required_sections ensures Plugins: yes, AdditionalDepots:, and DecryptionKeys:
    initial = "AppId:\n  - 480\n"
    ensured = ensure_required_sections(initial)
    check("Plugins: yes added", "Plugins: yes" in ensured)
    check("AdditionalDepots added", "AdditionalDepots:" in ensured)
    check("DecryptionKeys added", "DecryptionKeys:" in ensured)
    # Idempotent
    re_ensured = ensure_required_sections(ensured)
    check("ensure_required_sections idempotent", re_ensured == ensured)

    # 3. GuardService operational gate blocks if config.yaml is absent
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        cfg_path = home / ".config" / "SLSsteam" / "config.yaml"
        ctx = SimpleNamespace(
            home=home,
            sls_config=lambda: cfg_path,
            hubcap_key=SimpleNamespace(current=lambda: "key123"),
        )
        core = SimpleNamespace(ctx=ctx, sls=SlsConfig(ctx))
        guards = GuardService(core)
        res = guards.check_sls_environment()
        check("check_sls_environment fails if config.yaml missing", res["ok"] is False)
        check("reason is no_sls_config", res["reason"] == "no_sls_config")
        check("error mentions SLSsteam must be running", "running to generate it" in res["error"])

    # 4. SpaceBunny auto-deployment from R2 if no interceptor exists
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        cfg_path = home / ".config" / "SLSsteam" / "config.yaml"
        plugins_dir = cfg_path.parent / "plugins"
        cfg_path.parent.mkdir(parents=True)
        plugins_dir.mkdir(parents=True)
        cfg_path.write_text("Plugins: yes\n", encoding="utf-8")

        hubcap_key_val = ["test-key-abc"]
        ctx = SimpleNamespace(
            home=home,
            runtime_dir=home / "runtime",
            sls_config=lambda: cfg_path,
            hubcap_key=SimpleNamespace(current=lambda: hubcap_key_val[0]),
            sls_lock=SimpleNamespace(__enter__=lambda self: None, __exit__=lambda *a: None),
        )
        sls = SlsConfig(ctx)

        content = {
            "spacebunny1.5.lua": b"-- spacebunny plugin code\n",
            "spliced-tickets.lua": b"-- spliced tickets code\n",
        }
        manifest = {
            "plugins": {
                name: {"sha256": hashlib.sha256(data).hexdigest(), "version": "1.5.0"}
                for name, data in content.items()
            }
        }

        import urllib.request
        from uran_backend import plugin_deploy

        def fake_urlopen(request, timeout=10):
            url = request.full_url
            if url.endswith("plugins_manifest.json"):
                return FakeResponse(json.dumps(manifest).encode())
            name = url.rsplit("/", 1)[-1]
            return FakeResponse(content[name])

        plugin_deploy.urllib.request.urlopen = fake_urlopen
        deployer = PluginDeployer(ctx, sls)

        # Initially, no lua plugin exists. ensure_default_interceptor must deploy SpaceBunny
        r = deployer.ensure_default_interceptor()
        check("auto-deploy SpaceBunny succeeded", r["ok"])
        check("spacebunny1.5.lua deployed", (plugins_dir / "spacebunny1.5.lua").is_file())
        check("spacebunny.conf.lua created with key", (cfg_path.parent / "spacebunny.conf.lua").is_file())
        check("spacebunny.conf.lua contains key", "test-key-abc" in (cfg_path.parent / "spacebunny.conf.lua").read_text())

        # If user clears hubcap key, sync_spacebunny_conf removes spacebunny.conf.lua
        hubcap_key_val[0] = ""
        deployer.sync_spacebunny_conf()
        check("spacebunny.conf.lua removed when key is empty", not (cfg_path.parent / "spacebunny.conf.lua").exists())

        # If user has another interceptor (e.g. custom.lua), ensure_default_interceptor ignores it
        (plugins_dir / "custom.lua").write_text("-- custom interceptor\n")
        (plugins_dir / "spacebunny1.5.lua").unlink()
        r2 = deployer.ensure_default_interceptor()
        check("custom lua present -> ignored auto-deploy", r2["ok"] and not r2.get("deployed", False))
        check("spacebunny was not deployed over custom", not (plugins_dir / "spacebunny1.5.lua").exists())

    print("\nall operational gates checks pass")


if __name__ == "__main__":
    run()
