#!/usr/bin/env python3
"""
Enforce no network during v1 audit/replay. Hard fail if any network attempt occurred.
Produces out/network_guard_report.json for validation hashing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request-dir", default="")
    ap.add_argument("--v1-only", action="store_true")
    ap.add_argument("--out", default="")
    args, _ = ap.parse_known_args()

    req_root = Path(args.request_dir).resolve() if args.request_dir else (BASE / "state" / "requests")
    out_dir = Path(args.out).resolve() if args.out else (BASE / "out")
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "network_guard_report.json"

    violations: list[dict] = []
    net_log_names = ["NET_LOG.txt", "net_attempts.log", "NLC_NET_LOG"]

    if req_root.exists():
        for req_dir in sorted(req_root.iterdir()):
            if not req_dir.is_dir():
                continue
            for name in net_log_names:
                log_path = req_dir / name
                if log_path.exists() and log_path.stat().st_size > 0:
                    content = log_path.read_text(encoding="utf-8", errors="replace").strip()
                    if content:
                        violations.append({
                            "request_id": req_dir.name,
                            "log_file": name,
                            "content_preview": content[:500] + ("..." if len(content) > 500 else ""),
                        })

    report = {
        "schema_version": "network_guard_v1",
        "no_network_violations": len(violations) == 0,
        "violations": violations,
        "request_dirs_scanned": str(req_root),
    }

    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if violations:
        sys.stderr.write(f"FAIL: NETWORK_VIOLATION: {len(violations)} network attempt(s) detected during v1 audit.\n")
        for v in violations[:5]:
            sys.stderr.write(f"  - {v['request_id']}/{v['log_file']}: {v['content_preview'][:80]}...\n")
        sys.stderr.write("Replay must run with zero network access.\n")
        return 1

    print("verify_network_guard_v1: PASS (no network violations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
