"""Short-lived LAN key capture and Hubcap key management."""

import json
import re
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def bind_core(core) -> None:
    """Bind shared settings, HTTP and filesystem services from main.py."""
    names = (
        "logger", "requests", "HUBCAP_BASE_URL", "_detect_assella_canary_hubcap_key",
        "_write_accela_api_key", "_settings_write_lock", "_load_settings", "_save_settings",
        "_stored_hubcap_key", "_accela_conf_candidates", "_read_ini_value",
    )
    globals().update({name: getattr(core, name) for name in names})


# Local key-capture server ("Show QR code")
#
# In Gaming Mode there is no keyboard, so pasting a 100-char API key is painful.
# This serves a one-page form on the LAN; the Decky UI shows a QR code of its
# URL, the phone scans it and posts the key back. The server is short-lived:
# it binds to one random high port, requires a per-session token in the URL,
# and shuts itself down shortly after a successful submission.
#
# The key is validated against Hubcap's /depot-keys (authenticated, zero quota)
# before being stored. /health is NOT used: it is unauthenticated and returns
# 200 for any input, so it cannot prove a key is valid.
# ---------------------------------------------------------------------------
_KEYCARE_PORT_RANGE = (38500, 38600)
_KEYCARE_TTL_SECONDS = 300

_keycare_state: dict = {
    "running": False,
    "port": None,
    "token": None,
    "started_at": None,
    "urls": [],
    "status": "idle",
    "error": None,
    "keys_added": 0,
}
_keycare_server = None
_keycare_lock = threading.Lock()

def _lan_ip_addresses() -> list[str]:
    """Best-effort LAN IPv4 addresses a phone on the same Wi-Fi can reach.

    Avoids a full netifaces dependency: connect a UDP socket (sends nothing) to
    a public address and read the local end the kernel picked.
    """
    found: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.4)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                found.append(ip)
        finally:
            s.close()
    except Exception as e:
        logger.debug("UDP route probe failed: %s", e)

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("192.168.") or ip.startswith("10.") or re.match(r"^172\.(1[6-9]|2\d|3[01])\.", ip):
                if ip not in found:
                    found.append(ip)
    except Exception as e:
        logger.debug("hostname resolution failed: %s", e)

    # Private ranges only: 127.x and docker bridges are useless to a phone.
    return [ip for ip in found if not ip.startswith("127.")]

def _keycare_page(token: str) -> str:
    """Minimal self-contained form (no external assets, works offline)."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Uran · Hubcap key</title>
<style>
 body{{margin:0;font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
   background:#0e1116;color:#e6e6e6;display:flex;min-height:100vh;align-items:center;justify-content:center}}
 .card{{width:100%;max-width:520px;padding:24px}}
 h1{{font-size:20px;margin:0 0 4px}}
 p.sub{{color:#9aa4b2;margin:0 0 20px;font-size:14px}}
 label{{display:block;font-size:13px;color:#9aa4b2;margin-bottom:6px}}
 input{{width:100%;padding:14px;font-size:16px;border-radius:10px;border:1px solid #2a313c;
   background:#161b22;color:#e6e6e6;box-sizing:border-box}}
 input:focus{{outline:2px solid #1f6feb;border-color:transparent}}
 button{{width:100%;margin-top:14px;padding:14px;font-size:16px;font-weight:600;border:0;border-radius:10px;
   background:#1f6feb;color:#fff;cursor:pointer}}
 button:disabled{{opacity:.55}}
 .msg{{margin-top:16px;padding:12px;border-radius:10px;font-size:14px;display:none}}
 .ok{{display:block;background:#12331f;color:#7ee2a8;border:1px solid #1d5c37}}
 .err{{display:block;background:#3a1a1a;color:#ff9a9a;border:1px solid #6b2b2b}}
 .note{{color:#6b7684;font-size:12px;margin-top:18px}}
 code{{background:#161b22;padding:2px 6px;border-radius:4px}}
</style></head><body><div class="card">
<h1>Hubcap API key</h1>
<p class="sub">Paste your key below. It is checked against Hubcap, then stored
by Uran on your Steam Deck.</p>
<label for="k">API key</label>
<input id="k" type="password" inputmode="text" autocomplete="off"
       autocapitalize="off" autocorrect="off" spellcheck="false" placeholder="smm_...">
<button id="go">Submit</button>
<div id="m" class="msg"></div>
<p class="note">Get a key at <code>hubcapmanifest.com</code>. This page is
served by your Deck and closes automatically once the key is accepted.</p>
</div><script>
const TOKEN={token!r};
const inp=document.getElementById('k'),btn=document.getElementById('go'),m=document.getElementById('m');
function show(t,ok){{m.textContent=t;m.className='msg '+(ok?'ok':'err');}}
btn.onclick=async ()=>{{
 const k=inp.value.trim();
 if(!k){{show('Please paste a key first.',false);return;}}
 btn.disabled=true;btn.textContent='Checking…';show('Checking key with Hubcap…',true);
 try{{
  const r=await fetch('/submit',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{token:TOKEN,key:k}})}});
  const j=await r.json();
  if(j.ok){{show(j.message||'Key accepted.',true);btn.textContent='Done';inp.readOnly=true;}}
  else{{show(j.error||'Rejected.',false);btn.disabled=false;btn.textContent='Submit';}}
 }}catch(e){{show('Could not reach the Deck. Is it still on the same network?',false);
  btn.disabled=false;btn.textContent='Submit';}}
}};
inp.focus();
</script></body></html>"""

