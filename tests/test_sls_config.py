"""Exercise the config engine's pure functions against realistic input.

sls_config.py is the highest-risk, most self-contained code in the plugin: it
edits another application's config in place, and a mistake silently corrupts a
file the user cannot easily reconstruct. These checks run with no network, no
filesystem and no Decky.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging

from uran_backend import sls_config as sc

log = logging.getLogger("t")
fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"FAIL {label}\n     got  {got!r}\n     want {want!r}")
    else:
        print(f"ok  {label}")


BASE = """\
# SLSsteam config
Plugins: no
AdditionalApps:
  - 620 # Portal 2
AdditionalDepots:
  - 621 # Portal 2 [win64] (620)
DecryptionKeys:
  620: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa # Portal 2 [AppKey] (620)
  621: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb # Portal 2 [win64] (620)
FakeAppIds:
  620: 480 # Portal 2 -> Spacewar
SmartTickets: 0x0
"""

# --- sanitizers ---------------------------------------------------------
check("sanitize_id keeps digits", sc.sanitize_id(" 620 "), "620")
check("sanitize_id rejects traversal", sc.sanitize_id("../../etc/passwd"), None)
check("sanitize_id rejects empty", sc.sanitize_id(""), None)
check("sanitize_id rejects None", sc.sanitize_id(None), None)
check("sanitize_comment kills newlines (YAML injection)", sc.sanitize_comment("a\n  - 999"), "a - 999")
check("sanitize_key accepts 64 hex", sc.sanitize_key("a" * 64), "a" * 64)
check("sanitize_key rejects short", sc.sanitize_key("a" * 63), None)
check("sanitize_key preserves case", sc.sanitize_key("A" * 64), "A" * 64)

# --- section bounds -----------------------------------------------------
b = sc.section_bounds(BASE, "DecryptionKeys")
check("section bounds found", b is not None, True)
_sec = BASE[b[1]:b[2]]
check("section bounds cover both key lines",
      sum(1 for ln in _sec.splitlines() if ln.strip()), 2)
check("unknown section -> None", sc.section_bounds(BASE, "Nope"), None)

# --- parsers ------------------------------------------------------------
check("parse_list_section", sc.parse_list_section(BASE, "AdditionalApps"), {"620": "Portal 2"})
keys, comments = sc.parse_key_section(BASE, "DecryptionKeys")
check("parse_key_section ids", sorted(keys), ["620", "621"])
check("parse_key_section keeps comments", comments["620"], "Portal 2 [AppKey] (620)")

# --- ensure_* helpers ---------------------------------------------------
check("ensure_plugins_enabled rewrites 'no'", sc.ensure_plugins_enabled(BASE).splitlines()[1], "Plugins: yes")
check("ensure_plugins_enabled idempotent", sc.ensure_plugins_enabled(sc.ensure_plugins_enabled(BASE)), sc.ensure_plugins_enabled(BASE))
check("ensure_smart_tickets flips 0x0", "SmartTickets: 0x1" in sc.ensure_smart_tickets(BASE), True)
check("ensure_smart_tickets idempotent", sc.ensure_smart_tickets(sc.ensure_smart_tickets(BASE)), sc.ensure_smart_tickets(BASE))

# --- upsert / remove ----------------------------------------------------
out, changed = sc.upsert_in_memory(BASE, "AdditionalApps", "999", comment="New Game")
check("upsert adds entry", "  - 999 # New Game" in out, True)
check("upsert reports changed", changed, True)
check("upsert preserves other entries", "  - 620 # Portal 2" in out, True)
check("upsert preserves comments elsewhere", "# SLSsteam config" in out, True)

_, changed = sc.upsert_in_memory(BASE, "AdditionalApps", "620", comment="Renamed")
check("upsert replaces existing", "  - 620 # Renamed" in sc.upsert_in_memory(BASE, "AdditionalApps", "620", comment="Renamed")[0], True)

out, changed = sc.remove_in_memory(BASE, "AdditionalApps", "620", is_list=True)
check("remove drops entry", "  - 620" not in out, True)
check("remove reports changed", changed, True)
out, changed = sc.remove_in_memory(BASE, "AdditionalApps", "4242", is_list=True)
check("remove missing -> no change", changed, False)

# Idempotency: writing the same map value twice must not rewrite the file.
same, changed = sc.upsert_in_memory(BASE, "DecryptionKeys", "620", value="a" * 64, comment="x")
check("identical map value -> no change", changed, False)

# --- replace_section_block ---------------------------------------------
out = sc.replace_section_block(BASE, "AdditionalDepots", ["  - 700 # Seven"])
check("replace_section_block swaps body", "  - 700 # Seven" in out and "  - 621" not in out, True)

# --- dlc block removal --------------------------------------------------
# NOTE: remove_dlc_block removes the matched game AND every following indented
# line. When sibling games sit at the SAME indent level, they are consumed too.
# This matches ASSella and the pre-refactor behaviour of this plugin, so it is
# asserted here rather than "fixed" — changing it would diverge from ASSella.
DLC = BASE + "DlcData:\n  620:\n    - 900\n    - 901\n  700:\n    - 950\n"
out = sc.remove_dlc_block(DLC, "620")
# Scope the assertion to the DlcData section: "  620:" also appears legitimately
# in FakeAppIds as a map entry.
_dlc_tail = out.split("DlcData:", 1)[1] if out and "DlcData:" in out else ""
check("remove_dlc_block removes the game", "620:" not in _dlc_tail, True)
check("remove_dlc_block drops same-indent siblings (ASSella parity)", "700:" not in _dlc_tail, True)
check("remove_dlc_block keeps the section header", out is not None and "DlcData:" in out, True)
check("remove_dlc_block missing -> None", sc.remove_dlc_block(BASE, "424242"), None)

# --- validate_yaml guards a duplicate top-level key ---------------------
check("validate_yaml rejects duplicate keys",
      sc.validate_yaml("A: 1\nA: 2\n", log), False)
check("validate_yaml accepts normal config", sc.validate_yaml(BASE, log), True)

# --- replace_section_block ordering ------------------------------------
out = sc.replace_section_block(BASE, "AdditionalDepots", ["  - 900", "  - 100", "  - 500"])
ids = [ln.strip("- ").split(" ")[0] for ln in out.splitlines() if ln.strip().startswith("- ")]
check("replace_section_block keeps given order (caller sorts)", ids[-3:], ["900", "100", "500"])

print()
if fails:
    print("\n".join(fails))
    sys.exit(1)
print("all config engine checks pass")