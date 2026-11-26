#!/usr/bin/env python3
"""Tests for Epsilon bridge server, security filters, and API endpoints."""

import json
import logging
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Allow imports from project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from uran_backend.epsilon_server import dispatch_request, is_port_in_use
from uran_backend import console_api, steam_store
from uran_backend.steam_store import StoreDebugger


class FakeSettings:
    """Minimal stand-in for Settings: the console only needs get/set/shared_secret."""

    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    def shared_secret(self, key):
        return str(self.data.get(key) or "")

    def set(self, key, value):
        self.data[key] = value


def _console_services(token="tok_test", **settings):
    services = MagicMock()
    fake = FakeSettings({"epsilon_console_token": token, **settings})
    services.ctx.settings = fake
    services.ctx.write_setting.side_effect = lambda key, value: fake.set(key, value)
    services.ctx.hubcap_key.current.return_value = "key_123"
    services.guards.get_added_app_ids.return_value = ["620"]
    services.injector.status.return_value = None
    return services


def _console_headers(token="tok_test", client=True):
    headers = {"Authorization": f"Bearer {token}"}
    if client:
        headers["X-At0m-Client"] = "1"
    return headers


def test_cors_preflight_allowed():
    mock_services = MagicMock()
    code, resp, headers = dispatch_request(
        mock_services, "OPTIONS", "/inject", b"", {"Origin": "https://store.steampowered.com"}
    )
    assert code == 200, f"Expected 200, got {code}"
    assert resp.get("ok") is True, f"Expected ok=True, got {resp}"
    assert headers.get("Access-Control-Allow-Origin") == "https://store.steampowered.com"
    print("ok  test_cors_preflight_allowed")


def test_malicious_origin_rejected():
    mock_services = MagicMock()
    # Cross-origin request from an untrusted domain should be rejected with 403
    code, resp, _ = dispatch_request(
        mock_services, "GET", "/status?appid=730", b"", {"Origin": "https://malicious-site.org"}
    )
    assert code == 403, f"Expected 403 Forbidden for untrusted origin, got {code}"
    assert resp.get("ok") is False
    print("ok  test_malicious_origin_rejected")


def test_dns_rebinding_host_rejected():
    mock_services = MagicMock()
    # Attacker attempting DNS rebinding by sending external Host header to 127.0.0.1
    code, resp, _ = dispatch_request(
        mock_services, "GET", "/ping", b"", {"Host": "attacker-domain.com:1952"}
    )
    assert code == 403, f"Expected 403 Forbidden for external Host, got {code}"
    assert resp.get("ok") is False
    print("ok  test_dns_rebinding_host_rejected")


def test_valid_host_accepted():
    mock_services = MagicMock()
    mock_services.guards.check_sls_environment.return_value = {"ok": True}
    mock_services.ctx.hubcap_key.current.return_value = "test_key_123"

    code, resp, _ = dispatch_request(
        mock_services, "GET", "/ping", b"", {"Host": "127.0.0.1:1952"}
    )
    assert code == 200, f"Expected 200, got {code}"
    assert resp.get("service") == "epsilon"
    print("ok  test_valid_host_accepted")


def test_ping_endpoint():
    mock_services = MagicMock()
    mock_services.guards.check_sls_environment.return_value = {"ok": True}
    mock_services.guards.check_system_readiness.return_value = {
        "ready": True,
        "sls_active": True,
        "error_code": None,
        "error": None,
    }
    mock_services.ctx.hubcap_key.current.return_value = "test_key_123"
    mock_services.ctx.plugin_dir = ROOT

    code, resp, _ = dispatch_request(mock_services, "GET", "/ping", b"", {})
    assert code == 200, f"Expected 200, got {code}"
    assert resp.get("service") == "epsilon", f"Expected service=epsilon, got {resp}"
    expected_version = (ROOT / "epsilon" / "VERSION").read_text(encoding="utf-8").strip()
    assert resp.get("version") == expected_version, (
        f"Expected version={expected_version}, got {resp}"
    )
    assert resp.get("sls_active") is True, f"Expected sls_active=True, got {resp}"
    assert resp.get("has_hubcap_key") is True, f"Expected has_hubcap_key=True, got {resp}"
    print("ok  test_ping_endpoint")


