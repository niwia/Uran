#!/usr/bin/env python3
"""Run every test file in this directory.

Deliberately dependency-free: Decky plugins ship no test framework, and these
checks exercise pure functions only, so plain `python3 tests/test_x.py` works.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Parked while plugin deployment is disabled in Uran.
PARKED_TESTS = {
    "test_plugin_install.py",
    "test_plugin_manager.py",
}


def main() -> int:
    all_tests = sorted(HERE.glob("test_*.py"))
    tests = [test for test in all_tests if test.name not in PARKED_TESTS]
    skipped = [test.name for test in all_tests if test.name in PARKED_TESTS]
    if not tests:
        print("no tests found")
        return 1

    for name in skipped:
        print(f"--- {name} (parked/skipped)")

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