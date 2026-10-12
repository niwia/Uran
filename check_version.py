#!/usr/bin/env python3
"""Verify that plugin.json and package.json declare the same version.

plugin.json is the single source of truth: it is what Decky reads and what
uran_backend/updates.py reports. package.json duplicates the value for npm, so
a mismatch is a silent release bug rather than a visible one. Fail loudly here.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent.resolve()


def read_version(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    version = str(data.get("version") or "")
    if not version:
        raise SystemExit(f"error: {path.name} has no version field")
    return version


def main() -> int:
    plugin = read_version(HERE / "plugin.json")
    package = read_version(HERE / "package.json")

    if plugin != package:
        print(f"error: version mismatch — plugin.json {plugin} vs package.json {package}")
        print("       plugin.json is the source of truth; update package.json to match.")
        return 1

    print(f"versions agree: {plugin}")
    return 0


if __name__ == "__main__":
    sys.exit(main())