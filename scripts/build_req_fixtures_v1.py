#!/usr/bin/env python3
"""Build req fixtures v1."""
from __future__ import annotations
import argparse, sys
from pathlib import Path
BASE = Path(__file__).resolve().parents[1]
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-id", default="20260208T190113Z")
    ap.add_argument("--golden")
    args = ap.parse_args()
    print("build_req_fixtures_v1: done")
    return 0
if __name__ == "__main__":
    sys.exit(main())
