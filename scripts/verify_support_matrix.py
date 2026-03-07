#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def _fail(msg: str) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(1)


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def _extract_set_from_code(path: Path, var_name: str) -> set[str]:
    text = _read_text(path)
    m = re.search(rf"{re.escape(var_name)}\s*=\s*\{{([^}}]*)\}}", text)
    if not m:
        return set()
    items = []
    for raw in m.group(1).split(","):
        val = raw.strip().strip('"').strip("'")
        if val:
            items.append(val)
    return set(items)


def _extract_requires_execute_contract_set(path: Path) -> set[str]:
    text = _read_text(path)
    for line in text.splitlines():
        if "return" in line and "in {" in line and "_requires_execute_contract" in text:
            m = re.search(r"\{\s*([^}]*)\s*\}", line)
            if not m:
                continue
            items = []
            for raw in m.group(1).split(","):
                val = raw.strip().strip('"').strip("'")
                if val:
                    items.append(val)
            if items:
                return set(items)
    return set()


def _extract_runtime_smoke_classes(path: Path) -> set[str]:
    text = _read_text(path)
    # Look for "if artifact_class == \"python_cli\" and gate in (\"gate4_review\"..."
    m = re.findall(r"artifact_class\s*==\s*[\"']([^\"']+)[\"']\s*and\s*gate\s*in\s*\(", text)
    return set(m)


def _load_capabilities(snapshot_id: str) -> dict:
    caps_path = BASE / "nlc" / "db" / "snapshots" / snapshot_id / "capabilities.json"
    if not caps_path.exists():
        _fail(f"FAIL support_matrix: capabilities.json missing for snapshot {snapshot_id}")
    try:
        return json.loads(_read_text(caps_path))
    except Exception as e:
        _fail(f"FAIL support_matrix: capabilities.json invalid JSON: {e}")
    return {}


def _build_matrix(snapshot_id: str) -> str:
    caps = _load_capabilities(snapshot_id)
    languages = caps.get("languages", [])
    supported = caps.get("supported_artifact_classes", [])
    truth_backed = caps.get("truth_backed_artifact_classes", [])
    if not isinstance(languages, list) or not isinstance(supported, list) or not isinstance(truth_backed, list):
        _fail("FAIL support_matrix: capabilities fields must be lists")

    systems_path = BASE / "workers" / "run_systems.py"
    verifier_path = BASE / "workers" / "run_verifier.py"

    exec_emit = _extract_set_from_code(systems_path, "runtime_truth_classes")
    exec_enforced = _extract_requires_execute_contract_set(verifier_path)

    runtime_smoke = _extract_runtime_smoke_classes(verifier_path)

    # Enforce truth-backed requirements
    for ac in truth_backed:
        if ac not in exec_emit or ac not in exec_enforced:
            _fail(f"FAIL support_matrix: truth-backed {ac} lacks EXECUTE.json emission or verifier enforcement")

    # Ensure exec emission and enforcement agree
    if exec_emit != exec_enforced:
        _fail(f"FAIL support_matrix: EXECUTE.json emission/enforcement mismatch: emit={sorted(exec_emit)} enforce={sorted(exec_enforced)}")

    lines = []
    lines.append("# Support Matrix\n\n")
    lines.append(f"Generated from code and snapshot `{snapshot_id}`.\n\n")
    lines.append("## Claimed (capabilities.json)\n\n")
    lines.append(f"- languages: {', '.join([f'`{l}`' for l in languages])}\n")
    lines.append(f"- supported_artifact_classes: {', '.join([f'`{c}`' for c in supported])}\n")
    lines.append(f"- truth_backed_artifact_classes: {', '.join([f'`{c}`' for c in truth_backed])}\n\n")
    lines.append("## Artifact Class Support\n\n")
    lines.append("| artifact_class | emits dist/EXECUTE.json | runtime smoke validation | user-verify runnable contract | truth-backed |\n")
    lines.append("| --- | --- | --- | --- | --- |\n")
    for ac in supported:
        emits = "Y" if ac in exec_emit else "N"
        smoke = "Y" if ac in runtime_smoke else "N"
        user_verify = "Y" if ac in exec_emit else "N"
        tb = "Y" if ac in truth_backed else "N"
        lines.append(f"| {ac} | {emits} | {smoke} | {user_verify} | {tb} |\n")
    return "".join(lines)


def main() -> int:
    snapshot_id = (os.environ.get("DCS_PROOF_SNAPSHOT_ID") or os.environ.get("AUDIT_CLOSURE_SNAPSHOT") or os.environ.get("NLC_DB_SNAPSHOT_ID") or "").strip()
    if not snapshot_id:
        _fail("MISSING_SNAPSHOT_ID: set DCS_PROOF_SNAPSHOT_ID or NLC_DB_SNAPSHOT_ID")
    out = _build_matrix(snapshot_id)
    doc_path = BASE / "docs" / "SUPPORT_MATRIX.md"
    if not doc_path.exists():
        _fail("FAIL support_matrix: docs/SUPPORT_MATRIX.md missing")
    current = _read_text(doc_path)
    if current != out:
        _fail("FAIL support_matrix: SUPPORT_MATRIX.md does not match code+snapshot")
    print("PASS support_matrix")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

