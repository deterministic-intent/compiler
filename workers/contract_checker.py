#!/usr/bin/env python3
"""
Step 6: Contract enforcement.

Deterministic validator that emits canonical failures (no side effects).
The verifier remains the oracle and the single writer for verifier outputs.
"""

from __future__ import annotations

import json
import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8", errors="replace"))


def load_contract_rules(repo_root: Path) -> Dict[str, Any]:
    rules_path = repo_root / "contracts" / "contract_rules.json"
    return _read_json(rules_path)


def _type_ok(val: Any, expected: str) -> bool:
    if expected == "str":
        return isinstance(val, str)
    if expected == "int":
        return isinstance(val, int) and not isinstance(val, bool)
    if expected == "list":
        return isinstance(val, list)
    if expected == "dict":
        return isinstance(val, dict)
    return False


def _is_path_traversal(p: str) -> bool:
    parts = Path(p).parts
    return any(part == ".." for part in parts)


def _is_absolute(p: str) -> bool:
    try:
        return Path(p).is_absolute()
    except Exception:
        return False


def _list_top_level(request_dir: Path) -> Tuple[List[str], List[str]]:
    files: List[str] = []
    dirs: List[str] = []
    for child in sorted(request_dir.iterdir(), key=lambda x: x.name):
        if child.is_dir():
            dirs.append(child.name)
        elif child.is_file():
            files.append(child.name)
    return files, dirs


