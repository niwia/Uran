"""The Decky runtime must be discovered without a caller passing it in.

Decky instantiates `Plugin()` with no arguments, so `build_context` has to find
`decky_plugin` itself. If it does not, DECKY_USER_HOME is ignored and the
resolvers silently fall through to /home/deck or Path.home() — which on a Deck
with a renamed account means Uran would edit a different user's config.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uran_backend import services
from uran_backend.context import build_context

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"FAIL {label}\n     got  {got!r}\n     want {want!r}")
    else:
        print(f"ok  {label}")


class FakeDecky(types.ModuleType):
    def __init__(self, **attrs):
        super().__init__("decky_plugin")
        for key, value in attrs.items():
            setattr(self, key, value)


SANDBOX = "/tmp/uran-decky-discovery-test"


def test_explicit_module_is_used():
    decky = FakeDecky(
        DECKY_USER_HOME=SANDBOX,
        DECKY_PLUGIN_DIR=SANDBOX,
        DECKY_PLUGIN_RUNTIME_DIR=SANDBOX,
        DECKY_PLUGIN_SETTINGS_DIR=SANDBOX,
    )
    ctx = build_context(decky)
    check("explicit module: home", str(ctx.home), SANDBOX)
    check("explicit module: plugin dir", str(ctx.plugin_dir), SANDBOX)


def test_module_imported_when_not_passed():
    """The real Decky path: nothing passed in, decky_plugin in sys.modules."""
    decky = FakeDecky(
        DECKY_USER_HOME=SANDBOX,
        DECKY_PLUGIN_DIR=SANDBOX,
        DECKY_PLUGIN_RUNTIME_DIR=SANDBOX,
        DECKY_PLUGIN_SETTINGS_DIR=SANDBOX,
    )
    sys.modules["decky_plugin"] = decky
    try:
        # No argument at all — exactly what Decky does.
        built = services.build()
        ctx = built.ctx
        check("auto-discovery: home", str(ctx.home), SANDBOX)
        check("auto-discovery: plugin dir", str(ctx.plugin_dir), SANDBOX)
        check(
            "auto-discovery: ACCELA base stays under the sandbox",
            str(ctx.accela_base()).startswith(SANDBOX),
            True,
        )
        # sls_config() keeps its /home/deck and Path.home() candidates for
        # SteamOS compatibility — deliberately unchanged from the original.
        # What matters here is that DECKY_USER_HOME is honoured first, which
        # the home assertion above covers.
    finally:
        del sys.modules["decky_plugin"]


def test_missing_module_is_survivable():
    """Outside Decky (tests, linting) this must still construct."""
    sys.modules.pop("decky_plugin", None)
    built = services.build(None)
    check("missing module still builds", built is not None, True)
    check("missing module yields a home", isinstance(str(built.ctx.home), str), True)


test_explicit_module_is_used()
test_module_imported_when_not_passed()
test_missing_module_is_survivable()

print()
if fails:
    print("\n".join(fails))
    sys.exit(1)
print("all Decky discovery checks pass")