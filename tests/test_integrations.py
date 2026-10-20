"""Regression checks for SLSonline status being read from SLS config."""

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uran_backend.integrations import Integrations


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


if __name__ == "__main__":
    run()
