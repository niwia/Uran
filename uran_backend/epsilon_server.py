"""Epsilon Bridge HTTP server engine.

Exposes a lightweight, secure REST API on 127.0.0.1:1952 allowing the Photar
browser userscript to trigger game injections, status checks, and config syncs
directly via the Uran backend engine.
"""

import asyncio
import json
import logging
import os
import re
import socket
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

logger = logging.getLogger("Epsilon")

DEFAULT_PORT = 1952
DEFAULT_HOST = "127.0.0.1"
DEFAULT_IDLE_TIMEOUT = 120  # Exit after 120 seconds of inactivity under systemd socket

ALLOWED_HOSTS = {
    f"127.0.0.1:{DEFAULT_PORT}",
    f"localhost:{DEFAULT_PORT}",
    "127.0.0.1",
    "localhost",
}

ALLOWED_ORIGINS = {
    "https://store.steampowered.com",
    "https://steamdb.info",
}


def is_port_in_use(port: int = DEFAULT_PORT, host: str = DEFAULT_HOST) -> bool:
    """Check if the Epsilon bridge port is already active."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        try:
            s.connect((host, port))
            return True
        except (OSError, ConnectionRefusedError):
            return False


def get_systemd_listen_fd() -> socket.socket | None:
    """Detect and return socket passed via systemd socket activation (SD_LISTEN_FDS_START=3)."""
    listen_pid = os.environ.get("LISTEN_PID")
    listen_fds = os.environ.get("LISTEN_FDS")
    if listen_pid and listen_fds:
        try:
            if int(listen_pid) == os.getpid() and int(listen_fds) >= 1:
                return socket.fromfd(3, socket.AF_INET, socket.SOCK_STREAM)
        except Exception as exc:
            logger.debug("Failed parsing systemd listen fds: %s", exc)
    return None


def dispatch_request(
    services, method: str, path: str, body_bytes: bytes, headers: dict
) -> tuple[int, dict, dict]:
    """Pure request dispatcher shared by both standalone and async embedded servers.

    Returns:
        (status_code, response_data, response_headers)
    """
    # Normalize headers to lowercase
    norm_headers = {str(k).lower(): str(v).strip() for k, v in headers.items()}
    host = norm_headers.get("host", "")
    origin = norm_headers.get("origin", "")

    # Security Check 1: Host header validation (Defeats DNS-rebinding attacks)
    if host and host not in ALLOWED_HOSTS:
        return 403, {"ok": False, "error": "Forbidden: invalid Host header"}, {}

    # Security Check 2: Origin header validation (Defeats arbitrary web page cross-origin requests)
    if origin and origin not in ALLOWED_ORIGINS:
        return 403, {"ok": False, "error": "Forbidden: unauthorized Origin"}, {}

    # Build safe CORS headers if caller provided a recognized Origin
    resp_headers = {}
    if origin in ALLOWED_ORIGINS:
        resp_headers["Access-Control-Allow-Origin"] = origin
        resp_headers["Vary"] = "Origin"
        resp_headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp_headers["Access-Control-Allow-Headers"] = "Content-Type, X-Photar-Client"

    parsed = urllib.parse.urlparse(path)
    route = parsed.path.rstrip("/") or "/"
    query = urllib.parse.parse_qs(parsed.query)

    # 1. CORS Preflight
    if method == "OPTIONS":
        return 200, {"ok": True}, resp_headers

    # 2. Handshake / Health Ping
    if method == "GET" and route in ("/ping", "/health"):
        readiness = {}
        try:
            readiness = services.guards.check_system_readiness()
        except Exception:
            try:
                gate = services.guards.check_sls_environment()
                readiness = {"ready": bool(gate.get("ok")), "sls_active": bool(gate.get("ok"))}
            except Exception:
                readiness = {"ready": False, "error_code": "505"}

        from .updates import plugin_version

        version = plugin_version(services.ctx)
        ready = bool(readiness.get("ready"))
        error_code = readiness.get("error_code")
        error_msg = readiness.get("error")
        guide_url = (
            f"https://assella.niwia.top/epsilon#err-{error_code}"
            if error_code
            else "https://assella.niwia.top/epsilon"
        )

        return (
            200,
            {
                "ok": True,
                "service": "epsilon",
                "version": version,
                "engine": "uran_backend",
                "sls_active": readiness.get("sls_active", True),
                "sls_installed": error_code not in ("501", "504"),
                "has_plugins": error_code != "502",
                "has_hubcap_key": bool(services.ctx.hubcap_key.current()),
                "ready": ready,
                "error_code": error_code,
                "error": error_msg,
                "guide_url": guide_url,
            },
            resp_headers,
        )

    # 3. Game Status Check
    if method == "GET" and route == "/status":
        app_id_list = query.get("appid") or query.get("app_id") or []
        if not app_id_list:
            return 400, {"ok": False, "error": "Missing 'appid' query parameter"}, resp_headers
        raw_id = str(app_id_list[0]).strip()
        from .sls_config import sanitize_id

        aid = sanitize_id(raw_id)
        if not aid:
            return 400, {"ok": False, "error": f"Invalid AppID: {raw_id}"}, resp_headers

        readiness = {}
        try:
            readiness = services.guards.check_system_readiness()
        except Exception:
            pass

        ready = bool(readiness.get("ready", True))
        error_code = readiness.get("error_code")
        error_msg = readiness.get("error")

        added = bool(services.guards.is_app_added(aid))
        inject_status = services.injector.status(aid)
        details = services.steam.app_details(aid) or {}
        name = details.get("name", f"App {aid}")

        # Check if recent inject attempt failed
        if inject_status and inject_status.get("done") and inject_status.get("error"):
            runtime_err = str(inject_status.get("error", ""))
            if "401" in runtime_err or "Invalid Hubcap API key" in runtime_err:
                error_code = "401"
            elif "404" in runtime_err or "No Hubcap bundle" in runtime_err:
                error_code = "404"
            elif "429" in runtime_err or "rate limit" in runtime_err.lower():
                error_code = "429"
            elif "no keys" in runtime_err.lower():
                error_code = "701"
            else:
                error_code = "707"
            error_msg = runtime_err

        guide_url = (
            f"https://assella.niwia.top/epsilon#err-{error_code}"
            if error_code
            else "https://assella.niwia.top/epsilon"
        )

        return (
            200,
            {
                "ok": True,
                "appid": aid,
                "name": name,
                "added": added,
                "inject_status": inject_status,
                "ready": ready and not error_code,
                "error_code": error_code,
                "error": error_msg,
                "guide_url": guide_url,
            },
            resp_headers,
        )

    # Helper for parsing JSON payloads
    def _parse_json_payload():
        if not body_bytes:
            return None, "Empty request body"
        try:
            return json.loads(body_bytes.decode("utf-8")), None
        except Exception as exc:
            return None, f"Malformed JSON: {exc}"

    # 4. Inject Game
    if method == "POST" and route == "/inject":
        payload, err = _parse_json_payload()
        if err:
            return 400, {"ok": False, "error": err}, resp_headers
        raw_id = str(payload.get("appid") or payload.get("app_id") or "").strip()
        from .sls_config import sanitize_id

        aid = sanitize_id(raw_id)
        if not aid:
            return 400, {"ok": False, "error": f"Invalid AppID: {raw_id}"}, resp_headers

        result = services.injector.inject(aid)
        if result.get("error"):
            # Return 400 for errors, unless it's already added which is a normal check
            status_code = 200 if result.get("already_added") else 400
            err_text = str(result.get("error", ""))
            blocked = result.get("blocked")
            err_code = "707"
            if blocked == "no_api_key" or "401" in err_text:
                err_code = "401"
            elif blocked == "no_sls_config":
                err_code = "504"
            elif blocked in ("sls_not_installed", "sls_inactive"):
                err_code = "501"
            elif blocked == "plugins_disabled":
                err_code = "503"
            elif blocked == "no_lua_plugins":
                err_code = "502"
            elif "404" in err_text or "No Hubcap bundle" in err_text:
                err_code = "404"
            elif "429" in err_text:
                err_code = "429"
            elif "no keys" in err_text.lower():
                err_code = "701"

            resp_body = {
                "ok": False,
                "error": result["error"],
                "error_code": err_code if not result.get("already_added") else None,
                "already_added": result.get("already_added", False),
                "blocked": result.get("blocked"),
                "guide_url": f"https://assella.niwia.top/epsilon#err-{err_code}",
            }
            return (
                status_code,
                resp_body,
                resp_headers,
            )
        return (
            200,
            {
                "ok": True,
                "name": result.get("name"),
                "depots": result.get("depots", []),
                "fetching": result.get("fetching", True),
            },
            resp_headers,
        )

    # 5. Refresh Game Config
    if method == "POST" and route == "/refresh":
        payload, err = _parse_json_payload()
        if err:
            return 400, {"ok": False, "error": err}, resp_headers
        raw_id = str(payload.get("appid") or payload.get("app_id") or "").strip()
        from .sls_config import sanitize_id

        aid = sanitize_id(raw_id)
        if not aid:
            return 400, {"ok": False, "error": f"Invalid AppID: {raw_id}"}, resp_headers

        result = services.injector.refresh(aid)
        code = 200 if result.get("ok", True) else 400
        return code, {"ok": result.get("ok", True), "result": result}, resp_headers

    # 6. Refetch Fresh Hubcap Bundle
    if method == "POST" and route == "/refetch":
        payload, err = _parse_json_payload()
        if err:
            return 400, {"ok": False, "error": err}, resp_headers
        raw_id = str(payload.get("appid") or payload.get("app_id") or "").strip()
        from .sls_config import sanitize_id

        aid = sanitize_id(raw_id)
        if not aid:
            return 400, {"ok": False, "error": f"Invalid AppID: {raw_id}"}, resp_headers

        result = services.injector.refetch_game(aid)
        code = 200 if result.get("ok", False) else 400
        return code, {"ok": result.get("ok", False), "result": result}, resp_headers

    return 404, {"ok": False, "error": f"Unknown route: {method} {route}"}, resp_headers


class StandaloneHTTPHandler(BaseHTTPRequestHandler):
    """Sync HTTP handler for standalone execution or systemd socket activation."""

    services = None
    on_activity = None

    def _notify_activity(self):
        if callable(self.on_activity):
            self.on_activity()

    def _send_response_json(self, status_code: int, data: dict, extra_headers: dict | None = None):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._notify_activity()
        code, resp, headers = dispatch_request(
            self.services, "OPTIONS", self.path, b"", dict(self.headers)
        )
        self._send_response_json(code, resp, headers)

    def do_GET(self):
        self._notify_activity()
        code, resp, headers = dispatch_request(
            self.services, "GET", self.path, b"", dict(self.headers)
        )
        self._send_response_json(code, resp, headers)

    def do_POST(self):
        self._notify_activity()
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b""
        code, resp, headers = dispatch_request(
            self.services, "POST", self.path, body, dict(self.headers)
        )
        self._send_response_json(code, resp, headers)

    def log_message(self, fmt, *args):
        # Clean log format to avoid polluting systemd journals
        logger.debug("[Epsilon-HTTP] " + fmt % args)


class ThreadedEpsilonHTTPServer(ThreadingMixIn, HTTPServer):
    """Threaded HTTP Server that can optionally inherit a pre-bound socket."""

    def __init__(self, server_address, RequestHandlerClass, inherited_socket=None):
        if inherited_socket is not None:
            self.address_family = inherited_socket.family
            # Skip bind and listen; systemd already performed them
            super().__init__(server_address, RequestHandlerClass, bind_and_activate=False)
            self.socket = inherited_socket
            self.server_address = inherited_socket.getsockname()
        else:
            super().__init__(server_address, RequestHandlerClass, bind_and_activate=True)


class AsyncEpsilonServer:
    """Non-blocking asyncio HTTP server for embedding directly inside Decky's event loop."""

    def __init__(self, services, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.services = services
        self.host = host
        self.port = port
        self.server = None

    async def start(self) -> bool:
        if is_port_in_use(self.port, self.host):
            logger.info("Port %s is already active; skipping embedded Epsilon loopback", self.port)
            return False

        try:
            self.server = await asyncio.start_server(self._handle_client, self.host, self.port)
            logger.info("Epsilon embedded loopback running on %s:%s", self.host, self.port)
            return True
        except Exception as exc:
            logger.warning(
                "Failed starting Epsilon embedded loopback on %s:%s: %s",
                self.host,
                self.port,
                exc,
            )
            return False

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
            logger.info("Epsilon embedded loopback stopped")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            line = await reader.readline()
            if not line:
                writer.close()
                return

            request_line = line.decode("utf-8", errors="replace").strip()
            parts = request_line.split(" ")
            if len(parts) < 2:
                writer.close()
                return

            method, path = parts[0], parts[1]
            headers = {}
            while True:
                header_line = await reader.readline()
                if not header_line or header_line in (b"\r\n", b"\n", b""):
                    break
                h_str = header_line.decode("utf-8", errors="replace").strip()
                if ":" in h_str:
                    k, v = h_str.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            content_len = int(headers.get("content-length", 0))
            body = b""
            if content_len > 0:
                body = await reader.readexactly(content_len)

            # Offload synchronous/network logic to a worker thread so Decky UI never freezes
            status_code, data, extra_headers = await asyncio.to_thread(
                dispatch_request, self.services, method, path, body, headers
            )
            body_out = json.dumps(data, indent=2).encode("utf-8")

            status_text = "OK" if status_code == 200 else ("Forbidden" if status_code == 403 else "Error")
            writer.write(f"HTTP/1.1 {status_code} {status_text}\r\n".encode("utf-8"))
            writer.write(b"Content-Type: application/json; charset=utf-8\r\n")
            writer.write(f"Content-Length: {len(body_out)}\r\n".encode("utf-8"))
            if extra_headers:
                for k, v in extra_headers.items():
                    writer.write(f"{k}: {v}\r\n".encode("utf-8"))
            writer.write(b"Connection: close\r\n\r\n")
            writer.write(body_out)
            await writer.drain()
        except Exception as exc:
            logger.debug("Error handling client in Epsilon async loopback: %s", exc)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


async def ensure_loopback_running(services, port: int = DEFAULT_PORT) -> AsyncEpsilonServer | None:
    """Helper for Uran Plugin._main() to ensure Epsilon endpoint is available."""
    server = AsyncEpsilonServer(services, port=port)
    started = await server.start()
    return server if started else None