class _KeycareHandler(BaseHTTPRequestHandler):
    """Handles the phone's GET / and POST /submit."""

    server_version = "Uran"

    def log_message(self, fmt, *args):  # keep the key out of the Decky log
        logger.debug("keycare %s - %s", self.address_string(), fmt % args)

    def _send(self, code: int, body: str, ctype: str = "text/html; charset=utf-8") -> None:
        raw = body.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        token = _keycare_state.get("token")
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path != "/":
            return self._send(404, "not found", "text/plain")
        supplied = ""
        if "?" in self.path:
            for part in self.path.split("?", 1)[1].split("&"):
                if part.startswith("token="):
                    supplied = part[6:]
        # Same-origin token check: a bare scan from an untrusted device fails.
        if not token or supplied != token:
            return self._send(403, "Invalid or expired link.", "text/plain; charset=utf-8")
        self._send(200, _keycare_page(token))

    def do_POST(self):
        if self.path.split("?")[0].rstrip("/") != "/submit":
            return self._send(404, "not found", "text/plain")
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 8192:
                return self._send(400, "bad request", "text/plain")
            payload = json.loads(self.rfile.read(length).decode("utf-8", "replace"))
        except Exception:
            return self._send(400, "bad request", "text/plain")

        if payload.get("token") != _keycare_state.get("token"):
            return self._send(403, json.dumps({"ok": False, "error": "Invalid session."}),
                              "application/json")

        key = str(payload.get("key") or "").strip()
        if not key:
            return self._send(400, json.dumps({"ok": False, "error": "No key supplied."}),
                              "application/json")

        ok, message, detail = validate_hubcap_key(key)
        if not ok:
            _keycare_state["status"] = "rejected"
            return self._send(200, json.dumps({"ok": False, "error": message}),
                              "application/json")

        stored_ok, where = save_hubcap_key(key)
        logger.info("Hubcap key accepted via local QR capture (%s)", where)
        _keycare_state["status"] = "accepted" if stored_ok else "accepted_unstored"
        _keycare_state["stored_in"] = where
        _schedule_keycare_shutdown(delay=20)
        return self._send(200, json.dumps({
            "ok": True,
            "message": f"{message} Saved — shared with ASSella.",
        }), "application/json")

def validate_hubcap_key(key: str) -> tuple[bool, str, str]:
    """Validate a Hubcap API key via /user/stats (same endpoint ASSella uses).

    Returns (ok, message, detail_json). /user/stats is authenticated, consumes
    no generation quota, and reports the owning account so we can confirm the
    right key was pasted. (/health cannot be used: it is unauthenticated and
    answers 200 for any input.)
    """
    key = str(key or "").strip()
    if not key:
        return False, "No key supplied.", ""
    try:
        resp = requests.get(
            f"{HUBCAP_BASE_URL}/user/stats",
            headers={"Authorization": f"Bearer {key}"},
            timeout=20,
        )
    except Exception as e:
        return False, f"Could not reach Hubcap: {e}", ""

    if resp.status_code == 200:
        try:
            data = resp.json()
        except Exception:
            return True, "Key is valid.", ""
        user = data.get("username") or data.get("user_id") or "unknown"
        used = data.get("daily_usage")
        limit = data.get("daily_limit")
        can = data.get("can_make_requests", True)
        parts = [f"Key is valid — {user}"]
        if used is not None and limit:
            parts.append(f"{used}/{limit} requests today")
        if not can:
            return False, f"Key belongs to {user} but is not allowed to make requests.", ""
        return True, " · ".join(parts) + ".", json.dumps(data)
    if resp.status_code in (401, 403):
        detail = ""
        try:
            detail = (resp.json() or {}).get("detail") or ""
        except Exception:
            pass
        return False, detail or "Hubcap rejected this key (401).", str(resp.status_code)
    if resp.status_code == 429:
        return False, "Hubcap rate limit reached. Try again later.", str(resp.status_code)
    return False, f"Unexpected Hubcap response (HTTP {resp.status_code}).", str(resp.status_code)

