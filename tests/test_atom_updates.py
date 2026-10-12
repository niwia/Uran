"""AT0-M update check: states, error handling, caching and request pacing.

Each case here corresponds to a defect found in review:

  * a missing API key used to summarise as "all up to date"
  * `key_pending` was unreachable once the Steam side was dropped
  * the 40ms per-thread "rate limit" allowed 0ms gaps between requests
  * depot names were hardcoded to `Depot <id>` even when known locally
  * ASSella's persisted status was ignored, so every press re-queried Hubcap
"""

import sqlite3
import sys
import tempfile
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uran_backend import hubcap

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"FAIL {label}\n     got  {got!r}\n     want {want!r}")
    else:
        print(f"ok  {label}")


def build(sandbox, db_setup=None):
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

    if db_setup:
        db_dir = Path(sandbox) / ".local/share/ACCELA/db"
        db_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_dir / "steam_headers.db")
        db_setup(conn)
        conn.commit()
        conn.close()

    from uran_backend import services

    return services.build()


KEY = "a" * 64

# ---------------------------------------------------------------------------
# 1. key_pending is reachable again
# ---------------------------------------------------------------------------
sandbox = Path(tempfile.mkdtemp(prefix="uran-chk-"))
atom = build(sandbox).atom
atom.library.cached_update_status = lambda aid: None
atom.library.known_depots_for = lambda aid, rec: {"621"}
atom.manifests.contents = lambda aid: {"manifests": [{"depot_id": "621", "manifest_id": "1"}]}
atom.steam.app_details = lambda aid: {"depots": ["621", "622"]}

r = atom.check_updates("620")
check("Steam-added depot Hubcap lacks -> key_pending", r["status"], "key_pending")
check("key_pending is not an update", r["has_update"], False)
check("key_pending names the waiting depot",
      [d["id"] for d in r["pending_depots"]], ["622"])

# ---------------------------------------------------------------------------
# 2. up_to_date only when there is genuinely nothing
# ---------------------------------------------------------------------------
atom.steam.app_details = lambda aid: {"depots": ["621"]}
check("nothing missing -> up_to_date", atom.check_updates("620")["status"], "up_to_date")

atom.steam.app_details = lambda aid: {"depots": []}
check("no Steam data -> up_to_date (no false pending)",
      atom.check_updates("620")["status"], "up_to_date")

atom.manifests.contents = lambda aid: {"manifests": [{"depot_id": "621", "manifest_id": "1"},
                                                     {"depot_id": "623", "manifest_id": "1"}]}
atom.library.known_depots_for = lambda aid, rec: {"621"}
atom.steam.app_details = lambda aid: {"depots": ["621"]}
r = atom.check_updates("620")
check("Hubcap holds a depot we lack -> update_available", r["status"], "update_available")
check("update_available lists it", [d["id"] for d in r["new_depots"]], ["623"])

# ---------------------------------------------------------------------------
# 3. errors are never reported as "up to date"
# ---------------------------------------------------------------------------
atom.manifests.contents = lambda aid: {"error": "Hubcap API key is not set in ACCELA settings"}
r = atom.check_updates("620")
check("failed check reports status error", r["status"], "error")
check("failed check is not ok", r["ok"], False)
check("failed check carries the reason", "API key" in r["error"], True)

atom.library.load = lambda: {"620": {"name": "A", "depots": [], "keys": {}},
                            "621": {"name": "B", "depots": [], "keys": {}}}
batch = atom.check_all_updates()
check("batch with failures is not ok", batch["ok"], False)
check("batch counts failures", batch["error_count"], 2)
check("batch does not count failures as updates", batch["update_count"], 0)
check("batch surfaces the underlying error",
      "API key" in (batch["error"] or ""), True)

# ---------------------------------------------------------------------------
# 4. real depot names
# ---------------------------------------------------------------------------
atom.library.cached_update_status = lambda aid: None
atom.manifests.contents = lambda aid: {"manifests": [{"depot_id": "777", "manifest_id": "1"}]}
atom.library.known_depots_for = lambda aid, rec: set()
atom.steam.app_details = lambda aid: {"depots": []}
atom.ctx.depot_names["777"] = "Portal 2 win64 content"
check("uses the cached depot name",
      atom.check_updates("620")["new_depots"][0]["name"], "Portal 2 win64 content")

