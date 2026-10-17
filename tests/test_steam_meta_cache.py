"""Steam metadata cache: fresh, stale, and failed-refresh behaviour.

The game page must render from disk without waiting on Steam, so each source is
cached with a TTL. These cases lock in how staleness is decided:

  * a cold cache fetches both sources once and persists them to disk;
  * a fresh entry is served with no network at all;
  * a stale entry is still served (never blank the page) and is flagged so the
    page knows to refresh in the background;
  * a failed refresh keeps the stale copy rather than replacing it with nothing;
  * an unreadable cache file degrades to "missing", it never crashes the page.
"""

import json
import sys
import tempfile
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"FAIL {label}\n     got  {got!r}\n     want {want!r}")
    else:
        print(f"ok  {label}")


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


sandbox = Path(tempfile.mkdtemp(prefix="uran-meta-"))
meta = build(sandbox).steam

calls = {"store": 0, "steamcmd": 0}


def fetch_store(app_id):
    calls["store"] += 1
    return {"name": f"Game {app_id}", "dlc": [f"{app_id}1"]}


def fetch_cmd(app_id):
    calls["steamcmd"] += 1
    return {"depots": {"100": {"dlcappid": "101"}}}


meta._fetch_store = fetch_store
meta._fetch_steamcmd = fetch_cmd

# ---------------------------------------------------------------------------
# 1. Cold cache: both sources fetched once and written to disk
# ---------------------------------------------------------------------------
d = meta.app_details("1")
check("cold store fetched", calls["store"], 1)
check("cold steamcmd fetched", calls["steamcmd"], 1)
check("depot_dlc parsed", d["depot_dlc"], {"100": "101"})
check(
    "cold state is fresh",
    meta.meta_state("1"),
    {"store": "fresh", "steamcmd": "fresh", "needs_fetch": False},
)
check("cache file written", (sandbox / "meta" / "1.json").is_file(), True)

# ---------------------------------------------------------------------------
# 2. A fresh entry is served with no network
# ---------------------------------------------------------------------------
meta.app_details("1")
check("fresh cache does not refetch store", calls["store"], 1)
check("fresh cache does not refetch steamcmd", calls["steamcmd"], 1)

# ---------------------------------------------------------------------------
# 3. allow_network=False never issues a request, even when the entry is missing
# ---------------------------------------------------------------------------
meta.app_details("2", allow_network=False)
check("offline read issues no request", calls, {"store": 1, "steamcmd": 1})
check("unknown app asks for a fetch", meta.meta_state("2")["needs_fetch"], True)

# ---------------------------------------------------------------------------
# 4. Age the store entry past the TTL: served, flagged, then refreshed
# ---------------------------------------------------------------------------
path = sandbox / "meta" / "1.json"
raw = json.loads(path.read_text(encoding="utf-8"))
raw["store"]["at"] = time.time() - 100000
path.write_text(json.dumps(raw), encoding="utf-8")
meta._mem.clear()  # reload from disk

check("stale store still served offline", meta.app_details("1", allow_network=False)["name"], "Game 1")
check(
    "stale source is flagged",
    meta.meta_state("1"),
    {"store": "stale", "steamcmd": "fresh", "needs_fetch": True},
)

meta.app_details("1")  # background refresh
check("only the stale source refetched", calls, {"store": 2, "steamcmd": 1})
check("refreshed state is fresh", meta.meta_state("1")["needs_fetch"], False)

# ---------------------------------------------------------------------------
# 5. A failed refresh keeps the stale copy instead of blanking the page
# ---------------------------------------------------------------------------
raw = json.loads(path.read_text(encoding="utf-8"))
raw["steamcmd"]["at"] = time.time() - 100000
path.write_text(json.dumps(raw), encoding="utf-8")
meta._mem.clear()
meta._fetch_steamcmd = lambda app_id: None
check("failed refresh keeps stale data", meta.app_details("1")["depot_dlc"], {"100": "101"})

# ---------------------------------------------------------------------------
# 6. An unreadable cache degrades to missing, never crashes
# ---------------------------------------------------------------------------
path.write_text("{ this is not json", encoding="utf-8")
meta._mem.clear()
check(
    "corrupt cache reads as missing",
    meta.meta_state("1"),
    {"store": "missing", "steamcmd": "missing", "needs_fetch": True},
)

print()
if fails:
    print("\n".join(fails))
    sys.exit(1)
print("all steam metadata cache cases pass")
