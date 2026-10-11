#!/usr/bin/env python3
"""
build_zip.py — Packages Uran into a release zip ready for Decky Loader.
"""
import os
import zipfile
from pathlib import Path

HERE = Path(__file__).parent.resolve()
OUTPUT_ZIP = HERE / "Uran.zip"

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

def make_zip():
    if OUTPUT_ZIP.exists():
        OUTPUT_ZIP.unlink()

    dist_dir = HERE / "dist"
    if not dist_dir.exists() or not (dist_dir / "index.js").exists():
        raise SystemExit("Error: dist/index.js not found. Run 'npm run build' first!")

    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in FILES_TO_PACK:
            p = HERE / f
            if p.is_file():
                arcname = f"Uran/{f}"
                zf.write(p, arcname)
                print(f"  + {arcname}")

        for d in DIRS_TO_PACK:
            dp = HERE / d
            if dp.is_dir():
                for root, subdirs, files in os.walk(dp):
                    subdirs[:] = [name for name in subdirs if name != "__pycache__"]
                    for file in sorted(files):
                        if file.endswith((".pyc", ".pyo")):
                            continue
                        fp = Path(root) / file
                        rel = fp.relative_to(HERE)
                        arcname = f"Uran/{rel}"
                        zf.write(fp, arcname)
                        print(f"  + {arcname}")

    size_kb = round(OUTPUT_ZIP.stat().st_size / 1024, 1)
    print(f"\n==> Decky installable package built: {OUTPUT_ZIP.name} ({size_kb} KB)")

if __name__ == "__main__":
    make_zip()