# ---------------------------------------------------------------------------
# 5. ASSella's persisted status is honoured (read-only)
# ---------------------------------------------------------------------------
def seed(conn):
    conn.execute(
        "CREATE TABLE at0m_update_status (appid TEXT PRIMARY KEY, game_title TEXT,"
        " last_timeupdated INTEGER DEFAULT 0, last_checked INTEGER DEFAULT 0,"
        " status TEXT DEFAULT 'up_to_date', new_depots TEXT DEFAULT '[]',"
        " cooldown_until INTEGER DEFAULT 0)"
    )
    conn.execute(
        "CREATE TABLE missing_hubcap_depots (appid TEXT, depot_id TEXT,"
        " manifest_id TEXT, depot_name TEXT, first_seen INTEGER,"
        " PRIMARY KEY (appid, depot_id))"
    )
    now = int(time.time())
    conn.executemany(
        "INSERT INTO at0m_update_status VALUES (?,?,?,?,?,?,?)",
        [
            ("620", "Portal 2", 1, now - 60, "up_to_date", "[]", 0),
            ("999", "Ancient", 1, now - 90000, "up_to_date", "[]", 0),
            ("888", "Pending", 1, now - 60, "key_pending",
             '[{"id":"7","name":"Depot 7","has_key":false}]', now + 3600),
            ("777", "Advertised", 1, now - 60, "update_available",
             '[{"id":"5","name":"Depot 5","has_key":true}]', 0),
        ],
    )
    conn.execute("INSERT INTO missing_hubcap_depots VALUES (?,?,?,?,?)",
                 ("888", "7", "7", "Dedicated Server", 0))


sandbox2 = Path(tempfile.mkdtemp(prefix="uran-cache-"))
svc = build(sandbox2, db_setup=seed)
lib = svc.library
atom2 = svc.atom

check("fresh up_to_date is served from ASSella's cache",
      (lib.cached_update_status("620") or {}).get("from"), "assella_cache")
check("up_to_date past the 24h TTL is recomputed", lib.cached_update_status("999"), None)
check("key_pending inside cooldown is trusted",
      (lib.cached_update_status("888") or {}).get("status"), "key_pending")
check("update_available is re-verified, never cached blind",
      lib.cached_update_status("777"), None)
check("pending depots carry ASSella's name",
      [d["name"] for d in lib.pending_hubcap_depots("888")], ["Dedicated Server"])
check("absent appid is simply not cached", lib.cached_update_status("123456"), None)

hubcap_calls = []
atom2.library.load = lambda: {"620": {"name": "Portal 2", "depots": [], "keys": {}}}
atom2.manifests.contents = lambda aid: (hubcap_calls.append(aid), {"manifests": []})[1]
atom2.steam.app_details = lambda aid: {"depots": []}
r = atom2.check_updates("620")
check("cached game costs zero Hubcap calls", len(hubcap_calls), 0)
check("cached game reports the cached status", r["status"], "up_to_date")
check("cached game is marked as cached", r["from"], "assella_cache")

r = atom2.check_updates("620", use_cache=False)
check("cache can be bypassed explicitly", len(hubcap_calls), 1)

# ---------------------------------------------------------------------------
# 6. requests are actually paced
# ---------------------------------------------------------------------------
stamps = []


class _FakeClient:
    def get(self, url, headers=None, timeout=10, stream=False, verify=True):
        stamps.append(time.monotonic())

        class _R:
            status_code = 200
            ok = True
            content = b"{}"

            def json(self):
                return {}

        return _R()


original_client = hubcap.requests
original_interval = hubcap.MIN_REQUEST_INTERVAL
try:
    from concurrent.futures import ThreadPoolExecutor

    hubcap.requests = _FakeClient()
    hubcap.MIN_REQUEST_INTERVAL = 0.05
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: hubcap.request(f"https://x/manifest/{i}/contents"), range(8)))
    gaps = [stamps[i + 1] - stamps[i] for i in range(len(stamps) - 1)]
    check("concurrent requests never overlap the pacing gate", len(stamps), 8)
    check("every gap honours the minimum interval",
          all(gap >= hubcap.MIN_REQUEST_INTERVAL * 0.9 for gap in gaps), True)
finally:
    hubcap.requests = original_client
    hubcap.MIN_REQUEST_INTERVAL = original_interval

print()
if fails:
    print("\n".join(fails))
    sys.exit(1)
print("all update-check cases pass")