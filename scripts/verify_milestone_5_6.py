#!/usr/bin/env python3
"""
Milestone 5.6: Python Debug Script Proof

Tests three cases:
- Case A: Syntax error → PASS_AFTER_REPAIR
- Case B: Runtime exception → PASS_AFTER_REPAIR
- Case C: No bug → PASS (no repair)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import hashlib
import shutil
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_dir(root: Path) -> str:
    entries = []
    for p in sorted([f for f in root.rglob("*") if f.is_file()], key=lambda x: str(x)):
        rel = str(p.relative_to(root)).replace("\\", "/")
        entries.append(rel + ":" + _sha256_file(p))
    return hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()


def _fail(msg: str):
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def _run_dcs_run(dcs_path: Path) -> tuple[int, str, str]:
    """Run .dcs file through pipeline."""
    cmd = [sys.executable, str(BASE / "dcs_cli" / "main.py"), "run", str(dcs_path)]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BASE))
    return (p.returncode, p.stdout, p.stderr)


def _get_manifest_bundle_hash(snapshot_id: str) -> str:
    from nlc.reproducibility import get_manifest_hashes
    info = get_manifest_hashes(snapshot_id)
    return str(info.get("manifest_bundle_hash", "")).strip()


def _write_dcs(path: Path, content: dict):
    path.write_text(json.dumps(content, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _assert_truth_anchors(report_text: str):
    if "## Truth Anchors" not in report_text:
        _fail("Report missing Truth Anchors section")
    if "Clamp Summary" not in report_text:
        _fail("Report missing Clamp Summary section")
    for line in report_text.splitlines():
        if line.startswith("Cause:"):
            if "step_" not in line or "stderr_sha256=" not in line or "debug/repro/" not in line:
                _fail("Report Cause line not evidence-anchored")
    if "T" in report_text:
        import re
        if re.search(r"\d{4}-\d{2}-\d{2}T", report_text):
            _fail("Report contains timestamp")


def _assert_debug_artifacts(request_dir: Path):
    debug_dir = request_dir / "debug"
    report_md = debug_dir / "report.md"
    report_json = debug_dir / "report.json"
    repro_dir = debug_dir / "repro"
    steps_json = repro_dir / "steps.json"
    if not report_md.exists():
        _fail("report.md missing")
    if not report_json.exists():
        _fail("report.json missing")
    if not steps_json.exists():
        _fail("steps.json missing")
    steps_obj = json.loads(steps_json.read_text(encoding="utf-8", errors="replace"))
    steps = steps_obj.get("steps", [])
    if not steps:
        _fail("steps.json missing steps list")
    for step in steps:
        step_name = step.get("step", "")
        if not step_name:
            _fail("steps.json has empty step name")
        step_dir = repro_dir / step_name
        for fname in ("cmd.json", "exit_code.json", "stdout.sha256", "stderr.sha256"):
            if not (step_dir / fname).exists():
                _fail(f"missing {step_name}/{fname}")
    report_text = report_md.read_text(encoding="utf-8", errors="replace")
    _assert_truth_anchors(report_text)
    return json.loads(report_json.read_text(encoding="utf-8", errors="replace"))


def test_case_a_syntax_error(snapshot_id: str, bundle_hash: str):
    print("\n--- Case A: Syntax error ---")
    test_dir = BASE / "state" / "test_m56_case_a"
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir(parents=True)

    dcs_file = test_dir / "test.dcs"
    dcs_content = {
        "request_id": "M56_CASE_A",
        "artifact_class": "python_debug_script",
        "goal": "debug_script syntax error case",
        "constraints": [],
        "non_goals": [],
        "policy_version": "v1",
        "knowledge_snapshot_id": snapshot_id,
        "manifest_bundle_hash": bundle_hash,
        "files": {
            "main.py": "def hello():\n    print('hello'\n    # Missing closing paren"
        },
        "entrypoint": "main.py",
        "runtime_args": [],
    }
    _write_dcs(dcs_file, dcs_content)

    _run_dcs_run(dcs_file)
    request_dir = BASE / "state" / "requests" / "M56_CASE_A"
    if not request_dir.exists():
        _fail("Case A: Request directory not created")

    report_data = _assert_debug_artifacts(request_dir)
    proposal_diff = request_dir / "debug" / "proposal.diff"
    if not proposal_diff.exists():
        _fail("Case A: proposal.diff missing")

    repair_status = request_dir / "repair" / "status.json"
    if not repair_status.exists():
        _fail("Case A: repair/status.json missing")
    status_obj = json.loads(repair_status.read_text(encoding="utf-8", errors="replace"))
    if status_obj.get("final_status") != "PASS_AFTER_REPAIR":
        _fail(f"Case A: Expected PASS_AFTER_REPAIR, got {status_obj.get('final_status')}")
    
    # Pre-repair report must show compile failure
    pre_report_json = request_dir / "repair" / "iter_0" / "debug_pre" / "report.json"
    if not pre_report_json.exists():
        _fail("Case A: pre-repair report.json missing")
    pre_report = json.loads(pre_report_json.read_text(encoding="utf-8", errors="replace"))
    if pre_report.get("status") != "FAIL":
        _fail(f"Case A: Expected pre-repair status FAIL, got {pre_report.get('status')}")
    if not pre_report.get("compile_failures"):
        _fail("Case A: Expected pre-repair compile failures")

    # Replay must be byte-identical
    debug_hash_before = _hash_dir(request_dir / "debug")
    cmd = [sys.executable, str(BASE / "scripts" / "run_replay.py"), request_dir.name]
    subprocess.run(cmd, capture_output=True, text=True, cwd=str(BASE))
    debug_hash_after = _hash_dir(request_dir / "debug")
    if debug_hash_before != debug_hash_after:
        _fail("Case A: Replay not byte-identical for debug artifacts")

    print("✓ Case A: PASS_AFTER_REPAIR + replay identical")


def test_case_b_runtime_exception(snapshot_id: str, bundle_hash: str):
    print("\n--- Case B: Runtime exception ---")
    test_dir = BASE / "state" / "test_m56_case_b"
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir(parents=True)

    dcs_file = test_dir / "test.dcs"
    dcs_content = {
        "request_id": "M56_CASE_B",
        "artifact_class": "python_debug_script",
        "goal": "debug_script runtime error case",
        "constraints": [],
        "non_goals": [],
        "policy_version": "v1",
        "knowledge_snapshot_id": snapshot_id,
        "manifest_bundle_hash": bundle_hash,
        "files": {
            "main.py": "def divide(a, b):\n    return a / b\n\nif __name__ == '__main__':\n    result = divide(10, 0)\n    print(result)"
        },
        "entrypoint": "main.py",
        "runtime_args": [],
    }
    _write_dcs(dcs_file, dcs_content)

    _run_dcs_run(dcs_file)
    request_dir = BASE / "state" / "requests" / "M56_CASE_B"
    if not request_dir.exists():
        _fail("Case B: Request directory not created")

    report_data = _assert_debug_artifacts(request_dir)
    proposal_diff = request_dir / "debug" / "proposal.diff"
    if not proposal_diff.exists():
        _fail("Case B: proposal.diff missing")

    repair_status = request_dir / "repair" / "status.json"
    if not repair_status.exists():
        _fail("Case B: repair/status.json missing")
    status_obj = json.loads(repair_status.read_text(encoding="utf-8", errors="replace"))
    if status_obj.get("final_status") != "PASS_AFTER_REPAIR":
        _fail(f"Case B: Expected PASS_AFTER_REPAIR, got {status_obj.get('final_status')}")
    
    pre_report_json = request_dir / "repair" / "iter_0" / "debug_pre" / "report.json"
    if not pre_report_json.exists():
        _fail("Case B: pre-repair report.json missing")
    pre_report = json.loads(pre_report_json.read_text(encoding="utf-8", errors="replace"))
    if not pre_report.get("compile_success"):
        _fail("Case B: Expected pre-repair compile success")
    if pre_report.get("run_success"):
        _fail("Case B: Expected pre-repair run failure")

    debug_hash_before = _hash_dir(request_dir / "debug")
    cmd = [sys.executable, str(BASE / "scripts" / "run_replay.py"), request_dir.name]
    subprocess.run(cmd, capture_output=True, text=True, cwd=str(BASE))
    debug_hash_after = _hash_dir(request_dir / "debug")
    if debug_hash_before != debug_hash_after:
        _fail("Case B: Replay not byte-identical for debug artifacts")

    print("✓ Case B: PASS_AFTER_REPAIR + replay identical")


def test_case_c_no_bug(snapshot_id: str, bundle_hash: str):
    print("\n--- Case C: No bug ---")
    test_dir = BASE / "state" / "test_m56_case_c"
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir(parents=True)

    dcs_file = test_dir / "test.dcs"
    dcs_content = {
        "request_id": "M56_CASE_C",
        "artifact_class": "python_debug_script",
        "goal": "debug_script no bug case",
        "constraints": [],
        "non_goals": [],
        "policy_version": "v1",
        "knowledge_snapshot_id": snapshot_id,
        "manifest_bundle_hash": bundle_hash,
        "files": {
            "main.py": "def hello():\n    print('Hello, world!')\n\nif __name__ == '__main__':\n    hello()"
        },
        "entrypoint": "main.py",
        "runtime_args": [],
    }
    _write_dcs(dcs_file, dcs_content)

    _run_dcs_run(dcs_file)
    request_dir = BASE / "state" / "requests" / "M56_CASE_C"
    if not request_dir.exists():
        _fail("Case C: Request directory not created")

    report_data = _assert_debug_artifacts(request_dir)
    if report_data.get("status") != "PASS":
        _fail(f"Case C: Expected status PASS, got {report_data.get('status')}")
    proposal_diff = request_dir / "debug" / "proposal.diff"
    if proposal_diff.exists():
        _fail("Case C: proposal.diff should not exist")

    print("✓ Case C: PASS (no repair)")


def test_determinism(snapshot_id: str, bundle_hash: str):
    print("\n--- Determinism test ---")
    test_dir = BASE / "state" / "test_m56_determinism"
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir(parents=True)

    dcs_file = test_dir / "test.dcs"
    dcs_content = {
        "request_id": "M56_DETERMINISM",
        "artifact_class": "python_debug_script",
        "goal": "debug_script determinism case",
        "constraints": [],
        "non_goals": [],
        "policy_version": "v1",
        "knowledge_snapshot_id": snapshot_id,
        "manifest_bundle_hash": bundle_hash,
        "files": {
            "main.py": "print('test')"
        },
        "entrypoint": "main.py",
        "runtime_args": [],
    }
    _write_dcs(dcs_file, dcs_content)

    _run_dcs_run(dcs_file)
    request_dir = BASE / "state" / "requests" / "M56_DETERMINISM"
    if not request_dir.exists():
        _fail("Determinism: Request directory not created")
    hash1 = _hash_dir(request_dir / "debug")

    shutil.rmtree(request_dir)
    _run_dcs_run(dcs_file)
    request_dir = BASE / "state" / "requests" / "M56_DETERMINISM"
    hash2 = _hash_dir(request_dir / "debug")

    if hash1 != hash2:
        _fail("Determinism: debug artifacts differ across runs")

    print("✓ Determinism: debug artifacts identical across runs")


def main():
    print("=== Milestone 5.6 Proof: Python Debug Script ===")
    snapshot_id = os.environ.get("NLC_DB_SNAPSHOT_ID", "").strip()
    if not snapshot_id:
        # Deterministically select latest snapshot with manifest bundle hash
        snaps_root = BASE / "nlc" / "db" / "snapshots"
        ids = sorted([p.name for p in snaps_root.iterdir() if p.is_dir()]) if snaps_root.exists() else []
        if not ids:
            _fail("No snapshots found for proof")
        # Prefer timestamp-shaped ids
        ts_ids = [s for s in ids if len(s) == 16 and s.endswith("Z")]
        snapshot_id = (sorted(ts_ids) if ts_ids else ids)[-1]
        os.environ["NLC_DB_SNAPSHOT_ID"] = snapshot_id
    bundle_hash = _get_manifest_bundle_hash(snapshot_id)
    if not bundle_hash:
        _fail("manifest_bundle_hash missing for snapshot")

    test_case_a_syntax_error(snapshot_id, bundle_hash)
    test_case_b_runtime_exception(snapshot_id, bundle_hash)
    test_case_c_no_bug(snapshot_id, bundle_hash)
    test_determinism(snapshot_id, bundle_hash)

    print("\n✓ Milestone 5.6 proof: All tests passed")
    print("M56_PROOF_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

