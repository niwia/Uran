"""AppID-driven projection: base game always on, DLC toggles exact.

These cases lock in the defect that motivated the rewrite:

  * a refetched base-game key was written to DecryptionKeys but its depot never
    reached AdditionalDepots, so nothing mounted it (Refresh must mount it);
  * toggling a DLC off left its depots and keys behind (OFF must remove exactly
    what ON added);
  * depot -> owning-AppID attribution came only from Steam's own dlc list, so a
    DLC that owns depots but is absent from that list was invisible.
"""

import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

KEY = "a" * 64
K621 = "1" * 64
K700 = "2" * 64
K701 = "3" * 64
K622 = "4" * 64

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"FAIL {label}\n     got  {got!r}\n     want {want!r}")
    else:
        print(f"ok  {label}")


def build(sandbox):
    """Construct a Plugin against a throwaway sandbox home."""
    fake = types.ModuleType("decky_plugin")
    fake.DECKY_USER_HOME = str(sandbox)
    fake.DECKY_PLUGIN_DIR = str(sandbox)
    fake.DECKY_PLUGIN_RUNTIME_DIR = str(sandbox)
    fake.DECKY_PLUGIN_SETTINGS_DIR = str(sandbox)
    fake.DECKY_SETTINGS_DIR = str(sandbox)
    sys.modules["decky_plugin"] = fake

    for mod in [m for m in list(sys.modules) if m.startswith("uran_backend")]:
        del sys.modules[mod]

    from uran_backend import services

    return services.build()


SEED = f"""\
Plugins: yes
AdditionalApps:
  - 620 # Portal 2 (620)
AdditionalDepots:
  - 621 # Portal 2 [base] (620)
DecryptionKeys:
  620: {KEY} # Portal 2 [AppKey] (620)
  621: {K621} # Portal 2 [base] (620)
SmartTickets: 0x1
"""

sandbox = Path(tempfile.mkdtemp(prefix="uran-proj-"))
cfg_dir = sandbox / ".config" / "SLSsteam"
cfg_dir.mkdir(parents=True, exist_ok=True)
cfg = cfg_dir / "config.yaml"
cfg.write_text(SEED, encoding="utf-8")

svc = build(sandbox)
inj = svc.injector

APPDETAILS = {
    "name": "Portal 2",
    "depots": ["621", "700", "701"],
    "depot_dlc": {"700": "700", "701": "701"},
    "dlc": ["700", "701"],
}
KEYS = {"621": K621, "700": K700, "701": K701}

svc.steam.app_details = lambda aid: dict(APPDETAILS)
svc.manifests.fetch = (
    lambda aid, persist_config=True: {
        "ok": True,
        "depot_keys": dict(KEYS),
        "manifest_ids": {},
    }
)

from uran_backend import sls_config as slsc

svc.library.register(
    "620", "Portal 2", ["621"], {"621": K621}, depot_names={"621": "base"}
)


def sections():
    text = cfg.read_text(encoding="utf-8")
    return (
        text,
        slsc.parse_list_section(text, "AdditionalApps"),
        slsc.parse_list_section(text, "AdditionalDepots"),
        slsc.parse_key_section(text, "DecryptionKeys")[0],
    )


# ---------------------------------------------------------------------------
# 1. depot -> owning AppID attribution
# ---------------------------------------------------------------------------
record = {"depots": ["621"], "keys": KEYS, "dlc_appids": ["700", "701"]}
owners = svc.library.app_to_depots(
    "620", record=record, depot_dlc={"700": "700"}
)
check("dlcappid attributes depot 700 to AppID 700", sorted(owners.get("700", [])), ["700"])
check("a DLC's own AppID doubles as its depot id", sorted(owners.get("701", [])), ["701"])
check("unattributed depot 621 stays with the base game", sorted(owners.get("base", [])), ["621"])

# ---------------------------------------------------------------------------
# 2. enabling a DLC mounts exactly that DLC
# ---------------------------------------------------------------------------
res = inj.set_game_apps("620", ["700"])
_, apps, depots, keys = sections()
check("enabling a DLC succeeds", res.get("ok"), True)
check("base AppID stays", "620" in apps, True)
check("enabled DLC AppID is added", "700" in apps, True)
check("enabled DLC depot is mounted", "700" in depots, True)
check("enabled DLC key is written", keys.get("700"), K700)
check("the disabled DLC depot is not mounted", "701" in depots, False)
check("the disabled DLC key is not written", "701" in keys, False)

