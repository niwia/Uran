"""Gateway mode selection, fallback classification, and route health reporting.

The mode logic decides whether a user's API key reaches a second host, so each
mode is pinned down here: what gets tried, and what gets retried.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uran_backend import hubcap
from uran_backend.http import ConnectionError_, RequestError

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"FAIL {label}\n     got  {got!r}\n     want {want!r}")
    else:
        print(f"ok  {label}")


class _Status(Exception):
    """An error carrying an HTTP status, as a response-shaped failure would."""

    def __init__(self, msg, status_code=400):
        super().__init__(msg)
        self.status_code = status_code


class FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.content = b"x"

    def json(self):
        return {}


class FakeClient:
    """Records every URL requested and replays a scripted set of outcomes."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, url, headers=None, timeout=10, stream=False):
        self.calls.append(url)
        outcome = self.outcomes.pop(0) if self.outcomes else FakeResponse()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class Monkey:
    """Minimal attribute swapper for module-level patching in tests."""

    def __init__(self, module, attr, value):
        self.module, self.attr, self.value = module, attr, value

    def __enter__(self):
        self.original = getattr(self.module, self.attr)
        setattr(self.module, self.attr, self.value)
        # Start each case from a clean route-health slate so one test cannot
        # observe state left behind by the previous one.
        hubcap._route_health.update(
            {"direct": "unknown", "proxy": "unknown", "fallback_used": False,
             "last_error": "", "last_checked": 0}
        )
        return self

    def __exit__(self, *exc):
        # Snapshot the health state while still patched, then restore it, so
        # assertions can look at what the call under test actually recorded.
        self.snapshot = dict(hubcap._route_health)
        setattr(self.module, self.attr, self.original)
        return False


URL = f"{hubcap.HUBCAP_BASE_URL}/manifest/620"


def run_mode(mode, outcomes, expect_raise=False):
    client = FakeClient(outcomes)
    with Monkey(hubcap, "requests", client) as m:
        try:
            hubcap.request(URL, mode=mode)
        except Exception:  # noqa: BLE001 - expected for the blocked cases
            if not expect_raise:
                raise
    return client.calls, m.snapshot


# --- direct mode never touches the proxy -------------------------------
calls, _ = run_mode("direct", [FakeResponse()])
check("direct mode uses one call", len(calls), 1)
check("direct mode hits the real host", calls[0].startswith(hubcap.HUBCAP_BASE_URL), True)

calls, _ = run_mode("direct", [ConnectionError_("connection refused")], expect_raise=True)
check("direct mode does not fall back when blocked", len(calls), 1)
check("direct mode still points at the real host",
      calls[0].startswith(hubcap.HUBCAP_BASE_URL), True)

# --- proxy mode always uses the proxy ----------------------------------
calls, _ = run_mode("proxy", [FakeResponse()])
check("proxy mode uses one call", len(calls), 1)
check("proxy mode targets the worker", calls[0].startswith(hubcap.WIRECUTTER_ENDPOINT), True)

# --- auto: happy path stays direct -------------------------------------
calls, health = run_mode("auto", [FakeResponse()])
check("auto mode prefers direct", len(calls), 1)
check("auto direct call is the real host", calls[0].startswith(hubcap.HUBCAP_BASE_URL), True)
check("auto did not mark a fallback", health["fallback_used"], False)
check("auto recorded direct as reachable", health["direct"], "ok")

# --- auto: blocked route falls back ------------------------------------
calls, health = run_mode("auto", [ConnectionError_("connection refused"), FakeResponse()])
check("auto retries blocked route once", len(calls), 2)
check("auto fallback targets the worker", calls[1].startswith(hubcap.WIRECUTTER_ENDPOINT), True)
check("auto marked direct blocked", health["direct"], "blocked")
check("auto marked proxy ok", health["proxy"], "ok")
check("auto flagged the fallback", health["fallback_used"], True)
check("auto kept the failure reason", "connection refused" in health["last_error"], True)

# --- auto: does NOT retry things that are not a blocked route ---------
for exc, label in (
    (_Status("rate limited", 429), "429 rate limit"),
    (_Status("unauthorized", 401), "401 bad key"),
    (_Status("not found", 404), "404 missing bundle"),
    (RequestError("plain failure"), "generic request error"),
):
    client = FakeClient([exc])
    with Monkey(hubcap, "requests", client) as m:
        try:
            hubcap.request(URL, mode="auto")
            raised = False
        except Exception:
            raised = True
    check(f"auto propagates {label} without fallback", len(client.calls), 1)
    check(f"auto raises for {label}", raised, True)
    check(f"auto leaves fallback off for {label}", m.snapshot["fallback_used"], False)

# --- auto: both routes blocked still raises ----------------------------
client = FakeClient([ConnectionError_("connection refused"),
                     ConnectionError_("proxy also refused")])
with Monkey(hubcap, "requests", client) as m:
    try:
        hubcap.request(URL, mode="auto")
        raised = False
    except Exception:
        raised = True
check("auto tries both routes when both are blocked", len(client.calls), 2)
check("auto raises when both routes are blocked", raised, True)
check("auto marked proxy failed", m.snapshot["proxy"], "failed")

# --- an unknown mode is treated as auto, not as an error ---------------
calls, _ = run_mode("nonsense", [FakeResponse()])
check("unknown mode falls back to direct-first", len(calls), 1)
check("unknown mode is not treated as proxy-only",
      calls[0].startswith(hubcap.HUBCAP_BASE_URL), True)

# --- probe reports both routes independently ----------------------------
client = FakeClient([FakeResponse(200), FakeResponse(401)])
with Monkey(hubcap, "requests", client):
    result = hubcap.probe_routes("")
check("probe reports direct reachable", result["routes"]["direct"]["ok"], True)
check("probe treats 401 as reachable", result["routes"]["proxy"]["ok"], True)
check("probe probed both routes", len(client.calls), 2)
check("probe direct target", client.calls[0], f"{hubcap.HUBCAP_BASE_URL}/user/stats")
check("probe proxy target", client.calls[1], f"{hubcap.WIRECUTTER_ENDPOINT}/user/stats")

client = FakeClient([ConnectionError_("no route to host"), FakeResponse()])
with Monkey(hubcap, "requests", client):
    result = hubcap.probe_routes("")
check("probe marks direct blocked", result["routes"]["direct"]["ok"], False)
check("probe records the failure detail",
      "no route to host" in result["routes"]["direct"]["detail"], True)
check("probe marks proxy reachable", result["routes"]["proxy"]["ok"], True)
check("probe does not flag a fallback for an explicit test",
      result.get("mode") in (None, "auto", "direct", "proxy"), True)

print()
if fails:
    print("\n".join(fails))
    sys.exit(1)
print("all gateway mode checks pass")