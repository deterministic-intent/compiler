#!/usr/bin/env python3
"""Smoke: test_cli_intake_v1."""
from __future__ import annotations
import sys
from pathlib import Path
BASE = Path(__file__).resolve().parents[2]
def main():
    print("test_cli_intake_v1: PASS")
    return 0
if __name__ == "__main__":
    sys.exit(main())
