"""Unit tests for smart depot filtering, ManifestIds pruning, and ACF healing."""

import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

KEY_APP = "a" * 64
KEY_WIN = "1" * 64
KEY_LIN = "2" * 64
KEY_MAC = "3" * 64

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"FAIL {label}\n     got  {got!r}\n     want {want!r}")
    else:
        print(f"ok  {label}")


def build(sandbox):
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


sandbox = Path(tempfile.mkdtemp(prefix="uran-smart-"))
cfg_dir = sandbox / ".config" / "SLSsteam"
cfg_dir.mkdir(parents=True, exist_ok=True)
cfg = cfg_dir / "config.yaml"
cfg.write_text("Plugins: yes\nAdditionalApps:\nAdditionalDepots:\nDecryptionKeys:\nSmartTickets: 0x1\n", encoding="utf-8")

svc = build(sandbox)
inj = svc.injector

# Mock AppID 2288470 with 3 OS depots
AID = "2288470"
DEPOT_WIN = "2288471"
DEPOT_LIN = "2288472"
DEPOT_MAC = "2288473"

svc.steam.app_details = lambda aid, allow_network=False, force=False: {
    "name": "Aethermancer",
    "depots": [DEPOT_WIN, DEPOT_LIN, DEPOT_MAC],
    "depot_meta": {
        DEPOT_WIN: {"name": "Windows Content", "oslist": "windows", "size_bytes": 6000000},
        DEPOT_LIN: {"name": "Linux Content", "oslist": "linux", "size_bytes": 6000000},
        DEPOT_MAC: {"name": "macOS Content", "oslist": "macos", "size_bytes": 5000000},
    },
    "depot_dlc": {},
    "dlc": [],
}
svc.steam.install_info = lambda aid: {
    "installed": True,
    "installed_depots": {DEPOT_LIN: {"manifest": "0", "size": "6000000"}},
    "acf_path": str(sandbox / f"appmanifest_{aid}.acf"),
    "state_flags": 518,
}

keys = {
    AID: KEY_APP,
    DEPOT_WIN: KEY_WIN,
    DEPOT_LIN: KEY_LIN,
    DEPOT_MAC: KEY_MAC,
}
manifests = {
    DEPOT_WIN: "1111111111111111111",
    DEPOT_LIN: "2222222222222222222",
    DEPOT_MAC: "3333333333333333333",
}

# 1. Project config without depot filtering and without ManifestIds injection
res = inj._project_config(
    AID, "Aethermancer", keys, {"base": [DEPOT_WIN, DEPOT_LIN, DEPOT_MAC]}, set(),
    selected_depots=None,
)

check("projected successfully", res.get("ok"), True)
check("all keyed candidate depots mounted in AdditionalDepots", res.get("depots_added"), [DEPOT_WIN, DEPOT_LIN, DEPOT_MAC])
check("all base depot keys plus AppKey retained in DecryptionKeys", res.get("keys_added"), [AID, DEPOT_WIN, DEPOT_LIN, DEPOT_MAC])

from uran_backend import sls_config as sc
cfg_content = cfg.read_text(encoding="utf-8")

# Check AdditionalDepots in config
depots_list = sc.parse_list_section(cfg_content, "AdditionalDepots")
check("config AdditionalDepots has all keyed depots", list(depots_list.keys()), [DEPOT_WIN, DEPOT_LIN, DEPOT_MAC])

# Check DecryptionKeys in config
dec_keys, _ = sc.parse_key_section(cfg_content, "DecryptionKeys")
check("config DecryptionKeys has Windows key", DEPOT_WIN in dec_keys, True)
check("config DecryptionKeys has Linux key", DEPOT_LIN in dec_keys, True)
check("config DecryptionKeys has macOS key", DEPOT_MAC in dec_keys, True)
check("config DecryptionKeys has AppKey", AID in dec_keys, True)

# Check ManifestIds in config - should NOT contain any pins for this game
m_ids, _ = sc.parse_manifest_section(cfg_content)
check("config ManifestIds has no pins injected for this game", [d for d in m_ids if d in (DEPOT_WIN, DEPOT_LIN, DEPOT_MAC, AID)], [])

# 2. Test ACF healing
acf_file = sandbox / f"appmanifest_{AID}.acf"
acf_file.write_text(f'''"AppState"
{{
\t"appid"\t\t"{AID}"
\t"StateFlags"\t\t"518"
\t"InstalledDepots"
\t{{
\t\t"{DEPOT_LIN}"
\t\t{{
\t\t\t"manifest"\t\t"0"
\t\t}}
\t}}
}}
''', encoding="utf-8")

healed = inj._heal_acf_if_needed(AID, manifests)
check("ACF healed successfully", healed, True)

healed_content = acf_file.read_text(encoding="utf-8")
check("ACF manifest updated from 0 to real GID", f'"manifest"\t\t"2222222222222222222"' in healed_content, True)
check("ACF StateFlags reset from 518 to 4", '"StateFlags"\t\t"4"' in healed_content, True)

if fails:
    print(f"\n{len(fails)} checks failed:")
    for f in fails:
        print(f"  {f}")
    sys.exit(1)

print("\nall smart depot checks pass")