# ---------------------------------------------------------------------------
# 3. disabling the DLC removes exactly what it added (no residue)
# ---------------------------------------------------------------------------
res = inj.set_game_apps("620", [])
_, apps, depots, keys = sections()
check("disabling is ok", res.get("ok"), True)
check("the DLC AppID is removed", "700" in apps, False)
check("the DLC depot is removed", "700" in depots, False)
check("the DLC key is removed", "700" in keys, False)
check("the never-enabled DLC depot never appears", "701" in depots, False)
check("base AppID survives a DLC toggle", "620" in apps, True)
check("base depot survives a DLC toggle", "621" in depots, True)
check("base key survives a DLC toggle", keys.get("621"), K621)

# ---------------------------------------------------------------------------
# 4. Refresh mounts a base depot for a newly fetched key
# ---------------------------------------------------------------------------
svc.manifests.fetch = (
    lambda aid, persist_config=True: {
        "ok": True,
        "depot_keys": {**KEYS, "622": K622},
        "manifest_ids": {},
    }
)
res = inj.refresh("620")
_, apps, depots, keys = sections()
check("refresh is ok", res.get("ok"), True)
check("refresh mounts the new base depot", "622" in depots, True)
check("refresh writes the new base key", keys.get("622"), K622)
check("refresh does not resurrect a disabled DLC", "700" in depots, False)

# ---------------------------------------------------------------------------
# 5. Refresh keeps DLCs that are enabled
# ---------------------------------------------------------------------------
inj.set_game_apps("620", ["700"])
inj.refresh("620")
_, apps, depots, keys = sections()
check("refresh keeps an enabled DLC AppID", "700" in apps, True)
check("refresh keeps an enabled DLC depot", "700" in depots, True)

# ---------------------------------------------------------------------------
# 6. Local tiers: ASSella's cached Lua and this machine's appmanifest
# ---------------------------------------------------------------------------
lua_dir = sandbox / ".local/share/ACCELA" / "cached_luas"
lua_dir.mkdir(parents=True, exist_ok=True)
(lua_dir / "620.lua").write_text(
    "\n".join(
        [
            "-- MAIN APPLICATION",
            "-- MAIN APP DEPOTS",
            f'addappid(621, 1, "{K621}") -- base depot',
            "-- SHARED DEPOTS (from other apps)",
            f'addappid(228989, 1, "{"5" * 64}") -- VC redist',
            "-- DLCS WITH DEDICATED DEPOTS",
            "-- Something Extra (AppID: 703)",
            f'addappid(623, 1, "{"6" * 64}") -- dlc depot',
            "-- UNRELEASED DLCS (COMMENTED OUT)",
            f'--addappid(999, 1, "{"7" * 64}")',
        ]
    ),
    encoding="utf-8",
)
lua = svc.library.cached_lua_depots("620") or {}
check("lua attributes a DLC depot to its AppID", lua.get("623"), "703")
check("lua marks a base depot as base", lua.get("621"), "")
check("lua ignores shared-depot sections", "228989" in lua, False)
check("lua ignores commented-out depots", "999" in lua, False)

owners = svc.library.app_to_depots(
    "620",
    record={"depots": ["621"], "keys": {}},
    installed_depots={"624": {"dlcappid": "704"}, "625": {"manifest": "1"}},
)
check("lua tier maps depot 623 to its DLC", "623" in owners.get("703", []), True)
check("appmanifest tier maps depot 624 to its DLC", "624" in owners.get("704", []), True)
check("appmanifest depot without dlcappid stays base", "625" in owners.get("base", []), True)

# ---------------------------------------------------------------------------
# 7. the root AppKey is written under the AppID (never dropped)
# ---------------------------------------------------------------------------
APPKEY = "9" * 64
cfg.write_text(
    "Plugins: yes\n"
    "AdditionalApps:\n"
    "  - 620 # Portal 2 (620)\n"
    "AdditionalDepots:\n"
    "  - 621 # Portal 2 [base] (620)\n"
    "DecryptionKeys:\n"
    f"  621: {K621} # Portal 2 [base] (620)\n"
    "SmartTickets: 0x1\n",
    encoding="utf-8",
)
svc.manifests.fetch = (
    lambda aid, persist_config=True: {
        "ok": True,
        "depot_keys": {**KEYS, "620": APPKEY},
        "manifest_ids": {},
    }
)
res = inj.refresh("620")
_, apps, depots, keys = sections()
check("refresh writes the root AppKey under the AppID", keys.get("620"), APPKEY)
check(
    "the AppKey is tagged in the config",
    "[AppKey]" in cfg.read_text(encoding="utf-8"),
    True,
)
check("the AppKey is not mounted as a depot", "620" in depots, False)
check("keys_added reports the AppKey", "620" in (res.get("keys_added") or []), True)

