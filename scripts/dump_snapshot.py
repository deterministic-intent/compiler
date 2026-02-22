#!/usr/bin/env python3
"""Export current database as JSON snapshot."""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from db.api import save_snapshot


def main():
    """Export database to JSON snapshot."""
    parser = argparse.ArgumentParser(description="Export database snapshot")
    parser.add_argument("output_path", nargs="?", help="Output path for snapshot (default: auto-generated)")
    parser.add_argument("--format", choices=["json", "jsonl"], default="json", help="Output format")
    
    args = parser.parse_args()
    
    if args.output_path:
        output_path = Path(args.output_path)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path(f"db/snapshots/snapshot_{timestamp}.json")
    
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Exporting database snapshot to {output_path}...")
    save_snapshot(output_path, format=args.format)
    print("Snapshot exported successfully!")


if __name__ == "__main__":
    main()