def test_status_endpoint():
    mock_services = MagicMock()
    mock_services.guards.check_system_readiness.return_value = {
        "ready": True,
        "sls_active": True,
        "error_code": None,
        "error": None,
    }
    mock_services.guards.is_app_added.return_value = True
    mock_services.injector.status.return_value = {"done": True, "depots": ["731"]}
    mock_services.steam.app_details.return_value = {"name": "Counter-Strike 2"}

    code, resp, _ = dispatch_request(mock_services, "GET", "/status?appid=730", b"", {})
    assert code == 200, f"Expected 200, got {code}"
    assert resp.get("appid") == "730", f"Expected appid=730, got {resp}"
    assert resp.get("added") is True, f"Expected added=True, got {resp}"
    assert resp.get("name") == "Counter-Strike 2", f"Expected name=Counter-Strike 2, got {resp}"
    assert resp.get("inject_status", {}).get("done") is True, f"Expected done=True, got {resp}"

    # Invalid AppID test
    code_inv, resp_inv, _ = dispatch_request(mock_services, "GET", "/status?appid=abc", b"", {})
    assert code_inv == 400, f"Expected 400 for invalid appid, got {code_inv}"
    print("ok  test_status_endpoint")


def test_inject_endpoint_success():
    mock_services = MagicMock()
    mock_services.guards.check_system_readiness.return_value = {
        "ready": True,
        "sls_active": True,
        "error_code": None,
        "error": None,
    }
    mock_services.injector.inject.return_value = {
        "name": "Portal 2",
        "depots": ["621", "622"],
        "fetching": True,
    }

    body = json.dumps({"appid": "620"}).encode("utf-8")
    code, resp, _ = dispatch_request(mock_services, "POST", "/inject", body, {})
    assert code == 200, f"Expected 200, got {code}"
    assert resp.get("ok") is True, f"Expected ok=True, got {resp}"
    assert resp.get("name") == "Portal 2", f"Expected name=Portal 2, got {resp}"
    assert resp.get("fetching") is True, f"Expected fetching=True, got {resp}"
    mock_services.injector.inject.assert_called_once_with("620")
    print("ok  test_inject_endpoint_success")


def test_inject_endpoint_already_added():
    mock_services = MagicMock()
    mock_services.guards.check_system_readiness.return_value = {
        "ready": True,
        "sls_active": True,
        "error_code": None,
        "error": None,
    }
    mock_services.injector.inject.return_value = {
        "error": "Portal 2 is already registered in your library.",
        "already_added": True,
    }

    body = json.dumps({"appid": "620"}).encode("utf-8")
    code, resp, _ = dispatch_request(mock_services, "POST", "/inject", body, {})
    assert code == 200, f"Expected 200, got {code}"
    assert resp.get("ok") is False, f"Expected ok=False, got {resp}"
    assert resp.get("already_added") is True, f"Expected already_added=True, got {resp}"
    print("ok  test_inject_endpoint_already_added")


def test_refresh_and_refetch():
    mock_services = MagicMock()
    mock_services.injector.refresh.return_value = {"ok": True}
    mock_services.injector.refetch_game.return_value = {"ok": True}

    body = json.dumps({"appid": "400"}).encode("utf-8")
    code, resp, _ = dispatch_request(mock_services, "POST", "/refresh", body, {})
    assert code == 200 and resp.get("ok") is True
    mock_services.injector.refresh.assert_called_once_with("400")

    code2, resp2, _ = dispatch_request(mock_services, "POST", "/refetch", body, {})
    assert code2 == 200 and resp2.get("ok") is True
    mock_services.injector.refetch_game.assert_called_once_with("400")
    print("ok  test_refresh_and_refetch")