# ---------------------------------------------------------------------------
# 8. ownership comments are scoped: another game is never claimed
# ---------------------------------------------------------------------------
check(
    "the paren guard rejects a shared numeric prefix",
    svc.library._owned_comment("Half-Life 2 [base] (6207)", "620", "Portal 2"),
    False,
)
check(
    "the paren guard accepts our own AppID",
    svc.library._owned_comment("Portal 2 [base] (620)", "620", "Portal 2"),
    True,
)
check(
    "an ASSella name-prefix comment is recognised",
    svc.library._owned_comment("Portal 2 - base depot (621)", "620", "Portal 2"),
    True,
)
check(
    "a longer game name is not claimed by a prefix",
    svc.library._owned_comment("Portal 2 Continued [base] (6203)", "620", "Portal 2"),
    False,
)

cfg.write_text(
    "Plugins: yes\n"
    "AdditionalApps:\n"
    "  - 620 # Portal 2 (620)\n"
    "  - 6207 # Portal 2 Continued (6207)\n"
    "AdditionalDepots:\n"
    "  - 621 # Portal 2 [base] (620)\n"
    "  - 6208 # Portal 2 Continued [base] (6207)\n"
    "DecryptionKeys:\n"
    f"  620: {KEY} # Portal 2 [AppKey] (620)\n"
    f"  621: {K621} # Portal 2 [base] (620)\n"
    f"  6208: {K622} # Portal 2 Continued [base] (6207)\n"
    "SmartTickets: 0x1\n",
    encoding="utf-8",
)
inj.set_game_apps("620", [])
_, apps, depots, keys = sections()
check("another game's AppID is untouched", "6207" in apps, True)
check("another game's depot is untouched", "6208" in depots, True)
check("another game's key is untouched", keys.get("6208"), K622)

# ---------------------------------------------------------------------------
# 9. AppTokens: license tokens written, tagged, and isolated across games
# ---------------------------------------------------------------------------
r = inj._project_config(
    "620", "Portal 2", {"620": KEY, "621": K621}, {"base": ["621"]}, set(),
    candidate_depots={"621"}, app_tokens={"620": "TOK_620", "4000": "TOK_4000"},
)
check("project with tokens succeeds", r.get("ok"), True)
c = cfg.read_text(encoding="utf-8")
check("AppTokens section created", "AppTokens:" in c, True)
check("main game token has game name and appid comment", "620: TOK_620 # Portal 2 (620)" in c, True)
check("dlc token has appid comment", "4000: TOK_4000 # (620)" in c, True)

# Project another game with tokens
r2 = inj._project_config(
    "700", "HL2", {"700": KEY}, {"base": ["700"]}, set(),
    candidate_depots={"700"}, app_tokens={"700": "TOK_700"},
)
c2 = cfg.read_text(encoding="utf-8")
check("new game token added", "700: TOK_700 # HL2 (700)" in c2, True)
check("previous game token preserved", "620: TOK_620 # Portal 2 (620)" in c2, True)
check("previous dlc token preserved", "4000: TOK_4000 # (620)" in c2, True)

# Reproject 620 with updated tokens: 4000 dropped, 620 updated
r3 = inj._project_config(
    "620", "Portal 2", {"620": KEY, "621": K621}, {"base": ["621"]}, set(),
    candidate_depots={"621"}, app_tokens={"620": "NEW_TOK_620"},
)
c3 = cfg.read_text(encoding="utf-8")
check("updated token written", "620: NEW_TOK_620 # Portal 2 (620)" in c3, True)
check("old dlc token removed on reprojection", "TOK_4000" in c3, False)
check("unrelated game token still preserved", "700: TOK_700 # HL2 (700)" in c3, True)

print()
if fails:
    print("\n".join(fails))
    sys.exit(1)
print("all projection cases pass")