def check_request_contract(
    repo_root: Path,
    request_dir: Path,
    gate_name: str,
) -> List[Dict[str, Any]]:
    """
    Return a list of canonical failure dicts for contract violations.
    Deterministic ordering and IDs are handled by canonicalize_failure().
    """
    from workers.failure_canonicalizer import canonicalize_failure, FailureKind, FailureSeverity, sort_failures

    rules = load_contract_rules(repo_root)
    failures = []

    # --- Schema checks (minimal required keys/types) ---
    schemas: Dict[str, Any] = rules.get("schemas", {})
    for rel_path, spec in sorted(schemas.items(), key=lambda kv: kv[0]):
        p = request_dir / rel_path
        # repair/status.json only required if repair dir exists
        if rel_path == "repair/status.json" and not (request_dir / "repair").exists():
            continue
        if not p.exists():
            # Only enforce schema file existence when the file is expected at/after gate1.
            # payload.json is always required for all gates >= gate0_init.
            if rel_path in ("payload.json",):
                failures.append(
                    canonicalize_failure(
                        kind=FailureKind.CONTRACT_VIOLATION,
                        artifact=rel_path,
                        locator=str(p),
                        message=f"contract schema file missing: {rel_path}",
                        repro=f"contract:schema:{rel_path}",
                        severity=FailureSeverity.BLOCKER,
                    )
                )
            continue
        try:
            obj = _read_json(p)
        except Exception as e:
            failures.append(
                canonicalize_failure(
                    kind=FailureKind.CONTRACT_VIOLATION,
                    artifact=rel_path,
                    locator=str(p),
                    message=f"contract schema file not valid JSON: {rel_path} ({e})",
                    repro=f"contract:schema:{rel_path}",
                    severity=FailureSeverity.BLOCKER,
                )
            )
            continue
        required: Dict[str, str] = (spec or {}).get("required_keys", {}) or {}
        if not isinstance(obj, dict):
            failures.append(
                canonicalize_failure(
                    kind=FailureKind.CONTRACT_VIOLATION,
                    artifact=rel_path,
                    locator=str(p),
                    message=f"contract schema file must be a JSON object: {rel_path}",
                    repro=f"contract:schema:{rel_path}",
                    severity=FailureSeverity.BLOCKER,
                )
            )
            continue
        for k, t in sorted(required.items(), key=lambda kv: kv[0]):
            if k not in obj:
                failures.append(
                    canonicalize_failure(
                        kind=FailureKind.CONTRACT_VIOLATION,
                        artifact=rel_path,
                        locator=str(p),
                        message=f"missing required key '{k}' in {rel_path}",
                        repro=f"contract:schema:{rel_path}",
                        severity=FailureSeverity.BLOCKER,
                    )
                )
                continue
            if not _type_ok(obj.get(k), t):
                failures.append(
                    canonicalize_failure(
                        kind=FailureKind.CONTRACT_VIOLATION,
                        artifact=rel_path,
                        locator=str(p),
                        message=f"key '{k}' in {rel_path} has wrong type (expected {t})",
                        repro=f"contract:schema:{rel_path}",
                        severity=FailureSeverity.BLOCKER,
                    )
                )

    # --- Path policy: deliverables must be safe relative paths ---
    payload_path = request_dir / "payload.json"
    payload_obj: Optional[Dict[str, Any]] = None
    if payload_path.exists():
        try:
            payload_obj = _read_json(payload_path)
        except Exception:
            payload_obj = None
    if isinstance(payload_obj, dict):
        deliverables = payload_obj.get("deliverables", [])
        deliverables_paths: set[str] = set()
        if isinstance(deliverables, list):
            for d in deliverables:
                if isinstance(d, dict):
                    dp = str(d.get("path", "")).strip()
                    if dp:
                        deliverables_paths.add(dp)
            path_policy = rules.get("path_policy", {}) or {}
            forbid_abs = bool(path_policy.get("forbid_absolute_paths", True))
            forbid_trav = bool(path_policy.get("forbid_path_traversal", True))
            for d in deliverables:
                if not isinstance(d, dict):
                    continue
                dp = str(d.get("path", "")).strip()
                if not dp:
                    continue
                if forbid_abs and _is_absolute(dp):
                    failures.append(
                        canonicalize_failure(
                            kind=FailureKind.CONTRACT_VIOLATION,
                            artifact="payload.json",
                            locator=str(payload_path),
                            message=f"deliverable path must be relative (absolute): {dp}",
                            repro="contract:path_policy",
                            severity=FailureSeverity.BLOCKER,
                        )
                    )
                if forbid_trav and _is_path_traversal(dp):
                    failures.append(
                        canonicalize_failure(
                            kind=FailureKind.CONTRACT_VIOLATION,
                            artifact="payload.json",
                            locator=str(payload_path),
                            message=f"deliverable path must not contain '..': {dp}",
                            repro="contract:path_policy",
                            severity=FailureSeverity.BLOCKER,
                        )
                    )

    # --- Deliverables presence (formal contract rule) ---
    # Request-dir deliverables (SPEC.md, TASKS.json, etc.) live at request_dir root.
    # Artifact-internal deliverables (e.g. MISSING_DELIVERABLE.txt) live in workspace/project.
    REQUEST_DIR_DELIVERABLES = {"SPEC.md", "TASKS.json", "PLAN.md", "NEEDS.json", "REQUEST.md", "payload.json"}
    enforced_gates = set((rules.get("deliverables", {}) or {}).get("enforced_gates", []))
    if gate_name in enforced_gates and isinstance(payload_obj, dict):
        deliverables = payload_obj.get("deliverables", [])
        if isinstance(deliverables, list):
            workspace_project = request_dir / "workspace" / "project"
            for d in deliverables:
                if not isinstance(d, dict):
                    continue
                dp = str(d.get("path", "")).strip()
                if not dp:
                    continue
                if dp in REQUEST_DIR_DELIVERABLES:
                    full = request_dir / dp
                else:
                    # Artifact-internal: must exist in workspace/project
                    full = workspace_project / dp if workspace_project.exists() else request_dir / dp
                ok = full.exists() and full.is_file() and full.stat().st_size > 0
                if not ok:
                    failures.append(
                        canonicalize_failure(
                            kind=FailureKind.CONTRACT_VIOLATION,
                            artifact=dp,
                            locator=str(full),
                            message=f"required deliverable missing: {dp}",
                            repro="contract:deliverables_exist",
                            severity=FailureSeverity.BLOCKER,
                        )
                    )

    # --- Filesystem drift (unexpected files/dirs) ---
    fs = rules.get("filesystem", {}) or {}
    allowed_files = set(fs.get("allowed_top_level_files", []) or [])
    allowed_file_globs = list(fs.get("allowed_top_level_file_globs", []) or [])
    allowed_dirs = set(fs.get("allowed_top_level_dirs", []) or [])
    files, dirs = _list_top_level(request_dir)
    for fn in files:
        # Any deliverable explicitly listed in payload is allowed to exist.
        if "deliverables_paths" in locals() and fn in deliverables_paths:
            continue
        if fn in allowed_files:
            continue
        if any(fnmatch.fnmatch(fn, g) for g in allowed_file_globs):
            continue
        failures.append(
            canonicalize_failure(
                kind=FailureKind.CONTRACT_VIOLATION,
                artifact=fn,
                locator=str(request_dir / fn),
                message=f"unexpected top-level file: {fn}",
                repro="contract:unexpected_file",
                severity=FailureSeverity.BLOCKER,
            )
        )
    for dn in dirs:
        if dn in allowed_dirs:
            continue
        failures.append(
            canonicalize_failure(
                kind=FailureKind.CONTRACT_VIOLATION,
                artifact=dn,
                locator=str(request_dir / dn),
                message=f"unexpected top-level directory: {dn}",
                repro="contract:unexpected_dir",
                severity=FailureSeverity.BLOCKER,
            )
        )

    # --- Verifier dir contents (single-writer-ish contract surface) ---
    vdir = request_dir / "verifier"
    if vdir.exists() and vdir.is_dir():
        allowed_v = set(fs.get("verifier_dir_allowed_files", []) or [])
        for child in sorted(vdir.iterdir(), key=lambda x: x.name):
            if not child.is_file():
                continue
            if child.name not in allowed_v:
                failures.append(
                    canonicalize_failure(
                        kind=FailureKind.CONTRACT_VIOLATION,
                        artifact=f"verifier/{child.name}",
                        locator=str(child),
                        message=f"unexpected file under verifier/: {child.name}",
                        repro="contract:verifier_dir_contents",
                        severity=FailureSeverity.BLOCKER,
                    )
                )

    # deterministically sorted
    failures_sorted = sort_failures(failures)
    return [f.to_dict() for f in failures_sorted]


if __name__ == "__main__":
    import sys
    repo = Path(__file__).resolve().parent
    if len(sys.argv) != 3:
        print("Usage: contract_checker.py <REQUEST_DIR> <GATE_NAME>")
        raise SystemExit(2)
    rd = Path(sys.argv[1])
    gate = sys.argv[2]
    out = check_request_contract(repo, rd, gate)
    print(json.dumps({"failures": out}, indent=2, sort_keys=True))