def get_hubcap_user_stats() -> dict:
    """Account stats for the currently configured key (via /user/stats)."""
    key = _detect_assella_canary_hubcap_key()
    if not key:
        return {"ok": False, "error": "No key configured"}
    ok, message, detail = validate_hubcap_key(key)
    if not ok:
        return {"ok": False, "error": message}
    try:
        data = json.loads(detail) if detail else {}
    except Exception:
        data = {}
    daily = data.get("daily_usage")
    limit = data.get("daily_limit")
    remaining = None
    if isinstance(daily, int) and isinstance(limit, int):
        remaining = max(0, limit - daily)
    expires = data.get("api_key_expires_at") or ""
    if expires:
        # Trim the ISO timestamp to something readable.
        try:
            expires = expires.split(".")[0].replace("T", " ").strip()
        except Exception:
            pass
    return {
        "ok": True,
        "username": data.get("username") or "",
        "daily_usage": daily,
        "daily_limit": limit,
        "requests_remaining": remaining,
        "expires_at": expires,
        "can_make_requests": bool(data.get("can_make_requests", True)),
    }

def save_hubcap_key(key: str) -> tuple[bool, str]:
    """Validate and persist a key into ACCELA's config (shared with ASSella).

    Returns (ok, message).
    """
    key = str(key or "").strip()
    ok, message, _ = validate_hubcap_key(key)
    if not ok:
        return False, message

    wrote, where = _write_accela_api_key(key)
    with _settings_write_lock:
        s = _load_settings()
        s["manifest_api_key"] = "" if wrote else key
        _save_settings(s)
    return True, where

def _schedule_keycare_shutdown(delay: int) -> None:
    def _stop():
        time.sleep(delay)
        stop_keycare_server()
    threading.Thread(target=_stop, daemon=True).start()

def stop_keycare_server() -> dict:
    """Shut the local capture server down."""
    global _keycare_server
    with _keycare_lock:
        srv = _keycare_server
        _keycare_server = None
    if srv is not None:
        try:
            srv.shutdown()
            srv.server_close()
        except Exception as e:
            logger.debug("keycare shutdown: %s", e)
    _keycare_state.update({"running": False, "port": None, "token": None, "urls": []})
    return {"ok": True}

def start_keycare_server() -> dict:
    """Start the local capture server and return the URLs to encode as a QR."""
    global _keycare_server
    with _keycare_lock:
        if _keycare_server is not None:
            return {"ok": True, **get_keycare_status()}

        token = secrets.token_urlsafe(24)
        httpd = None
        last_err = None
        lo, hi = _KEYCARE_PORT_RANGE
        for port in range(lo, hi):
            try:
                httpd = ThreadingHTTPServer(("0.0.0.0", port), _KeycareHandler)
                break
            except OSError as e:
                last_err = e
                continue
        if httpd is None:
            _keycare_state.update({"status": "error", "error": f"No free port: {last_err}"})
            return {"ok": False, "error": _keycare_state["error"]}

        httpd.daemon_threads = True
        _keycare_server = httpd
        port = httpd.server_address[1]
        urls = [f"http://{ip}:{port}/?token={token}" for ip in _lan_ip_addresses()]
        _keycare_state.update({
            "running": True,
            "port": port,
            "token": token,
            "started_at": time.time(),
            "urls": urls,
            "status": "waiting",
            "error": None,
            "keys_added": 0,
        })
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.3},
                         daemon=True).start()
        logger.info("Local key-capture server listening on port %d", port)

        # Auto-expire so we are not listening indefinitely.
        _schedule_keycare_shutdown(delay=_KEYCARE_TTL_SECONDS)

        if not urls:
            logger.warning("No LAN address detected; QR may not be reachable from a phone")
        return {"ok": True, **get_keycare_status()}

def get_keycare_status() -> dict:
    st = dict(_keycare_state)
    started = st.get("started_at")
    if started:
        st["expires_in"] = max(0, int(_KEYCARE_TTL_SECONDS - (time.time() - started)))
    # Never expose the token to logs/UI beyond what the URL already carries.
    st.pop("token", None)
    return st

def get_hubcap_key_status() -> dict:
    """Report where the Hubcap key came from, for the settings UI."""
    stored = _stored_hubcap_key()
    detected = ""
    source = ""
    for p in _accela_conf_candidates():
        if p.is_file():
            detected = _read_ini_value(p, "morrenus_api_key")
            if detected:
                source = str(p)
                break
    if stored:
        origin, masked = "plugin override", stored
    elif detected:
        origin, masked = f"ACCELA ({source})", detected
    else:
        origin, masked = "not found", ""
    return {
        "ok": bool(stored or detected),
        "source": origin,
        "configured_path": source,
        "masked": (masked[:8] + "..." + masked[-4:]) if len(masked) > 14 else masked,
        "is_override": bool(stored),
        "base_url": HUBCAP_BASE_URL,
    }