def test_port_check():
    # An unallocated high port should return False
    assert is_port_in_use(58291) is False
    print("ok  test_port_check")


# ---------------------------------------------------------------- /v1 console

def _reset_auth_state():
    with console_api._fail_lock:
        console_api._fail_state.update({"count": 0, "first": 0.0, "blocked_until": 0.0})


def test_console_preflight_private_network():
    mock_services = _console_services()
    code, resp, headers = dispatch_request(
        mock_services,
        "OPTIONS",
        "/v1/library",
        b"",
        {
            "Origin": "https://assella.pages.dev",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Private-Network": "true",
        },
    )
    assert code == 200, f"Expected 200, got {code}"
    assert headers.get("Access-Control-Allow-Origin") == "https://assella.pages.dev"
    assert headers.get("Access-Control-Allow-Private-Network") == "true", headers
    assert "Authorization" in headers.get("Access-Control-Allow-Headers", "")
    print("ok  test_console_preflight_private_network")


def test_console_requires_token():
    _reset_auth_state()
    mock_services = _console_services()
    code, resp, headers = dispatch_request(mock_services, "GET", "/v1/library", b"", {})
    assert code == 401, f"Expected 401 without a token, got {code}"
    assert headers.get("WWW-Authenticate") == "Bearer"
    assert "games" not in resp
    print("ok  test_console_requires_token")


def test_console_token_accepted():
    _reset_auth_state()
    mock_services = _console_services()
    mock_services.ctx.plugin_dir = ROOT
    code, resp, _ = dispatch_request(
        mock_services, "GET", "/v1/session", b"", _console_headers()
    )
    assert code == 200, f"Expected 200, got {code}"
    assert resp.get("ok") is True
    assert resp.get("console") is True
    assert resp.get("library_count") == 1
    print("ok  test_console_token_accepted")


def test_console_rejects_wrong_token():
    _reset_auth_state()
    mock_services = _console_services()
    code, resp, _ = dispatch_request(
        mock_services, "GET", "/v1/session", b"", _console_headers(token="nope")
    )
    assert code == 401, f"Expected 401 for a wrong token, got {code}"
    _reset_auth_state()
    print("ok  test_console_rejects_wrong_token")


def test_console_write_needs_client_header():
    _reset_auth_state()
    mock_services = _console_services()
    body = json.dumps({"appid": "620"}).encode("utf-8")
    code, resp, _ = dispatch_request(
        mock_services, "POST", "/v1/register", body, _console_headers(client=False)
    )
    assert code == 403, f"Expected 403 without X-At0m-Client, got {code}"
    mock_services.injector.inject.assert_not_called()
    print("ok  test_console_write_needs_client_header")


def test_console_register_uses_injector():
    _reset_auth_state()
    mock_services = _console_services()
    mock_services.injector.inject.return_value = {
        "name": "Portal 2", "depots": ["621"], "fetching": True,
    }
    body = json.dumps({"appid": "620"}).encode("utf-8")
    code, resp, _ = dispatch_request(
        mock_services, "POST", "/v1/register", body, _console_headers()
    )
    assert code == 200, f"Expected 200, got {code}"
    assert resp.get("ok") is True and resp.get("fetching") is True
    mock_services.injector.inject.assert_called_once_with("620")
    print("ok  test_console_register_uses_injector")


def test_console_register_maps_errors():
    _reset_auth_state()
    mock_services = _console_services()
    mock_services.injector.inject.return_value = {
        "error": "No SLSsteam config", "blocked": "no_sls_config",
    }
    body = json.dumps({"appid": "620"}).encode("utf-8")
    code, resp, _ = dispatch_request(
        mock_services, "POST", "/v1/register", body, _console_headers()
    )
    assert code == 400, f"Expected 400, got {code}"
    assert resp.get("error_code") == "504", resp
    assert resp.get("blocked") == "no_sls_config"
    assert resp.get("guide_url", "").endswith("#err-504")
    print("ok  test_console_register_maps_errors")


