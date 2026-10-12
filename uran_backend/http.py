"""HTTP client for Uran.

Decky does not bundle third-party Python packages into a plugin's runtime, so
`requests` is usually absent. Rather than take a dependency on a vendored copy
(the old `defaults/python` bootstrap, which never actually shipped because the
directory is gitignored and absent from the packaging script), we fall back to
a small urllib shim that mirrors the slice of the `requests` API this plugin
uses.

The shim deliberately mimics `requests` *including its exception namespace* —
callers catch `http.RequestError` (or `requests.exceptions.ConnectionError`
where they use the real library), and a missing `.exceptions` attribute turns
the handler itself into an AttributeError.
"""

import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class RequestError(Exception):
    """Stand-in for requests.RequestException."""


class ConnectionError_(RequestError):
    """Stand-in for requests.exceptions.ConnectionError."""


class Timeout(RequestError):
    """Stand-in for requests.exceptions.Timeout."""


class _Exceptions:
    """Stand-in for the `requests.exceptions` module namespace."""

    RequestException = RequestError
    ConnectionError = ConnectionError_
    Timeout = Timeout


exceptions = _Exceptions()


def _build_ssl_context():
    for cafile in (
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/pki/tls/certs/ca-bundle.crt",
        "/etc/ssl/cert.pem",
    ):
        if os.path.exists(cafile):
            try:
                return ssl.create_default_context(cafile=cafile)
            except Exception:  # noqa: BLE001 - try the next candidate
                pass
    try:
        return ssl.create_default_context()
    except Exception:  # noqa: BLE001 - fall back to the stdlib default
        return None


_SSL_CTX = _build_ssl_context()


class _Response:
    """Stand-in for requests.Response, built from a urllib response."""

    def __init__(self, status: int, headers: dict, content: bytes):
        self.status_code = status
        self.headers = headers
        self.content = content
        self.text = content.decode("utf-8", errors="replace")

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        import json

        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if not self.ok:
            raise RequestError(f"HTTP {self.status_code}")


def _open(req: urllib.request.Request, timeout: int) -> _Response:
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
            return _Response(resp.status, dict(resp.headers), resp.read())
    except urllib.error.HTTPError as exc:
        # An HTTP error is still a response the caller wants to inspect.
        return _Response(exc.code, dict(exc.headers), exc.read())
    except TimeoutError as exc:
        raise Timeout(str(exc)) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (TimeoutError, OSError)) and "timed out" in str(reason).lower():
            raise Timeout(str(reason)) from exc
        raise ConnectionError_(str(reason)) from exc
    except OSError as exc:
        raise ConnectionError_(str(exc)) from exc


class _Shim:
    """The slice of the requests API Uran actually uses."""

    RequestException = RequestError
    exceptions = _Exceptions()

    @staticmethod
    def get(url, params=None, headers=None, timeout=10, stream=False, verify=True):
        if params:
            query = urllib.parse.urlencode(params)
            url = f"{url}?{query}" if "?" not in url else f"{url}&{query}"
        hdrs = dict(headers or {})
        hdrs.setdefault("User-Agent", BROWSER_UA)
        # verify=False cannot be honoured without disabling the CA bundle, and
        # silently downgrading TLS to satisfy an optional flag is not worth it.
        if not verify:
            hdrs.setdefault("X-Uran-Ignore-Tls", "1")
        return _open(urllib.request.Request(url, headers=hdrs), timeout)

    @staticmethod
    def post(url, data=None, json=None, headers=None, timeout=10):
        req_headers = dict(headers or {})
        body = None
        if json is not None:
            import json as _json

            body = _json.dumps(json).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        elif data is not None:
            if isinstance(data, dict):
                body = urllib.parse.urlencode(data).encode("utf-8")
                req_headers["Content-Type"] = "application/x-www-form-urlencoded"
            elif isinstance(data, bytes):
                body = data
            elif isinstance(data, str):
                body = data.encode("utf-8")
        req_headers.setdefault("User-Agent", BROWSER_UA)
        req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
        return _open(req, timeout)


try:  # pragma: no cover - depends on the host's Python environment
    import requests  # type: ignore

    HAS_REQUESTS = True
except ImportError:  # pragma: no cover - the normal Decky path
    requests = _Shim()  # type: ignore[assignment]
    HAS_REQUESTS = False