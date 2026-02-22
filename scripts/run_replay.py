#!/usr/bin/env python3
"""
Step 7: Replay mode (deterministic re-execution).

Rules:
- No LLM calls.
- Must verify snapshot pins (knowledge_snapshot_id + manifest_bundle_hash) and toolchain pins.
- Must not regenerate planner/generator outputs.
- Must not mutate snapshots.
- Produces byte-identical verifier outputs by verifying and then copying original bytes.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

import sys

# Repo root
BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


@dataclass
class ReplayError(Exception):
    message: str
    code: int = 2
    repro: str = "replay:error"


def die(msg: str, code: int = 2, repro: str = "replay:error"):
    raise ReplayError(msg, code=code, repro=repro)


def _read_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8", errors="replace"))


def _write_json(p: Path, obj: Any):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_payload(request_dir: Path) -> Dict[str, Any]:
    payload_path = request_dir / "payload.json"
    if not payload_path.exists():
        die("payload.json missing", repro="replay:missing_payload")
    obj = _read_json(payload_path)
    if not isinstance(obj, dict):
        die("payload.json must be a JSON object", repro="replay:payload_schema")
    return obj


def _verify_pins(payload: Dict[str, Any]) -> Tuple[str, str, str]:
    policy_version = str(payload.get("policy_version", "")).strip()
    snapshot_id = payload.get("knowledge_snapshot_id")
    bundle_hash = payload.get("manifest_bundle_hash")
    if not policy_version:
        die("payload.json.policy_version missing", repro="replay:pin_missing:policy_version")
    if not snapshot_id:
        die("payload.json.knowledge_snapshot_id missing", repro="replay:pin_missing:knowledge_snapshot_id")
    if not bundle_hash:
        die("payload.json.manifest_bundle_hash missing", repro="replay:pin_missing:manifest_bundle_hash")
    return policy_version, str(snapshot_id), str(bundle_hash)


def _verify_manifest_bundle_hash(snapshot_id: str, expected_bundle_hash: str):
    # Must read only from pinned snapshot manifests; must not rebuild.
    from nlc.reproducibility import get_manifest_hashes

    info = get_manifest_hashes(snapshot_id)
    got = str(info.get("manifest_bundle_hash", "")).strip()
    if not got:
        die(f"manifest_bundle_hash not found for snapshot {snapshot_id}", repro="replay:pin_missing:manifest_bundle_hash")
    if got != expected_bundle_hash:
        die(
            f"manifest_bundle_hash mismatch: expected={expected_bundle_hash} got={got}",
            repro="replay:pin_mismatch:manifest_bundle_hash",
        )


def _verify_toolchain_pins(snapshot_id: str, policy_version: str):
    pins_path = BASE / "nlc" / "db" / "snapshots" / snapshot_id / "manifest" / "toolchain_pins.json"
    if not pins_path.exists():
        die(f"toolchain_pins.json missing for snapshot {snapshot_id}", repro="replay:pin_missing:toolchain_pins")
    pins = _read_json(pins_path)
    if isinstance(pins, dict):
        pv = pins.get("policy_version")
        if pv and str(pv).strip() != policy_version:
            die(
                f"toolchain_pins policy_version mismatch: expected={policy_version} got={pv}",
                repro="replay:pin_mismatch:toolchain_pins_policy_version",
            )


def _semantic_equal_verifier_result(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    # Allow timestamps to differ; everything else must match.
    def strip_ts(x: Dict[str, Any]) -> Dict[str, Any]:
        y = dict(x)
        y.pop("started_at", None)
        y.pop("ended_at", None)
        return y
    return strip_ts(a) == strip_ts(b)


def main() -> int:
    os.environ["DCS_REPRO"] = "1"  # Replay: no network; deterministic failure on any network attempt
    from nlc.net_guard import activate_network_guard
    activate_network_guard()
    ap = argparse.ArgumentParser()
    ap.add_argument("request_id")
    ap.add_argument("gate_name")
    ap.add_argument("--replay-id", default="replay1")
    args = ap.parse_args()

    request_id = args.request_id
    gate = args.gate_name
    replay_id = args.replay_id

    request_dir = BASE / "state" / "requests" / request_id
    replay_dir = request_dir / "replay" / replay_id
    if replay_dir.exists():
        shutil.rmtree(replay_dir, ignore_errors=True)
    replay_dir.mkdir(parents=True, exist_ok=True)

    def write_fail(err: ReplayError) -> int:
        from workers.failure_canonicalizer import canonicalize_failure, FailureKind, FailureSeverity

        failure = canonicalize_failure(
            kind=FailureKind.CONTRACT_VIOLATION,
            artifact="replay",
            locator=str(request_dir),
            message=err.message,
            repro=err.repro,
            severity=FailureSeverity.BLOCKER,
        ).to_dict()
        _write_json(replay_dir / "status.json", {"status": "FAIL", "reason": err.repro, "message": err.message})
        _write_json(replay_dir / "failures.json", {"failures": [failure]})
        print(f"ERROR: {err.message}")
        return err.code

    try:
        if not request_dir.exists():
            die(f"request dir not found: {request_dir}", repro="replay:missing_request_dir")

        # Pins
        payload = _load_payload(request_dir)
        policy_version, snapshot_id, expected_bundle_hash = _verify_pins(payload)
        _verify_manifest_bundle_hash(snapshot_id, expected_bundle_hash)
        _verify_toolchain_pins(snapshot_id, policy_version)

        # IR byte-equality: compare REQ.json to pinned hash (replay_pins.json or payload.req_sha256)
        req_path = request_dir / "REQ.json"
        if req_path.exists():
            req_bytes = req_path.read_bytes()
            req_sha256 = __import__("hashlib").sha256(req_bytes).hexdigest()
            pin_req_hash = str(payload.get("req_sha256", "")).strip()
            if not pin_req_hash:
                pins_path = request_dir / "replay_pins.json"
                if pins_path.exists():
                    try:
                        pins = _read_json(pins_path)
                        pin_req_hash = str(pins.get("req_sha256", "")).strip()
                    except Exception:
                        pass
            if pin_req_hash and pin_req_hash != req_sha256:
                die(
                    f"REPLAY.IR_MISMATCH: REQ.json bytes differ from pinned hash expected={pin_req_hash} got={req_sha256}",
                    repro="replay:REPLAY.IR_MISMATCH",
                )

        # Original verifier outputs (source of truth for byte-identical replay output)
        orig_verifier_dir = request_dir / "verifier"
        orig_result_path = orig_verifier_dir / "verifier.result.json"
        orig_failures_path = orig_verifier_dir / "failures.json"
        if not orig_result_path.exists() or not orig_failures_path.exists():
            die("original verifier outputs missing under request_dir/verifier/", repro="replay:missing_verifier_outputs")

        orig_result = _read_json(orig_result_path)
        orig_failures = _read_json(orig_failures_path)

        # Deterministic re-execution: run verifier logic in-memory (no file writes), then compare.
        from workers.run_verifier import verify_gate
        status, _text, failures = verify_gate(request_id, gate, request_dir)

        computed_failures_obj = {
            "request_id": request_id,
            "policy_version": policy_version,
            "knowledge_snapshot_id": payload.get("knowledge_snapshot_id"),
            "manifest_bundle_hash": payload.get("manifest_bundle_hash"),
            "failures": failures,
        }

        if not isinstance(orig_failures, dict) or orig_failures.get("failures") != computed_failures_obj.get("failures"):
            die("replay verifier mismatch: failures differ from original", repro="replay:verifier_mismatch:failures")
        if not isinstance(orig_result, dict):
            die("original verifier.result.json must be an object", repro="replay:verifier_mismatch:result_schema")
        if str(orig_result.get("status", "")).strip() != status:
            die(
                f"replay verifier mismatch: status differs from original (orig={orig_result.get('status')} replay={status})",
                repro="replay:verifier_mismatch:status",
            )

        replay_verifier_dir = replay_dir / "verifier"
        replay_verifier_dir.mkdir(parents=True, exist_ok=True)

        # Byte-identical: copy original bytes
        shutil.copy2(orig_result_path, replay_verifier_dir / "verifier.result.json")
        shutil.copy2(orig_failures_path, replay_verifier_dir / "failures.json")

        status_obj = {
            "status": "PASS",
            "request_id": request_id,
            "gate_name": gate,
            "replay_id": replay_id,
            "policy_version": policy_version,
            "knowledge_snapshot_id": snapshot_id,
            "manifest_bundle_hash": expected_bundle_hash,
        }
        _write_json(replay_dir / "status.json", status_obj)
        return 0
    except ReplayError as e:
        return write_fail(e)


if __name__ == "__main__":
    raise SystemExit(main())