def test_console_library_never_leaks_keys():
    _reset_auth_state()
    mock_services = _console_services()
    mock_services.atom.list_games.return_value = [{
        "app_id": "620", "name": "Portal 2", "state": "installed",
        "depots": ["621"], "keys": {"621": "deadbeef"}, "key_count": 1,
        "install_path": "/home/u/.steam/steamapps/common/Portal 2",
    }]
    code, resp, _ = dispatch_request(
        mock_services, "GET", "/v1/library", b"", _console_headers()
    )
    assert code == 200
    game = resp["games"][0]
    assert "keys" not in game and "install_path" not in game, game
    assert game["key_count"] == 1
    print("ok  test_console_library_never_leaks_keys")


def test_console_detail_masks_keys():
    _reset_auth_state()
    mock_services = _console_services()
    mock_services.atom.detail.return_value = {
        "ok": True, "app_id": "620", "name": "Portal 2", "registered": True,
        "keys_detail": [{
            "id": "621", "name": "Portal 2", "key": "a" * 64,
            "masked_key": "aaaaaaaa...aaaaaa", "is_appkey": False,
            "in_config": True, "in_local": True,
        }],
        "depots_detail": [], "dlcs_detail": [],
    }
    code, resp, _ = dispatch_request(
        mock_services, "GET", "/v1/app/620?network=0", b"", _console_headers()
    )
    assert code == 200, f"Expected 200, got {code}"
    key = resp["keys_detail"][0]
    assert "key" not in key and key["masked_key"].endswith("aaaaaa"), key
    assert resp["inject_status"] is None
    print("ok  test_console_detail_masks_keys")


def test_console_settings_whitelist():
    _reset_auth_state()
    mock_services = _console_services()
    body = json.dumps({"manifest_api_key": "secret"}).encode("utf-8")
    code, resp, _ = dispatch_request(
        mock_services, "POST", "/v1/settings", body, _console_headers()
    )
    assert code == 400, f"Secrets must not be writable from the console, got {code}"

    code, resp, _ = dispatch_request(
        mock_services, "POST", "/v1/settings",
        json.dumps({"hubcap_gateway": "proxy"}).encode("utf-8"), _console_headers(),
    )
    assert code == 200 and resp["settings"]["hubcap_gateway"] == "proxy", resp
    mock_services.ctx.write_setting.assert_called_once_with("hubcap_gateway", "proxy")

    code, _, _ = dispatch_request(
        mock_services, "POST", "/v1/settings",
        json.dumps({"hubcap_gateway": "nonsense"}).encode("utf-8"), _console_headers(),
    )
    assert code == 400, "Unknown enum value must be rejected"
    print("ok  test_console_settings_whitelist")


def test_dev_origin_only_reaches_console():
    _reset_auth_state()
    mock_services = _console_services()
    # A loopback docs preview may reach /v1 (and still gets 401 without a token).
    code, _, _ = dispatch_request(
        mock_services, "GET", "/v1/library", b"", {"Origin": "http://localhost:5173"}
    )
    assert code == 401, f"Expected 401 from a dev origin on /v1, got {code}"

    # Photar's routes keep the strict allowlist.
    code, _, _ = dispatch_request(
        mock_services, "POST", "/inject", b"{}", {"Origin": "http://localhost:5173"}
    )
    assert code == 403, f"A dev origin must not reach /inject, got {code}"
    print("ok  test_dev_origin_only_reaches_console")


