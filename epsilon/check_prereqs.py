#!/usr/bin/env python3
"""Epsilon Prerequisites Checker.

Verifies:
1. SLSsteam is installed and config.yaml is generated.
2. SLSsteam Lua plugins (e.g. SpaceBunny, download.lua) are present.
3. Hubcap API key is available in ASSella/ACCELA/spacebunny.conf.lua.

Directs users to the Epsilon setup guide if anything is missing:
https://assella.niwia.top/epsilon
"""

import sys
from pathlib import Path

# Ensure uran_backend is accessible
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

GUIDE_URL = "https://assella.niwia.top/epsilon"


def check_prerequisites():
    from uran_backend.plugin_api import default_services

    services = default_services()
    ctx = services.ctx

    # 1. SLSsteam installation check
    cfg = ctx.sls_config()
    sls_installed = bool(cfg and cfg.exists())
    if not sls_installed:
        from uran_backend.paths import sls_binary_candidates

        for b_cand in sls_binary_candidates(ctx.home):
            if b_cand.is_file():
                sls_installed = True
                break

    # 2. SLS Plugins check
    from uran_backend.guards import find_lua_plugins

    plugin_dir, lua_files = find_lua_plugins(ctx.home)
    has_plugins = bool(lua_files)

    # 3. Hubcap API Key check
    has_hubcap_key = bool(ctx.hubcap_key.current())

    all_ok = sls_installed and has_plugins and has_hubcap_key

    print("==========================================================")
    print("  Epsilon Prerequisites Check                             ")
    print("==========================================================")

    if sls_installed:
        print(f"[+] SLSsteam:         Installed ({cfg or 'binary found'})")
    else:
        print("[-] SLSsteam:         MISSING (config.yaml not found)")

    if has_plugins:
        plugin_list = ", ".join(lua_files[:3])
        if len(lua_files) > 3:
            plugin_list += f" (+{len(lua_files) - 3} more)"
        print(f"[+] SLSsteam Plugins: Found ({plugin_list})")
    else:
        p_dir_display = str(plugin_dir) if plugin_dir else "plugins folder"
        print(f"[-] SLSsteam Plugins: MISSING (No .lua plugins in {p_dir_display})")

    if has_hubcap_key:
        print("[+] Hubcap API Key:   Configured")
    else:
        print("[-] Hubcap API Key:   MISSING (No key in settings or spacebunny.conf.lua)")

    print("----------------------------------------------------------")
    if all_ok:
        print("[+] All prerequisites are satisfied!")
        print("    Epsilon is fully configured and ready for injections.")
    else:
        print("[!] Setup is incomplete! Epsilon requires these components")
        print("    to communicate with Steam and download game manifests.")
        print("")
        print(f"    Please follow our step-by-step setup guide:")
        print(f"    {GUIDE_URL}")
    print("==========================================================")

    return 0 if all_ok else 2


if __name__ == "__main__":
    sys.exit(check_prerequisites())
