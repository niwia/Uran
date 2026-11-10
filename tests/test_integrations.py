"""Regression checks for SLSonline status being read from SLS config."""

import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uran_backend.integrations import Integrations
from uran_backend.sls_config import SlsConfig


def check(label, actual, expected):
    if actual != expected:
        raise AssertionError(f"{label}: got {actual!r}, expected {expected!r}")
    print(f"ok  {label}")


def run():
    with tempfile.TemporaryDirectory() as temp:
        config = Path(temp) / "config.yaml"
        ctx = SimpleNamespace(sls_config=lambda: config)
        integrations = Integrations(ctx, sls=None, steam=None)

        config.write_text("FakeAppIds:\n  620: 480 # per-game only\n", encoding="utf-8")
        check("per-game 480 does not imply global SLSonline", integrations.global_slsonline_enabled(), False)

        config.write_text("FakeAppIds:\n  0: 480 # Global -> Spacewar\n", encoding="utf-8")
        check("global SLSonline is enabled from config entry 0: 480", integrations.global_slsonline_enabled(), True)

        config.write_text("FakeAppIds:\n  0: 620 # not Spacewar\n", encoding="utf-8")
        check("global SLSonline is false when entry 0 maps elsewhere", integrations.global_slsonline_enabled(), False)

        missing_config = Path(temp) / "missing.yaml"
        missing_ctx = SimpleNamespace(
            home=Path(temp),
            sls_config=lambda: missing_config,
            sls_lock=threading.RLock(),
        )
        missing_sls = SlsConfig(missing_ctx)
        guarded = Integrations(missing_ctx, sls=missing_sls, steam=None)
        binary_calls = []
        guarded.ensure_netsock_binary = lambda: binary_calls.append(True) or True
        result = guarded.set_netsock("620", True)
        check("NetSock rejects missing config", result.get("ok"), False)
        check("NetSock does not install binary when config is missing", binary_calls, [])
        check("FakeAppId rejects missing config", guarded.set_fake_appid("620", "480").get("ok"), False)
        check("list FakeAppIds preserves unknown config status", guarded.list_fake_app_ids().get("ok"), False)


if __name__ == "__main__":
    run()