def test_console_store_patch_state():
    _reset_auth_state()
    mock_services = _console_services()

    root = Path("/tmp/uran-store-patch-test")
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)

    class _NoCef:
        @staticmethod
        def get(*_args, **_kwargs):
            raise OSError("no CEF debugging port here")

    log_path = root / "store_patch.log"
    debugger = StoreDebugger(_NoCef(), logging.getLogger("test"), log_path=log_path)
    for index in range(steam_store.LOG_TAIL + 4):
        debugger.record_log(f"[StorePatch] line {index}")
    debugger.record_log("not a store trace")  # filtered out

    mock_services.store_debugger = debugger
    code, body, _ = dispatch_request(
        mock_services, "GET", "/v1/store", b"", _console_headers()
    )
    assert code == 200, f"Expected 200, got {code}"
    assert body["cef"]["available"] is False
    assert "logs" not in body["cef"], "in-memory diagnostics should not ship to the console"
    assert body["enabled"] is True
    assert body["patched_by"] == "uran"
    assert len(body["recent"]) == steam_store.LOG_TAIL, body["recent"]
    assert body["recent"][-1].endswith("line 15"), body["recent"][-1]
    assert all("[StorePatch]" in line for line in body["recent"])

    # The shared trace comes from the settings directory, not Path.home():
    # Decky runs as root, so a home-relative path would land in /root.
    assert debugger.log_path == log_path

    # A missing file is an empty trace, not an error.
    absent = StoreDebugger(_NoCef(), logging.getLogger("test"), log_path=root / "absent.log")
    assert absent.recent_logs() == []

    # Rollover keeps the newest lines instead of wiping the evidence.
    original_cap = steam_store.LOG_MAX_BYTES
    steam_store.LOG_MAX_BYTES = 512
    try:
        rotating = StoreDebugger(_NoCef(), logging.getLogger("test"), log_path=root / "rotate.log")
        for index in range(80):
            rotating.record_log(f"[StorePatch] rotate line {index}")
        text = (root / "rotate.log").read_text(encoding="utf-8")
        assert text.strip(), "rollover must not leave an empty trace"
        assert len(text) < steam_store.LOG_MAX_BYTES + 200, len(text)
        assert "rotate line 79" in text, text[-200:]
    finally:
        steam_store.LOG_MAX_BYTES = original_cap

    # The switch is writable from the console and lands in settings.json.
    code, body, _ = dispatch_request(
        mock_services,
        "POST",
        "/v1/settings",
        json.dumps({"steam_store_enabled": False}).encode(),
        _console_headers(),
    )
    assert code == 200, f"Expected 200, got {code}"
    assert body["settings"]["steam_store_enabled"] is False
    shutil.rmtree(root, ignore_errors=True)
    print("ok  test_console_store_patch_state")


def test_console_can_be_disabled():
    _reset_auth_state()
    mock_services = _console_services(epsilon_console_enabled=False)
    code, _, _ = dispatch_request(
        mock_services, "GET", "/v1/session", b"", _console_headers()
    )
    assert code == 403, f"Expected 403 when disabled, got {code}"
    print("ok  test_console_can_be_disabled")


def test_photar_inject_still_unauthenticated():
    mock_services = MagicMock()
    mock_services.injector.inject.return_value = {
        "name": "Portal 2", "depots": ["621"], "fetching": True,
    }
    body = json.dumps({"appid": "620"}).encode("utf-8")
    code, resp, _ = dispatch_request(mock_services, "POST", "/inject", body, {})
    assert code == 200, f"Photar's route must not require the console token, got {code}"
    assert resp.get("ok") is True
    print("ok  test_photar_inject_still_unauthenticated")


def main():
    test_cors_preflight_allowed()
    test_malicious_origin_rejected()
    test_dns_rebinding_host_rejected()
    test_valid_host_accepted()
    test_ping_endpoint()
    test_status_endpoint()
    test_inject_endpoint_success()
    test_inject_endpoint_already_added()
    test_refresh_and_refetch()
    test_port_check()
    test_console_preflight_private_network()
    test_console_requires_token()
    test_console_token_accepted()
    test_console_rejects_wrong_token()
    test_console_write_needs_client_header()
    test_console_register_uses_injector()
    test_console_register_maps_errors()
    test_console_library_never_leaks_keys()
    test_console_detail_masks_keys()
    test_console_settings_whitelist()
    test_console_can_be_disabled()
    test_console_store_patch_state()
    test_dev_origin_only_reaches_console()
    test_photar_inject_still_unauthenticated()
    print("\nAll Epsilon tests passed successfully!")


if __name__ == "__main__":
    main()
