"""Wirecutter fallback classification.

The proxy retry is only correct when the direct route was genuinely blocked.
A rate limit, an auth failure or a TLS misconfiguration must NOT be retried
through a second host: it would double-burn quota or mask the real error.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uran_backend import hubcap
from uran_backend.http import ConnectionError_, RequestError, Timeout

class _Status(Exception):
    """Stands in for a response-shaped error carrying an HTTP status."""

    def __init__(self, msg, status_code=400):
        super().__init__(msg)
        self.status_code = status_code


CASES = [
    (ConnectionError_("Connection refused"), True, "connection refused"),
    (ConnectionError_("Connection reset by peer"), True, "reset"),
    (ConnectionError_("Temporary failure in name resolution"), True, "DNS blip"),
    (ConnectionError_("Name or service not known"), True, "DNS NXDOMAIN"),
    (ConnectionError_("nodename nor servname provided"), True, "DNS legacy"),
    (ConnectionError_("getaddrinfo failed"), True, "getaddrinfo"),
    (ConnectionError_("Network is unreachable"), True, "no route"),
    (ConnectionError_("No route to host"), True, "no host"),
    (ConnectionError_("Host is unreachable"), True, "host unreachable"),
    (ConnectionError_("SSL: CERTIFICATE_VERIFY_FAILED"), True, "TLS interception"),
    (ConnectionError_("ssl.SSLError: handshake failure"), True, "TLS handshake"),
    (Timeout("timed out"), True, "route silently dropped packets"),

    # --- HTTP-level problems: the route works, so do NOT retry elsewhere ---
    (_Status("rate limited", 429), False, "rate limit - retrying elsewhere double-burns quota"),
    (_Status("unauthorized", 401), False, "bad key - proxy would 401 identically"),
    (_Status("forbidden", 403), False, "forbidden"),
    (_Status("not found", 404), False, "not found"),
    (_Status("server error", 500), False, "server error"),
    (_Status("bad gateway", 502), False, "bad gateway"),
    (RequestError("programming error"), False, "bug, not a network problem"),
]

fails = []
for exc, expected, label in CASES:
    actual = hubcap.is_blocked_transport_error(exc)
    mark = "ok " if actual == expected else "FAIL"
    if actual != expected:
        fails.append(f"{mark} {type(exc).__name__}: {label} -> got {actual}, want {expected}")
    else:
        print(f"{mark} fallback={str(actual):5} {label}")

print()
if fails:
    print("\n".join(fails))
    sys.exit(1)
print(f"all {len(CASES)} classification cases pass")