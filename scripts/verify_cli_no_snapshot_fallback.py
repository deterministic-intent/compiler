#!/usr/bin/env python3
"""
Enforce no snapshot fallback: reject "latest", require explicit snapshot ID in v1,
and verify no path escape from nlc/db/snapshots/<SNAPSHOT_ID>/.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SNAP_ROOT = BASE / "nlc" / "db" / "snapshots"


def _forbidden_snapshot_id(sid: str) -> str | None:
    """Return reason if snapshot ID is forbidden, else None."""
    t = (sid or "").strip()
    if not t:
        return "empty"
    if t.lower() == "latest":
        return "SNAPSHOT_LATEST_FORBIDDEN"
    if ".." in t or "/" in t or "\\" in t or "\x00" in t:
        return "SNAPSHOT_PATH_ESCAPE"
    return None


def _resolve_under_root(sid: str) -> Path | None:
    """Resolve snapshot path; return None if escapes root."""
    reason = _forbidden_snapshot_id(sid)
    if reason:
        return None
    p = (SNAP_ROOT / sid).resolve()
    try:
        p.relative_to(SNAP_ROOT.resolve())
    except ValueError:
        return None
    if not p.is_dir():
        return None
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request-dir", default="")
    ap.add_argument("--v1-only", action="store_true")
    args, _ = ap.parse_known_args()

    req_root = Path(args.request_dir).resolve() if args.request_dir else (BASE / "state" / "requests")

    errors: list[str] = []

    # v1: require AUDIT_CLOSURE_SNAPSHOT or NLC_DB_SNAPSHOT_ID
    closure = (os.environ.get("AUDIT_CLOSURE_SNAPSHOT") or "").strip()
    nlc_snap = (os.environ.get("NLC_DB_SNAPSHOT_ID") or "").strip()
    snap_env = closure or nlc_snap

    if args.v1_only or closure or nlc_snap:
        if not snap_env:
            errors.append("SNAPSHOT_ID_REQUIRED: v1 requires AUDIT_CLOSURE_SNAPSHOT or NLC_DB_SNAPSHOT_ID")
        else:
            reason = _forbidden_snapshot_id(snap_env)
            if reason:
                errors.append(f"SNAPSHOT_FORBIDDEN: env snapshot '{snap_env}' -> {reason}")
            elif not _resolve_under_root(snap_env):
                errors.append(f"SNAPSHOT_INVALID: env snapshot '{snap_env}' not under {SNAP_ROOT}/ or missing")

    # Scan payloads in request dirs for knowledge_snapshot_id
    if req_root.exists():
        for req_dir in sorted(req_root.iterdir()):
            if not req_dir.is_dir():
                continue
            pl_path = req_dir / "payload.json"
            if not pl_path.exists():
                continue
            try:
                pl = json.loads(pl_path.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            sid = str(pl.get("knowledge_snapshot_id", "") or "").strip()
            if not sid:
                continue
            reason = _forbidden_snapshot_id(sid)
            if reason:
                errors.append(f"SNAPSHOT_FORBIDDEN: {req_dir.name}/payload.json knowledge_snapshot_id '{sid}' -> {reason}")
            elif not _resolve_under_root(sid):
                errors.append(f"SNAPSHOT_PATH_ESCAPE: {req_dir.name} knowledge_snapshot_id '{sid}' escapes {SNAP_ROOT}/")

    if errors:
        for e in errors:
            sys.stderr.write(f"FAIL: {e}\n")
        sys.stderr.write("No snapshot fallback or path escape allowed in v1.\n")
        return 1

    print("verify_cli_no_snapshot_fallback: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
