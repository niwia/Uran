"""Tests for SLS Lua configuration bridge (spacebunny.conf.lua),
internal key timestamps (mmhhddyyyy format), chronological sort keys,
and bidirectional synchronization with Uran and ASSella.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uran_backend import paths
from uran_backend.settings import HubcapKey, Settings
from uran_backend.sls_lua_config import (
    _timestamp_to_sort_key,
    escape_lua_string,
    generate_hubcap_timestamp,
    is_valid_hubcap_key,
    read_spacebunny_conf,
    sync_hubcap_key_bidirectional,
    sync_spacebunny_key,
    write_spacebunny_conf,
)


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print(f"ok  {label}")


def main():
    # 1. Validation & Timestamp generation
    ts = generate_hubcap_timestamp()
    check("timestamp is integer", isinstance(ts, int))
    check("timestamp is 10 digits", len(str(ts)) == 10)
    check("timestamp format mmhhddyyyy ends with current year", str(ts).endswith("2026") or str(ts).endswith("2025") or str(ts).endswith("2024") or str(ts).endswith("2027"))

    # 2. Chronological sort key comparison
    # 10-digit mmhhddyyyy:
    # ts1: 10:14 26-2026 -> 1014262026 -> sort key: 2026 * 10^8 + 26 * 10^6 + 14 * 10^4 + 10
    # ts2: 12:15 26-2026 -> 1215262026 -> later hour/minute
    ts_earlier = 1014262026  # minute 10, hour 14, day 26, year 2026
    ts_later = 1215262026    # minute 12, hour 15, day 26, year 2026
    sk_earlier = _timestamp_to_sort_key(ts_earlier)
    sk_later = _timestamp_to_sort_key(ts_later)
    check("sort key converts to chronological order", sk_later > sk_earlier)

    # Day comparison: day 27 should be after day 26
    ts_next_day = 1010272026  # minute 10, hour 10, day 27, year 2026
    check("next day sort key is higher", _timestamp_to_sort_key(ts_next_day) > sk_later)

    # 3. Key validation
    check("valid alphanumeric key", is_valid_hubcap_key("my-hubcap_key_12345"))
    check("rejects short key", not is_valid_hubcap_key("abc"))
    check("rejects spaces", not is_valid_hubcap_key("my hubcap key"))
    check("rejects empty", not is_valid_hubcap_key(""))
    check("rejects special chars", not is_valid_hubcap_key("key@invalid!"))

    # 4. Read & Write spacebunny.conf.lua
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        conf = paths.spacebunny_conf(root)

        init_cfg = {
            "standalone": True,
            "hubcap": {
                "enabled": True,
                "base_url": "https://custom.api/v1",
                "api_key": "initial_key_12345",
                "api_key_timestamp": 2221262026,
                "timeout_sec": 10,
                "write_config": False,
                "notify": True,
                "preflight": "all",
                "depot_index": True,
                "write_depot_comments": True,
            },
        }

        w_ok = write_spacebunny_conf(init_cfg, conf)
        check("write_spacebunny_conf succeeds", w_ok)
        check("conf file created", conf.is_file())

        parsed = read_spacebunny_conf(conf)
        check("standalone parsed", parsed["standalone"] is True)
        h = parsed["hubcap"]
        check("hubcap.enabled parsed", h["enabled"] is True)
        check("hubcap.base_url parsed", h["base_url"] == "https://custom.api/v1")
        check("hubcap.api_key parsed", h["api_key"] == "initial_key_12345")
        check("hubcap.api_key_timestamp parsed", h["api_key_timestamp"] == 2221262026)
        check("hubcap.timeout_sec parsed", h["timeout_sec"] == 10)
        check("hubcap.write_config parsed", h["write_config"] is False)
        check("hubcap.notify parsed", h["notify"] is True)
        check("hubcap.preflight parsed", h["preflight"] == "all")
        check("hubcap.depot_index parsed", h["depot_index"] is True)
        check("hubcap.write_depot_comments parsed", h["write_depot_comments"] is True)

        # 5. sync_spacebunny_key preserves other options
        s_ok = sync_spacebunny_key(conf, "updated_key_99999", timestamp=2522262026)
        check("sync_spacebunny_key succeeds", s_ok)
        re_parsed = read_spacebunny_conf(conf)
        check("updated key preserved", re_parsed["hubcap"]["api_key"] == "updated_key_99999")
        check("updated timestamp preserved", re_parsed["hubcap"]["api_key_timestamp"] == 2522262026)
        check("standalone option still preserved", re_parsed["standalone"] is True)
        check("timeout_sec option still preserved", re_parsed["hubcap"]["timeout_sec"] == 10)
        check("preflight option still preserved", re_parsed["hubcap"]["preflight"] == "all")

        # 6. Bidirectional synchronization
        settings_dir = root / "settings"
        settings = Settings(settings_dir)

        # Case A: Lua has a newer timestamp than Uran
        # Uran has older timestamp (or none)
        settings.set("manifest_api_key", "old_uran_key_11111")
        settings.set("manifest_api_key_timestamp", 1010262026)

        # Lua has newer timestamp 2522262026
        active_key, synced, reason = sync_hubcap_key_bidirectional(settings, conf, root)
        check("Lua newer -> synced to Uran", synced and active_key == "updated_key_99999")
        check("settings.json updated with Lua key", settings.get("manifest_api_key") == "updated_key_99999")
        check("settings.json updated with Lua timestamp", settings.get("manifest_api_key_timestamp") == 2522262026)

        # Case B: Uran refreshes with a newer timestamp
        newer_ts = 5523262026
        settings.set("manifest_api_key", "fresh_decky_key_22222")
        settings.set("manifest_api_key_timestamp", newer_ts)

        active_key, synced, reason = sync_hubcap_key_bidirectional(settings, conf, root)
        check("Uran newer -> synced to Lua", synced and active_key == "fresh_decky_key_22222")
        lua_after = read_spacebunny_conf(conf)
        check("Lua file has fresh Uran key", lua_after["hubcap"]["api_key"] == "fresh_decky_key_22222")
        check("Lua file has fresh Uran timestamp", lua_after["hubcap"]["api_key_timestamp"] == newer_ts)

        # Case C: ACCELA.conf shared sync
        accela_conf = root / ".config" / "Tachibana Labs" / "ACCELA.conf"
        accela_conf.parent.mkdir(parents=True, exist_ok=True)
        accela_conf.write_text("[General]\nmorrenus_api_key=assella_key_33333\nmorrenus_api_key_timestamp=5923262026\n", encoding="utf-8")

        # Clear Uran settings so it discovers ASSella/Lua
        settings.set("manifest_api_key", "")
        settings.set("manifest_api_key_timestamp", 0)

        # Sync adopts newer key from ACCELA / Lua
        active_key, synced, reason = sync_hubcap_key_bidirectional(settings, conf, root)
        check("Adopts valid key across bridge", bool(active_key))

        # 7. write_accela_api_key writes key and timestamp
        ok, msg = paths.write_accela_api_key("final_key_77777", root, timestamp=1122262026)
        check("write_accela_api_key succeeds", ok)
        check("ACCELA key is written", paths.read_ini_value(accela_conf, "morrenus_api_key") == "final_key_77777")
        check("ACCELA timestamp is written", paths.read_ini_value(accela_conf, "morrenus_api_key_timestamp") == "1122262026")

        # 8. HubcapKey class integration
        hk = HubcapKey(settings, root)
        hk_current = hk.current()
        check("HubcapKey.current returns active key", bool(hk_current))

        # HubcapKey.save writes to spacebunny.conf.lua and ACCELA.conf
        hk.save("brand_new_key_88888")
        check("HubcapKey.save updates settings", settings.get("manifest_api_key") == "brand_new_key_88888")
        check("HubcapKey.save generates internal timestamp", settings.get("manifest_api_key_timestamp") > 0)
        lua_final = read_spacebunny_conf(conf)
        check("HubcapKey.save updates spacebunny.conf.lua", lua_final["hubcap"]["api_key"] == "brand_new_key_88888")
        check("spacebunny.conf.lua has matching timestamp", lua_final["hubcap"]["api_key_timestamp"] == settings.get("manifest_api_key_timestamp"))

    print("\nall SLS Lua config bridge tests passed")


if __name__ == "__main__":
    main()
