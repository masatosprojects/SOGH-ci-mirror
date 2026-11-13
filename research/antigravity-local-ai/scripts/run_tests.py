#!/usr/bin/env python3
"""
SOGH Antigravity - Local Test Runner
Executes Phase 1 local sanity and evaluation tests.
"""

import sys
import unittest
import os
import io

# Force utf-8 encoding for standard outputs if needed
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tests_dir = os.path.join(base_dir, "tests")

    # Add project root to sys.path
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)

    print("==================================================")
    print("SOGH Antigravity - Phase 1 Test Execution")
    print(f"Base Directory: {base_dir}")
    print(f"Python: {sys.executable} ({sys.version.split()[0]})")
    print("==================================================")

    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=tests_dir, pattern="test_*.py")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n--------------------------------------------------")
    print(f"Total Tests Run: {result.testsRun}")
    print(f"Passed: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("--------------------------------------------------")

    if not result.wasSuccessful():
        sys.exit(1)

if __name__ == "__main__":
    main()
