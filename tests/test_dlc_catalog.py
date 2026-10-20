"""DLC catalog parsing, intersection safeguard, qualification, and key safety tests.

Validates:
1. `qualify_dlc_name` correctly handles placeholders vs real titles.
2. `listofdlc` extraction merges SteamCMD catalog with store data.
3. Catalog intersection safeguard:
   - When store DLCs intersect with SteamCMD DLCs, splits into active and delisted.
   - When store DLCs do not intersect (Rocksmith 2014 pattern), keeps all as active.
4. `add_delisted_dlcs` setting behavior in `fetch_dlcs`.
5. Key exclusivity: unkeyed depots are never mounted in AdditionalDepots or DecryptionKeys.
"""

import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uran_backend.depot_tags import is_placeholder_dlc_name, qualify_dlc_name

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"FAIL {label}\n     got  {got!r}\n     want {want!r}")
    else:
        print(f"ok  {label}")


# ---------------------------------------------------------------------------
# 1. qualify_dlc_name & is_placeholder_dlc_name
# ---------------------------------------------------------------------------
check("empty string is placeholder", is_placeholder_dlc_name("", "100"), True)
check("unknown is placeholder", is_placeholder_dlc_name("Unknown", "100"), True)
check("dlc <id> is placeholder", is_placeholder_dlc_name("DLC 100", "100"), True)
check("raw id is placeholder", is_placeholder_dlc_name("100", "100"), True)
check("real name is not placeholder", is_placeholder_dlc_name("Episode One", "100"), False)

check(
    "placeholder qualified with game name",
    qualify_dlc_name("Unknown", "211421", "Dark Souls"),
    "Dark Souls - Unknown",
)
check(
    "empty name qualified with game name",
    qualify_dlc_name("", "211421", "Dark Souls"),
    "Dark Souls - DLC 211421",
)
check(
    "real title preserved untouched",
    qualify_dlc_name("Artorias of the Abyss", "211421", "Dark Souls"),
    "Artorias of the Abyss",
)

# ---------------------------------------------------------------------------
# 2. Services sandbox for steammeta and inject tests
# ---------------------------------------------------------------------------
sandbox = Path(tempfile.mkdtemp(prefix="uran-dlc-test-"))
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
svc = services.build()

# Create dummy SLS config
cfg_file = sandbox / ".config" / "slssteam" / "config.yaml"
cfg_file.parent.mkdir(parents=True, exist_ok=True)
cfg_file.write_text("Plugins: yes\nAdditionalApps:\nAdditionalDepots:\nDecryptionKeys:\n")
svc.ctx.sls_config = lambda: cfg_file

# ---------------------------------------------------------------------------
# 3. Catalog intersection safeguard
# ---------------------------------------------------------------------------
# Scenario A: Normal game with store DLCs (101, 102) and historical listofdlc (101, 102, 103-delisted)
svc.steam._fetch_store = lambda aid: {
    "name": "Game A",
    "packages": [],
    "dlc": [101, 102],
}
svc.steam._fetch_steamcmd = lambda aid: {
    "common": {"name": "Game A"},
    "extended": {"listofdlc": "101,102,103"},
    "depots": {
        "101": {"dlcappid": "101"},
        "102": {"dlcappid": "102"},
        "103": {"dlcappid": "103"},
    },
}

details_a = svc.steam.app_details("100", allow_network=True, force=True)
check("store active dlcs parsed", details_a["dlc"], ["101", "102"])
check("all dlcs contains delisted", details_a["dlc_all"], ["101", "102", "103"])
check(
    "delisted dlc is outside the active list",
    [d for d in details_a["dlc_all"] if d not in details_a["dlc"]],
    ["103"],
)

# Scenario B: Rocksmith-style game where store lists song bundles (901) and SteamCMD lists individual songs (902, 903)
svc.steam._fetch_store = lambda aid: {
    "name": "Rocksmith 2014",
    "packages": [],
    "dlc": [901],
}
svc.steam._fetch_steamcmd = lambda aid: {
    "common": {"name": "Rocksmith 2014"},
    "extended": {"listofdlc": "902,903"},
    "depots": {},
}
details_b = svc.steam.app_details("24870", allow_network=True, force=True)
# Non-intersecting: safeguard keeps all dlcs as active instead of dropping everything
check("non-intersecting keep all dlcs", details_b["dlc_all"], ["902", "903", "901"])
check("non-intersecting safeguard active dlcs", details_b["dlc"], ["902", "903", "901"])
check(
    "non-intersecting fallback has no separately delisted DLCs",
    [d for d in details_b["dlc_all"] if d not in details_b["dlc"]],
    [],
)

# ---------------------------------------------------------------------------
# 4. Settings default & configured DLC fetch behavior
# ---------------------------------------------------------------------------
check("add_delisted_dlcs default is True", svc.ctx.read_setting("add_delisted_dlcs", True), True)
check("fetch_dlcs_on_inject default is True", svc.ctx.read_setting("fetch_dlcs_on_inject", True), True)

# Mock manifests to provide depot keys for 101 and 103, but NOT 102
K101 = "a" * 64
K103 = "c" * 64
svc.manifests.fetch = lambda aid, persist_config=False: {
    "ok": True,
    "app_id": aid,
    "depot_keys": {"101": K101, "103": K103},
    "dlc_appids": ["101", "103"],
}
svc.library.save_local_depot_keys("100", {"101": K101, "103": K103})

# Register base game first
svc.library.register("100", "Game A", ["101"], {"101": K101})

# Fetch DLCs; the configured add_delisted_dlcs setting controls catalog scope.
res_delisted = svc.injector.fetch_dlcs("100")
check("fetch_dlcs with delisted enabled is ok", res_delisted.get("ok"), True)
check("configured fetch includes delisted DLC 103", "103" in res_delisted.get("apps_added", []), True)

# Check config contents: 102 had no key so depot 102 must NOT be mounted
from uran_backend import sls_config as slsc
sls_text = cfg_file.read_text(encoding="utf-8")
depots = slsc.parse_list_section(sls_text, "AdditionalDepots")
keys, _ = slsc.parse_key_section(sls_text, "DecryptionKeys")

check("depot 101 with key is mounted", "101" in depots, True)
check("depot 103 with key is mounted", "103" in depots, True)
check("unkeyed depot 102 is NOT mounted in AdditionalDepots", "102" in depots, False)
check("unkeyed depot 102 is NOT in DecryptionKeys", "102" in keys, False)

print()
if fails:
    print(f"FAILED: {len(fails)} check(s)")
    for f in fails:
        print(f)
    sys.exit(1)
print("all DLC catalog tests passed")
