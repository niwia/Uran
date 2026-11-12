"""Tests for operational gates: config.yaml non-generation, required sections,
and the plugin presence check (Uran no longer deploys plugins).
"""

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uran_backend.guards import GuardService
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
            _settings={},
            read_setting=lambda key, default=None: ctx._settings.get(key, default),
            write_setting=lambda key, value: ctx._settings.update({key: value}),
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

    # 4. Parked while plugin deployment is disabled in Uran:
    # # The bundled manifest is signed and supplies its required set offline.
    # from assella_shared.plugin_manifest import ManifestStore, verify_signature
    # bundled = Path(__file__).resolve().parent.parent / "plugins"
    # body = (bundled / "plugins_manifest.json").read_bytes()
    # signature = (bundled / "plugins_manifest.json.sig").read_bytes()
    # check("bundled manifest signature verifies", verify_signature(body, signature))
    # manifest = ManifestStore(Path(tempfile.gettempdir()) / "uran-test-cache", bundled).load_local()
    # check("offline manifest loads", manifest is not None)
    # check("required plugins reflect the signed manifest", set(manifest.required_plugins()) == {
    #     "spacebunny.lua", "styx.lua", "lobster.lua"})
    # check("retired katamari is not deployable", manifest.policy("katamari.lua") == "unavailable")

    # 5. Strict read-only GuardService checks (no Plugins flipping or auto-deploy)
    import uran_backend.guards as guards_mod

    orig_is_steam_running = guards_mod.is_steam_running
    orig_is_sls_active = guards_mod.is_sls_active
    try:
        guards_mod.is_steam_running = lambda: False
        guards_mod.is_sls_active = lambda: False

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            cfg_dir = home / ".config" / "SLSsteam"
            cfg_dir.mkdir(parents=True)
            cfg_path = cfg_dir / "config.yaml"

            sls_dir = home / ".local" / "share" / "SLSsteam"
            sls_dir.mkdir(parents=True)
            (sls_dir / "SLSsteam.so").write_bytes(b"so")

            ctx = SimpleNamespace(
                home=home,
                sls_config=lambda: cfg_path,
                sls_lock=SimpleNamespace(__enter__=lambda self: None, __exit__=lambda *a: None),
                hubcap_key=SimpleNamespace(current=lambda: "key123"),
                _settings={},
                read_setting=lambda key, default=None: ctx._settings.get(key, default),
                write_setting=lambda key, value: ctx._settings.update({key: value}),
            )
            core = SimpleNamespace(ctx=ctx, sls=SlsConfig(ctx))
            guards = GuardService(core)

            # 5a. Plugins: no fails with plugins_disabled and leaves config.yaml unmodified
            initial_cfg = "Plugins: no\nAdditionalDepots:\nDecryptionKeys:\n"
            cfg_path.write_text(initial_cfg, encoding="utf-8")
            res = guards.check_sls_environment()
            check("Plugins: no blocked", res["ok"] is False)
            check("reason is plugins_disabled", res["reason"] == "plugins_disabled")
            check("config.yaml remains unmodified", cfg_path.read_text(encoding="utf-8") == initial_cfg)

            # 5b. Plugins: yes with empty plugins dir fails with no_lua_plugins
            cfg_path.write_text("Plugins: yes\nAdditionalDepots:\nDecryptionKeys:\n", encoding="utf-8")
            res = guards.check_sls_environment()
            check("empty plugins dir blocked", res["ok"] is False)
            check("reason is no_lua_plugins", res["reason"] == "no_lua_plugins")

            # 5c. Plugins: yes with any *.lua file succeeds
            plugins_dir = cfg_dir / "plugins"
            plugins_dir.mkdir(parents=True)
            (plugins_dir / "custom.lua").write_text("-- custom lua plugin\n", encoding="utf-8")
            res = guards.check_sls_environment()
            check("custom.lua accepted", res["ok"] is True)
            check("custom.lua listed in lua_plugins", "custom.lua" in res.get("lua_plugins", []))
    finally:
        guards_mod.is_steam_running = orig_is_steam_running
        guards_mod.is_sls_active = orig_is_sls_active

    print("\nall operational gates checks pass")


if __name__ == "__main__":
    run()
