#!/usr/bin/env python3
"""
Phase 2: Golden request pack v1 runner.

Deterministic runner:
- runs pinned cases against pinned snapshot/bundle
- computes sha256 for selected artifacts
- compares to expected

Failure tokens (exact):
  FAIL suite:case_failed <case_id>
  FAIL suite:hash_mismatch <case_id> <artifact>
  FAIL suite:status_mismatch <case_id> <expected> <got>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple


BASE = Path(__file__).resolve().parents[2]


def _die(msg: str, code: int = 1) -> None:
    sys.stdout.write((msg.rstrip("\n") + "\n"))
    sys.stdout.flush()
    raise SystemExit(code)


def _fail(token_line: str, code: int = 1) -> None:
    # Must be exactly one deterministic failure line.
    sys.stdout.write(token_line.rstrip("\n") + "\n")
    sys.stdout.flush()
    raise SystemExit(code)


def _sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _load_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def _write_json(p: Path, obj: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sanitize_request_id(suite_id: str, case_id: str) -> str:
    rid = f"SUITE-{suite_id}-{case_id}"
    rid = re.sub(r"[^A-Za-z0-9_.-]+", "_", rid)
    return rid[:120]


def _request_dir(request_id: str) -> Path:
    return BASE / "state" / "requests" / request_id


def _cleanup_request_dir(rd: Path) -> None:
    if rd.exists():
        shutil.rmtree(rd, ignore_errors=True)


def _run(cmd: List[str], *, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(BASE),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )


def _orch_gate0(request_id: str, objective: str, env: Dict[str, str]) -> None:
    p = _run(
        [
            sys.executable,
            str(BASE / "orchestrator" / "orchestrator.py"),
            "gate0_init",
            request_id,
            json.dumps(objective),
            json.dumps([]),
            json.dumps([]),
            json.dumps([]),
        ],
        env=env,
    )
    if p.returncode != 0:
        _die(p.stderr or p.stdout or "gate0_init failed", p.returncode)


def _patch_payload(rd: Path, *, suite: Dict[str, Any]) -> None:
    payload_path = rd / "payload.json"
    payload = _load_json(payload_path) if payload_path.exists() else {}
    if not isinstance(payload, dict):
        payload = {}
    payload["policy_version"] = suite["policy_version"]
    payload["knowledge_snapshot_id"] = suite["knowledge_snapshot_id"]
    payload["manifest_bundle_hash"] = suite["manifest_bundle_hash"]
    payload["answer_mode"] = "index_backed"
    _write_json(payload_path, payload)


def _run_pipeline(request_id: str, env: Dict[str, str]) -> str:
    """
    Run gates 1..6. Return final_status = PASS|CLARIFY|FAIL.
    """
    orch = str(BASE / "orchestrator" / "orchestrator.py")
    for gate_cmd, gate_n in (
        ("gate1_planning", 1),
        ("gate2_delegation", 2),
        ("gate3_execution", 3),
        ("gate4_review", 4),
        ("gate5_finalize", 5),
        ("gate6_complete", 6),
    ):
        p = _run([sys.executable, orch, gate_cmd, request_id], env=env)
        rd = _request_dir(request_id)
        st_path = rd / f"gate{gate_n}.status"
        st = st_path.read_text(encoding="utf-8", errors="replace").strip() if st_path.exists() else ""
        if st == "CLARIFY":
            return "CLARIFY"
        if p.returncode != 0 or st != "PASS":
            return "FAIL"
    return "PASS"


def _collect_hashes(rd: Path, expected_keys: List[str]) -> Dict[str, str]:
    got: Dict[str, str] = {}
    for k in expected_keys:
        p = rd / k
        if not p.exists():
            got[k] = ""
            continue
        got[k] = _sha256_file(p)
    return got


def _case_expected_keys(case: Dict[str, Any]) -> List[str]:
    exp = case.get("expected_sha256", {})
    if not isinstance(exp, dict):
        return []
    keys = [str(k) for k in exp.keys()]
    keys.sort()
    return keys


def _compare_or_update_hashes(
    *,
    case: Dict[str, Any],
    got_hashes: Dict[str, str],
    update_hashes: bool,
    unpinned_proof: bool,
) -> None:
    exp = case.get("expected_sha256", {})
    if not isinstance(exp, dict):
        exp = {}
        case["expected_sha256"] = exp

    for artifact, got in got_hashes.items():
        want = str(exp.get(artifact, "")).strip()
        if update_hashes:
            # Update mode is strict about existence: do not write empties; fail fast if missing.
            if not got:
                _fail(f"FAIL suite:hash_mismatch {case['case_id']} {artifact}", 1)
            exp[artifact] = got
            continue

        # Strict default (pinned): empty expected hash is a failure.
        if want == "" and not unpinned_proof:
            _fail(f"FAIL suite:hash_mismatch {case['case_id']} {artifact}", 1)

        # Never mask missing expected artifacts (even in unpinned-proof mode).
        if not got:
            _fail(f"FAIL suite:hash_mismatch {case['case_id']} {artifact}", 1)

        # Unpinned-proof: allow empty expected hash by skipping equality comparison only.
        if want == "" and unpinned_proof:
            continue
        if want != got:
            _fail(f"FAIL suite:hash_mismatch {case['case_id']} {artifact}", 1)


def _emit_run_hashes(path: Path, *, suite_id: str, suite_version: Any, cases_out: List[Dict[str, Any]]) -> None:
    """
    Emit a deterministic run-hash summary to a repo-controlled path.
    No timestamps, stable sorting.
    """
    obj = {
        "suite_id": suite_id,
        "suite_version": suite_version,
        "cases": cases_out,
    }
    _write_json(path, obj)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default=str(BASE / "suites" / "v1" / "golden_pack.json"))
    ap.add_argument("--only", default="", help="Run only a single case_id")
    ap.add_argument("--update-hashes", action="store_true", help="Update expected_sha256 fields in suite file")
    ap.add_argument(
        "--unpinned-proof",
        action="store_true",
        help="Allow empty expected_sha256 values (skip equality only) for determinism proof runs.",
    )
    ap.add_argument(
        "--emit-run-hashes",
        default="",
        help="Write a deterministic run-hash summary JSON to this path (repo-controlled).",
    )
    args = ap.parse_args()

    suite_path = Path(args.suite).resolve()
    suite = _load_json(suite_path)
    if not isinstance(suite, dict):
        _die("bad suite json", 2)
    suite_id = str(suite.get("suite_id", "")).strip()
    cases = suite.get("cases", [])
    if not suite_id or not isinstance(cases, list):
        _die("bad suite schema", 2)

    only = str(args.only or "").strip()

    env = os.environ.copy()
    # Ensure the deterministic core sees pinned snapshot/bundle through payload; avoid ambient env pins.
    env.pop("NLC_EXTERNAL_SNAPSHOT_ID", None)
    env.pop("DCS_REPRO", None)
    env.pop("NLC_REPRO", None)
    # Gate0 requires snapshot binding via env to deterministically populate manifest_bundle_hash.
    env["NLC_DB_SNAPSHOT_ID"] = str(suite.get("knowledge_snapshot_id", "")).strip()
    env["NLC_SNAPSHOT_ID"] = str(suite.get("knowledge_snapshot_id", "")).strip()
    env["NLC_KB_SNAPSHOT_ID"] = str(suite.get("knowledge_snapshot_id", "")).strip()
    env["NLC_POLICY_VERSION"] = str(suite.get("policy_version", "")).strip()

    # Coverage preflight (deterministic, capability-bound). Fail fast before hashing anything.
    snapshot_id = str(suite.get("knowledge_snapshot_id", "")).strip()
    if snapshot_id:
        p = _run(
            [
                sys.executable,
                str(BASE / "scripts" / "verify_suite_coverage.py"),
                "--snapshot-id",
                snapshot_id,
                "--suite",
                str(suite_path),
            ],
            env=env,
        )
        if p.returncode != 0:
            # Must preserve the verifier's exact token line.
            sys.stdout.write((p.stdout or "").strip() + "\n")
            sys.stdout.flush()
            raise SystemExit(p.returncode or 1)

    updated = False
    run_hash_cases: List[Dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("case_id", "")).strip()
        if not case_id:
            continue
        if only and case_id != only:
            continue

        try:
            request_id = _sanitize_request_id(suite_id, case_id)
            rd = _request_dir(request_id)
            _cleanup_request_dir(rd)

            request_text = str(case.get("request_text", "")).strip()
            expected_status = str(case.get("expected_final_status", "")).strip().upper()
            if not request_text or not expected_status:
                _fail(f"FAIL suite:case_failed {case_id}", 2)

            _orch_gate0(request_id, request_text, env=env)
            _patch_payload(rd, suite=suite)

            got_status = _run_pipeline(request_id, env=env)
            if got_status != expected_status:
                _fail(f"FAIL suite:status_mismatch {case_id} {expected_status} {got_status}", 1)

            # Hash verification
            keys = _case_expected_keys(case)
            got_hashes = _collect_hashes(rd, keys)
            _compare_or_update_hashes(
                case=case,
                got_hashes=got_hashes,
                update_hashes=bool(args.update_hashes),
                unpinned_proof=bool(args.unpinned_proof),
            )
            if args.emit_run_hashes or args.unpinned_proof:
                run_hash_cases.append(
                    {
                        "case_id": case_id,
                        "request_id": request_id,
                        "expected_final_status": expected_status,
                        "got_hashes": {k: got_hashes.get(k, "") for k in sorted(got_hashes.keys())},
                    }
                )
            if args.update_hashes:
                updated = True
        except SystemExit:
            raise
        except Exception:
            _fail(f"FAIL suite:case_failed {case_id}", 1)

    if args.update_hashes and updated:
        # Enforce fully pinned suite after update: no empty expected hashes remain.
        for case in cases:
            if not isinstance(case, dict):
                continue
            exp = case.get("expected_sha256", {})
            if not isinstance(exp, dict):
                _fail(f"FAIL suite:case_failed {case.get('case_id','')}", 1)
            for _k, v in exp.items():
                if str(v).strip() == "":
                    _fail(f"FAIL suite:case_failed {case.get('case_id','')}", 1)
        _write_json(suite_path, suite)

    # In unpinned-proof mode, emit a deterministic summary under a repo-controlled path.
    emit_path = str(args.emit_run_hashes or "").strip()
    if args.unpinned_proof and not emit_path:
        emit_path = str(BASE / "state" / "suites" / suite_id / "run_hashes.json")
    if emit_path:
        _emit_run_hashes(
            Path(emit_path).resolve(),
            suite_id=suite_id,
            suite_version=suite.get("suite_version"),
            cases_out=run_hash_cases,
        )

    sys.stdout.write("SUITE_OK\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


