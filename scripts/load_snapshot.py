#!/usr/bin/env python3
"""Load a saved database snapshot."""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from db.api import load_snapshot


def main():
    """Load a database snapshot from JSON file."""
    parser = argparse.ArgumentParser(description="Load database snapshot")
    parser.add_argument("snapshot_path", help="Path to snapshot JSON file")
    parser.add_argument("--clear", action="store_true", help="Clear existing data before loading")
    
    args = parser.parse_args()
    
    snapshot_path = Path(args.snapshot_path)
    if not snapshot_path.exists():
        print(f"Error: Snapshot file {snapshot_path} not found")
        sys.exit(1)
    
    print(f"Loading snapshot from {snapshot_path}...")
    load_snapshot(snapshot_path, clear_existing=args.clear)
    print("Snapshot loaded successfully!")


if __name__ == "__main__":
    main()
