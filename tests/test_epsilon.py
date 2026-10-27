#!/usr/bin/env python3
"""Tests for Epsilon bridge server and API endpoints."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Allow imports from project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from uran_backend.epsilon_server import dispatch_request, is_port_in_use


def test_cors_preflight():
    mock_services = MagicMock()
    code, resp = dispatch_request(mock_services, "OPTIONS", "/inject", b"", {})
    assert code == 200, f"Expected 200, got {code}"
    assert resp.get("ok") is True, f"Expected ok=True, got {resp}"
    print("ok  test_cors_preflight")


def test_ping_endpoint():
    mock_services = MagicMock()
    mock_services.guards.check_sls_environment.return_value = {"ok": True}
    mock_services.ctx.hubcap_key.current.return_value = "test_key_123"

    code, resp = dispatch_request(mock_services, "GET", "/ping", b"", {})
    assert code == 200, f"Expected 200, got {code}"
    assert resp.get("service") == "epsilon", f"Expected service=epsilon, got {resp}"
    assert resp.get("version") == "0.6.3", f"Expected version=0.6.3, got {resp}"
    assert resp.get("sls_active") is True, f"Expected sls_active=True, got {resp}"
    assert resp.get("has_hubcap_key") is True, f"Expected has_hubcap_key=True, got {resp}"
    print("ok  test_ping_endpoint")


def test_status_endpoint():
    mock_services = MagicMock()
    mock_services.guards.is_app_added.return_value = True
    mock_services.injector.status.return_value = {"done": True, "depots": ["731"]}
    mock_services.steam.app_details.return_value = {"name": "Counter-Strike 2"}

    code, resp = dispatch_request(mock_services, "GET", "/status?appid=730", b"", {})
    assert code == 200, f"Expected 200, got {code}"
    assert resp.get("appid") == "730", f"Expected appid=730, got {resp}"
    assert resp.get("added") is True, f"Expected added=True, got {resp}"
    assert resp.get("name") == "Counter-Strike 2", f"Expected name=Counter-Strike 2, got {resp}"
    assert resp.get("inject_status", {}).get("done") is True, f"Expected done=True, got {resp}"

    # Invalid AppID test
    code_inv, resp_inv = dispatch_request(mock_services, "GET", "/status?appid=abc", b"", {})
    assert code_inv == 400, f"Expected 400 for invalid appid, got {code_inv}"
    print("ok  test_status_endpoint")


def test_inject_endpoint_success():
    mock_services = MagicMock()
    mock_services.injector.inject.return_value = {
        "name": "Portal 2",
        "depots": ["621", "622"],
        "fetching": True,
    }

    body = json.dumps({"appid": "620"}).encode("utf-8")
    code, resp = dispatch_request(mock_services, "POST", "/inject", body, {})
    assert code == 200, f"Expected 200, got {code}"
    assert resp.get("ok") is True, f"Expected ok=True, got {resp}"
    assert resp.get("name") == "Portal 2", f"Expected name=Portal 2, got {resp}"
    assert resp.get("fetching") is True, f"Expected fetching=True, got {resp}"
    mock_services.injector.inject.assert_called_once_with("620")
    print("ok  test_inject_endpoint_success")


def test_inject_endpoint_already_added():
    mock_services = MagicMock()
    mock_services.injector.inject.return_value = {
        "error": "Portal 2 is already registered in your library.",
        "already_added": True,
    }

    body = json.dumps({"appid": "620"}).encode("utf-8")
    code, resp = dispatch_request(mock_services, "POST", "/inject", body, {})
    assert code == 200, f"Expected 200, got {code}"
    assert resp.get("ok") is False, f"Expected ok=False, got {resp}"
    assert resp.get("already_added") is True, f"Expected already_added=True, got {resp}"
    print("ok  test_inject_endpoint_already_added")


def test_refresh_and_refetch():
    mock_services = MagicMock()
    mock_services.injector.refresh.return_value = {"ok": True}
    mock_services.injector.refetch_game.return_value = {"ok": True}

    body = json.dumps({"appid": "400"}).encode("utf-8")
    code, resp = dispatch_request(mock_services, "POST", "/refresh", body, {})
    assert code == 200 and resp.get("ok") is True
    mock_services.injector.refresh.assert_called_once_with("400")

    code2, resp2 = dispatch_request(mock_services, "POST", "/refetch", body, {})
    assert code2 == 200 and resp2.get("ok") is True
    mock_services.injector.refetch_game.assert_called_once_with("400")
    print("ok  test_refresh_and_refetch")


def test_port_check():
    # An unallocated high port should return False
    assert is_port_in_use(58291) is False
    print("ok  test_port_check")


def main():
    test_cors_preflight()
    test_ping_endpoint()
    test_status_endpoint()
    test_inject_endpoint_success()
    test_inject_endpoint_already_added()
    test_refresh_and_refetch()
    test_port_check()
    print("\nAll Epsilon tests passed successfully!")


if __name__ == "__main__":
    main()
