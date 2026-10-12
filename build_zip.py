#!/usr/bin/env python3
"""
build_zip.py — Packages Uran into a release zip ready for Decky Loader.

Layout follows the Decky plugin template:
    Uran/
      dist/index.js        (required)
      package.json         (required)
      plugin.json          (required)
      main.py              (required — Python backend)
      LICENSE              (required)
      README.md            (recommended)

The source map is deliberately excluded: it is the single largest file in the
package and it would ship the full TypeScript source to users.
"""

import os
import zipfile
from pathlib import Path

HERE = Path(__file__).parent.resolve()
OUTPUT_ZIP = HERE / "Uran.zip"
PLUGIN_DIR = "Uran"

# Never ship these: build noise and the frontend source map.
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".map")
EXCLUDE_DIRS = {"__pycache__", "node_modules", ".git", "defaults"}

FILES_TO_PACK = [
    "plugin.json",
    "package.json",
    "main.py",
    "README.md",
    "LICENSE",
]

DIRS_TO_PACK = [
    "dist",
    "assets",
    "uran_backend",
]


def _add(zf: zipfile.ZipFile, source: Path, arcname: str) -> None:
    zf.write(source, arcname)
    print(f"  + {arcname}")


def make_zip() -> None:
    if OUTPUT_ZIP.exists():
        OUTPUT_ZIP.unlink()

    dist_index = HERE / "dist" / "index.js"
    if not dist_index.exists():
        raise SystemExit(
            "Error: dist/index.js not found. Run 'npm run build' first!"
        )

    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in FILES_TO_PACK:
            path = HERE / name
            if path.is_file():
                _add(zf, path, f"{PLUGIN_DIR}/{name}")
            elif name in ("plugin.json", "package.json", "main.py", "LICENSE"):
                raise SystemExit(f"Error: required file missing: {name}")

        for directory in DIRS_TO_PACK:
            root_dir = HERE / directory
            if not root_dir.is_dir():
                continue
            for root, subdirs, files in os.walk(root_dir):
                subdirs[:] = [
                    d for d in subdirs if d not in EXCLUDE_DIRS and not d.startswith(".")
                ]
                for file in sorted(files):
                    if file.endswith(EXCLUDE_SUFFIXES):
                        continue
                    file_path = Path(root) / file
                    arcname = f"{PLUGIN_DIR}/{file_path.relative_to(HERE)}"
                    _add(zf, file_path, arcname)

    size_kb = round(OUTPUT_ZIP.stat().st_size / 1024, 1)
    print(f"\n==> Decky installable package built: {OUTPUT_ZIP.name} ({size_kb} KB)")


if __name__ == "__main__":
    make_zip()