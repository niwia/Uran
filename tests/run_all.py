#!/usr/bin/env python3
"""Run every test file in this directory.

Deliberately dependency-free: Decky plugins ship no test framework, and these
checks exercise pure functions only, so plain `python3 tests/test_x.py` works.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    tests = sorted(HERE.glob("test_*.py"))
    if not tests:
        print("no tests found")
        return 1

    failed = []
    for test in tests:
        print(f"--- {test.name}")
        result = subprocess.run([sys.executable, str(test)], check=False)
        if result.returncode != 0:
            failed.append(test.name)

    print()
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print(f"all {len(tests)} test files passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())