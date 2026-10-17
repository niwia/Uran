"""ASSella's local depot map as a seed for the Steam metadata cache.

When ASSella has already DLC-expanded a game, its ``apps.depots_json`` blob
carries the same depot -> dlcappid attribution the SteamCMD API returns. Uran
seeds its own cache from it so the game page opens with no network call, while
still falling back to the network for anything ASSella has not expanded and
for the latest data. Uran must also work standalone, so a missing DB (or a
missing optional ``zstandard``) simply means "go to the network".

Skips itself when ``zstandard`` is unavailable, since the blob cannot be built
without it (and Uran is dependency-free by design).
"""

import json
import sqlite3
import sys
import tempfile
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import zstandard
except ImportError:  # pragma: no cover - depends on the host
    print("skip: zstandard not installed (optional dependency)")
    sys.exit(0)

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"FAIL {label}\n     got  {got!r}\n     want {want!r}")
    else:
        print(f"ok  {label}")


def blob(payload: dict) -> bytes:
    return zstandard.ZstdCompressor().compress(json.dumps(payload).encode("utf-8"))


def build(sandbox):
    """Construct the services against a throwaway sandbox home."""
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


sandbox = Path(tempfile.mkdtemp(prefix="uran-local-tier-"))

# ---------------------------------------------------------------------------
# A minimal ACCELA steam_headers.db: one expanded row, one unexpanded row.
# ---------------------------------------------------------------------------
db_dir = sandbox / ".local" / "share" / "ACCELA" / "db"
db_dir.mkdir(parents=True, exist_ok=True)
db_path = db_dir / "steam_headers.db"

expanded = {
    "dlcs_expanded": True,
    "listofdlc": "901, 902",
    "hasdepotsindlc": True,
    "branches": {"public": {}},
    "100": {"name": "Base Content", "oslist": "windows,linux", "osarch": "64",
            "language": "english", "size": 2048, "dlcappid": None, "is_dlc": False},
    "9010": {"name": "[DLC 901] Extra", "oslist": "windows", "osarch": "64",
             "language": "english", "size": 4096, "dlcappid": "901", "is_dlc": True},
}
unexpanded = {
    "dlcs_expanded": False,
    "listofdlc": None,
    "100": {"name": "Base", "dlcappid": None, "is_dlc": False},
}

now = time.time()
with sqlite3.connect(db_path) as conn:
    conn.execute(
        "CREATE TABLE apps (appid TEXT, name TEXT, header_path TEXT, installdir TEXT, "
        "depots_json BLOB, last_updated REAL)"
    )
    conn.execute(
        "INSERT INTO apps VALUES (?,?,?,?,?,?)",
        ("900", "Expanded Game", "", "", blob(expanded), now),
    )
    conn.execute(
        "INSERT INTO apps VALUES (?,?,?,?,?,?)",
        ("902", "Stale Game", "", "", blob(expanded), now - 100000),
    )
    conn.execute(
        "INSERT INTO apps VALUES (?,?,?,?,?,?)",
        ("901", "Unexpanded Game", "", "", blob(unexpanded), now),
    )

svc = build(sandbox)
library, meta = svc.library, svc.steam

calls = {"store": 0, "steamcmd": 0}
meta._fetch_store = lambda app_id: calls.__setitem__("store", calls["store"] + 1) or {
    "name": f"Net {app_id}", "dlc": [f"{app_id}9"]
}
meta._fetch_steamcmd = lambda app_id: calls.__setitem__("steamcmd", calls["steamcmd"] + 1) or {
    "depots": {"100": {"dlcappid": "999"}}
}

# ---------------------------------------------------------------------------
# 1. steam_app_depots decodes an expanded row and rejects the rest
# ---------------------------------------------------------------------------
row = library.steam_app_depots("900")
check("expanded row detected", isinstance(row, dict), True)
check("row name", row["name"], "Expanded Game")
check("DLC list from listofdlc", row["dlc"], ["901", "902"])
check("depot keys are digit ids", sorted(row["depots"]), ["100", "9010"])
check("unexpanded row rejected", library.steam_app_depots("901"), None)
check("absent app rejected", library.steam_app_depots("999"), None)
check("non-digit appid rejected", library.steam_app_depots("abc"), None)

# ---------------------------------------------------------------------------
# 2. A fresh expanded row opens the game with NO network call
# ---------------------------------------------------------------------------
details = meta.app_details("900")
check("no network for a fresh local row", calls, {"store": 0, "steamcmd": 0})
check("depot attribution from local map", details["depot_dlc"], {"9010": "901"})
check("store DLC list from local map", details["dlc"], ["901", "902"])
check("game name from local map", details["name"], "Expanded Game")
check(
    "local row reads as fresh",
    meta.meta_state("900"),
    {"store": "fresh", "steamcmd": "fresh", "needs_fetch": False},
)

# ---------------------------------------------------------------------------
# 3. A row ASSella has not expanded falls back to the network
# ---------------------------------------------------------------------------
calls.update(store=0, steamcmd=0)
meta.app_details("901")
check("unexpanded row uses the network", calls, {"store": 1, "steamcmd": 1})

# ---------------------------------------------------------------------------
# 4. A stale local row is served offline, then refreshed online
# ---------------------------------------------------------------------------
check("stale local row served offline", meta.app_details("902", allow_network=False)["name"], "Stale Game")
check("stale local row still flags a fetch", meta.meta_state("902")["needs_fetch"], True)
calls.update(store=0, steamcmd=0)
meta.app_details("902")
check("stale local row refreshes online", calls, {"store": 1, "steamcmd": 1})
check("refreshed row is fresh", meta.meta_state("902")["needs_fetch"], False)

# ---------------------------------------------------------------------------
# 5. Standalone: no ASSella DB at all means the network, as before
# ---------------------------------------------------------------------------
empty_home = Path(tempfile.mkdtemp(prefix="uran-standalone-"))
solo = build(empty_home)
check("no ASSella DB reads as no local data", solo.library.steam_app_depots("900"), None)
solo.steam._fetch_store = lambda app_id: {"name": "Solo", "dlc": []}
solo.steam._fetch_steamcmd = lambda app_id: {"depots": {}}
check("standalone still fetches the store", solo.steam.app_details("900")["name"], "Solo")

print()
if fails:
    print("\n".join(fails))
    sys.exit(1)
print("all steam local tier cases pass")
