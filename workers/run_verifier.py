#!/usr/bin/env python3
import sys
import json
import hashlib
import os
import re
import traceback
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict, Any

# Deterministic verifier: NO external model calls.
# It only inspects REQUEST_DIR artifacts and reports PASS/FAIL/BLOCKED.

# Ensure repository root is on sys.path when run as a script.
BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from nlc.paths import deliverables_root, verifier_root  # canonical roots

# Policy loader (optional - for future policy-aware verification)
try:
    from policy import load_policy, get_default_policy_version
except ImportError:
    load_policy = None
    get_default_policy_version = None


def get_policy_for_verification(request_dir: Path, policy_version: Optional[str] = None):
    """
    Get policy for verification. Step 1: wiring only - no enforcement yet.
    
    Helper only locates policy_version and calls load_policy().
    All enforcement logic lives elsewhere (not in helpers).
    
    Args:
        request_dir: Request directory (may contain payload.json with policy_version)
        policy_version: Optional explicit policy version
    
    Returns:
        Policy object or None if policy module unavailable or load fails
    """
    if load_policy is None:
        return None
    
    # Try to load from payload.json if not explicitly provided
    if policy_version is None:
        payload_path = request_dir / "payload.json"
        if payload_path.exists():
            try:
                payload = json.loads(payload_path.read_text(encoding="utf-8", errors="replace"))
                policy_version = payload.get("policy_version")
            except Exception:
                pass
    
    if policy_version is None:
        if get_default_policy_version:
            policy_version = get_default_policy_version()
        else:
            return None
    
    try:
        return load_policy(policy_version)
    except Exception:
        return None

ALLOWED_GATES = {
    "gate0_init",
    "gate1_planning",
    "gate2_delegation",
    "gate3_execution",
    "gate4_review",
    "gate5_finalize",
    "gate6_complete",
}

STOP_TOKEN = "END_OF_RESPONSE"

def now_utc() -> str:
    # Deterministic timestamp for verifier outputs (no wall-clock time).
    return "1970-01-01T00:00:00Z"

def sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()

def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")

def write_text(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")

def _requires_execute_contract(artifact_class: str) -> bool:
    return str(artifact_class or "").strip() in {"python_cli"}

def die(msg: str, code: int = 2):
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)

def file_exists_nonempty(p: Path) -> bool:
    try:
        return p.exists() and p.is_file() and p.stat().st_size > 0 and read_text(p).strip() != ""
    except Exception:
        return False

def is_valid_tasks_json(tasks_path: Path) -> tuple[bool, str]:
    # TASKS.json is JSON-by-contract in this repo.
    if not file_exists_nonempty(tasks_path):
        return (False, "TASKS.json missing or empty")
    try:
        obj = json.loads(read_text(tasks_path))
    except Exception:
        return (False, "TASKS.json is not valid JSON")
    if not isinstance(obj, dict) or "tasks" not in obj or not isinstance(obj["tasks"], list):
        return (False, "TASKS.json JSON must be an object with a 'tasks' list")
    return (True, "")

def summarize_missing(request_dir: Path, names: list[str]) -> list[str]:
    missing = []
    for n in names:
        p = request_dir / n
        if not file_exists_nonempty(p):
            missing.append(n)
    return missing

def gate_requirements(request_dir: Path, gate: str) -> tuple[list[str], list[str]]:
    """
    Authoritative gate requirements per spec:
    - Orchestrator is the state machine.
    - Planner produces SPEC.md, TASKS.json, PLAN.md (and optional NEEDS.json).
    - NO DISPATCH.md in the system.
    - Developer produces code artifacts in workspace/project/
    - Systems produces dist/ artifacts deterministically
    """
    if gate == "gate0_init":
        return (["REQUEST.md", "payload.json", "state.json"], [])
    if gate == "gate1_planning":
        return (["REQUEST.md", "payload.json", "snapshot_resolution.json", "SPEC.md", "TASKS.json", "PLAN.md"], ["NEEDS.json"])
    if gate == "gate2_delegation":
        # State label only: ensure planning artifacts exist; NO dispatch artifact required.
        return (["REQUEST.md", "payload.json", "SPEC.md", "TASKS.json", "PLAN.md"], ["NEEDS.json"])
    if gate == "gate3_execution":
        # If python_debug_script, require debug artifacts instead of workspace/project
        artifact_class = ""
        payload_path = request_dir / "payload.json"
        if payload_path.exists():
            try:
                payload = json.loads(read_text(payload_path))
                artifact_class = str(payload.get("artifact_class", "")).strip()
            except Exception:
                artifact_class = ""
        if artifact_class == "python_debug_script":
            return ([
                "REQUEST.md",
                "payload.json",
                "debug/repro/steps.json",
                "debug/report.md",
                "debug/report.json",
            ], ["NEEDS.json"])
        # Default: check developer produced required project structure + REQ.json for structured intents
        return (["REQUEST.md", "payload.json", "SPEC.md", "TASKS.json", "PLAN.md", "REQ.json"], ["NEEDS.json"])
    if gate == "gate4_review":
        # Scope validation vs REQUEST.md + SPEC.md (deterministic heuristics + required artifacts)
        return (["REQUEST.md", "payload.json", "SPEC.md", "TASKS.json", "PLAN.md"], ["NEEDS.json"])
    if gate == "gate5_finalize":
        # dist artifact exists + checksums + entrypoint docs
        return (["REQUEST.md", "payload.json"], ["SPEC.md", "TASKS.json", "PLAN.md", "NEEDS.json"])
    if gate == "gate6_complete":
        # Verifies all deliverables present, final manifest, no pending failures
        return (["REQUEST.md", "payload.json"], ["SPEC.md", "TASKS.json", "PLAN.md", "NEEDS.json"])
    return (["REQUEST.md"], [])

def build_prompt_dump(request_id: str, gate: str, request_dir: Path) -> str:
    # Deterministic “what I checked” record (NOT an external model prompt).
    reqs, opts = gate_requirements(request_dir, gate)
    lines = []
    lines.append(f"REQUEST_ID: {request_id}")
    lines.append(f"GATE: {gate}")
    lines.append(f"REQUEST_DIR: {request_dir}")
    lines.append("")
    lines.append("REQUIRED_FILES:")
    for f in reqs:
        p = request_dir / f
        lines.append(f"- {f}: {'OK' if file_exists_nonempty(p) else 'MISSING/EMPTY'}")
    lines.append("")
    lines.append("OPTIONAL_FILES:")
    for f in opts:
        p = request_dir / f
        lines.append(f"- {f}: {'OK' if file_exists_nonempty(p) else 'MISSING/EMPTY'}")
    lines.append("")
    if (request_dir / "TASKS.json").exists():
        ok, why = is_valid_tasks_json(request_dir / "TASKS.json")
        lines.append(f"TASKS.json_json_valid: {ok}")
        if not ok:
            lines.append(f"TASKS.json_issue: {why}")
    return "\n".join(lines) + "\n"


def verify_intent_fulfillment(request_dir: Path, workspace_project: Path) -> tuple[bool, list[str]]:
    """Verify that generated code fulfills REQ.json intents. Returns (is_valid, failures)."""
    req_path = request_dir / "REQ.json"
    if not req_path.exists():
        return (False, ["REQ.json missing"])
    
    try:
        req_obj = json.loads(read_text(req_path))
        intents = req_obj.get("intents", [])
        failures = []
        
        for intent in intents:
            intent_type = intent.get("intent_type")
            params = intent.get("params", {})
            
            # Check if code implements the intent
            if intent_type == "print_sequence":
                # Check that generated code contains range/print logic
                py_files = list(workspace_project.glob("*.py"))
                if not py_files:
                    failures.append(f"Intent '{intent_type}': No Python files found")
                    continue
                
                # Read first Python file and check for sequence logic
                code_content = read_text(py_files[0]).lower()
                from_val = params.get("from", 1)
                to_val = params.get("to")
                
                # Check for range or loop that could print sequence
                has_range = "range" in code_content or "for" in code_content
                has_print = "print" in code_content
                
                if not has_range or not has_print:
                    failures.append(f"Intent '{intent_type}': Code missing range/print logic")
            
            # Add more intent checks here as new intents are added
        
        return (len(failures) == 0, failures)
    except Exception as e:
        return (False, [f"Error validating REQ.json: {str(e)}"])


def _verify_debug_artifacts(request_dir: Path) -> tuple[str, str, list[dict]]:
    """
    Verify python_debug_script artifacts for gate3_execution.
    Returns (status, message, failures).
    """
    from workers.failure_canonicalizer import canonicalize_failure, FailureKind, FailureSeverity
    failures: list[dict] = []
    debug_dir = request_dir / "debug"
    repro_dir = debug_dir / "repro"
    steps_path = repro_dir / "steps.json"
    report_md = debug_dir / "report.md"
    report_json = debug_dir / "report.json"
    
    # Required base artifacts
    required_paths = [steps_path, report_md, report_json]
    missing = [str(p.relative_to(request_dir)) for p in required_paths if not p.exists()]
    if missing:
        msg = f"debug:missing_artifacts missing={missing}"
        failures.append(canonicalize_failure(
            kind=FailureKind.VERIFIER_ERROR,
            artifact="debug",
            locator=str(debug_dir),
            message=msg,
            repro="verify_gate:gate3_execution:debug_missing_artifacts",
            severity=FailureSeverity.BLOCKER,
        ).to_dict())
        lines = ["FAIL", "EVIDENCE:", f"- {msg}", "REQUIRED_ACTIONS:", "- Provide required debug artifacts.", STOP_TOKEN]
        return ("FAIL", "\n".join(lines) + "\n", failures)
    
    # Load steps.json
    try:
        steps_obj = json.loads(read_text(steps_path))
    except Exception as e:
        msg = f"debug:missing_artifacts invalid_steps_json: {e}"
        failures.append(canonicalize_failure(
            kind=FailureKind.VERIFIER_ERROR,
            artifact="debug/repro/steps.json",
            locator=str(steps_path),
            message=msg,
            repro="verify_gate:gate3_execution:debug_steps_json_invalid",
            severity=FailureSeverity.BLOCKER,
        ).to_dict())
        lines = ["FAIL", "EVIDENCE:", f"- {msg}", "REQUIRED_ACTIONS:", "- Provide valid steps.json.", STOP_TOKEN]
        return ("FAIL", "\n".join(lines) + "\n", failures)
    
    steps = steps_obj.get("steps", [])
    if not isinstance(steps, list) or not steps:
        msg = "debug:missing_artifacts steps.json missing steps list"
        failures.append(canonicalize_failure(
            kind=FailureKind.VERIFIER_ERROR,
            artifact="debug/repro/steps.json",
            locator=str(steps_path),
            message=msg,
            repro="verify_gate:gate3_execution:debug_steps_missing",
            severity=FailureSeverity.BLOCKER,
        ).to_dict())
        lines = ["FAIL", "EVIDENCE:", f"- {msg}", "REQUIRED_ACTIONS:", "- steps.json must list executed steps.", STOP_TOKEN]
        return ("FAIL", "\n".join(lines) + "\n", failures)
    
    # Check required step artifacts
    step_names = [str(s.get("step", "")).strip() for s in steps if isinstance(s, dict)]
    required_steps = ["step_01_py_compile"]
    for sn in required_steps:
        if sn not in step_names:
            msg = f"debug:missing_artifacts required_step_missing {sn}"
            failures.append(canonicalize_failure(
                kind=FailureKind.VERIFIER_ERROR,
                artifact="debug/repro/steps.json",
                locator=str(steps_path),
                message=msg,
                repro="verify_gate:gate3_execution:debug_required_step_missing",
                severity=FailureSeverity.BLOCKER,
            ).to_dict())
            lines = ["FAIL", "EVIDENCE:", f"- {msg}", "REQUIRED_ACTIONS:", "- steps.json must include step_01_py_compile.", STOP_TOKEN]
            return ("FAIL", "\n".join(lines) + "\n", failures)
    
    # Validate per-step artifact files
    def _check_step_artifacts(step_name: str) -> list[str]:
        step_dir = repro_dir / step_name
        needed = ["cmd.json", "exit_code.json", "stdout.sha256", "stderr.sha256"]
        missing_local = []
        for n in needed:
            if not (step_dir / n).exists():
                missing_local.append(f"debug/repro/{step_name}/{n}")
        return missing_local
    
    missing_step_artifacts: list[str] = []
    for sn in step_names:
        missing_step_artifacts.extend(_check_step_artifacts(sn))
    
    if missing_step_artifacts:
        msg = f"debug:missing_artifacts missing={missing_step_artifacts}"
        failures.append(canonicalize_failure(
            kind=FailureKind.VERIFIER_ERROR,
            artifact="debug/repro",
            locator=str(repro_dir),
            message=msg,
            repro="verify_gate:gate3_execution:debug_step_artifacts_missing",
            severity=FailureSeverity.BLOCKER,
        ).to_dict())
        lines = ["FAIL", "EVIDENCE:", f"- {msg}", "REQUIRED_ACTIONS:", "- Provide required debug step artifacts.", STOP_TOKEN]
        return ("FAIL", "\n".join(lines) + "\n", failures)
    
    # Verify exit codes and classify failures
    def _load_exit_code(step_name: str) -> int:
        p = repro_dir / step_name / "exit_code.json"
        try:
            obj = json.loads(read_text(p))
            return int(obj.get("exit_code", 1))
        except Exception:
            return 1
    
    compile_exit = _load_exit_code("step_01_py_compile")
    if compile_exit != 0:
        msg = "debug:compile_failed"
        failures.append(canonicalize_failure(
            kind=FailureKind.COMPILE_ERROR,
            artifact="debug/repro/step_01_py_compile",
            locator=str(repro_dir / "step_01_py_compile"),
            message=msg,
            repro="verify_gate:gate3_execution:debug_compile_failed",
            severity=FailureSeverity.BLOCKER,
        ).to_dict())
    
    if "step_02_run" in step_names:
        run_exit = _load_exit_code("step_02_run")
        if run_exit != 0:
            msg = "debug:run_failed"
            failures.append(canonicalize_failure(
                kind=FailureKind.RUNTIME_EXCEPTION,
                artifact="debug/repro/step_02_run",
                locator=str(repro_dir / "step_02_run"),
                message=msg,
                repro="verify_gate:gate3_execution:debug_run_failed",
                severity=FailureSeverity.BLOCKER,
            ).to_dict())
    
    if "step_03_unittest" in step_names:
        test_exit = _load_exit_code("step_03_unittest")
        if test_exit != 0:
            msg = "debug:tests_failed"
            failures.append(canonicalize_failure(
                kind=FailureKind.TEST_FAILURE,
                artifact="debug/repro/step_03_unittest",
                locator=str(repro_dir / "step_03_unittest"),
                message=msg,
                repro="verify_gate:gate3_execution:debug_tests_failed",
                severity=FailureSeverity.BLOCKER,
            ).to_dict())
    
    # Report anchoring checks
    report_text = read_text(report_md)
    if "## Truth Anchors" not in report_text or "Clamp Summary" not in report_text:
        msg = "debug:report_not_evidence_anchored missing_truth_anchors"
        failures.append(canonicalize_failure(
            kind=FailureKind.VERIFIER_ERROR,
            artifact="debug/report.md",
            locator=str(report_md),
            message=msg,
            repro="verify_gate:gate3_execution:debug_report_missing_truth_anchors",
            severity=FailureSeverity.BLOCKER,
        ).to_dict())
    
    for line in report_text.splitlines():
        if line.startswith("Cause:"):
            if "step_" not in line or "stderr_sha256=" not in line or "debug/repro/" not in line:
                msg = "debug:report_not_evidence_anchored bad_cause_line"
                failures.append(canonicalize_failure(
                    kind=FailureKind.VERIFIER_ERROR,
                    artifact="debug/report.md",
                    locator=str(report_md),
                    message=msg,
                    repro="verify_gate:gate3_execution:debug_report_cause_line",
                    severity=FailureSeverity.BLOCKER,
                ).to_dict())
                break
    
    if failures:
        lines = ["FAIL", "EVIDENCE:"]
        lines.extend([f"- {f.get('message', '')}" for f in failures])
        lines.append("REQUIRED_ACTIONS:")
        lines.append("- Fix debug artifacts and ensure evidence-anchored report format.")
        lines.append(STOP_TOKEN)
        return ("FAIL", "\n".join(lines) + "\n", failures)
    
    lines = ["PASS", "EVIDENCE:", "- debug artifacts verified", STOP_TOKEN]
    return ("PASS", "\n".join(lines) + "\n", failures)
def execute_cli_behavioral_test(request_dir: Path, workspace_project: Path) -> tuple[bool, str, dict]:
    """
    Execute CLI and capture behavioral outputs.
    Returns (success, error_message, execution_results).
    execution_results contains: commands_run, outputs (list of {command, exit_code, stdout, stderr})
    """
    import subprocess
    import json
    
    # Load REQ.json to understand what to execute
    req_json_path = request_dir / "REQ.json"
    if not req_json_path.exists():
        return False, "REQ.json missing", {}
    
    try:
        req_json = json.loads(read_text(req_json_path))
        intents = req_json.get("intents", [])
    except Exception as e:
        return False, f"Failed to parse REQ.json: {e}", {}
    
    # Find main Python file (including src/main.py, src/run.py, etc.)
    py_files = list(workspace_project.rglob("*.py"))
    if not py_files:
        return False, "No Python files found", {}
    # Prefer src/main.py, main.py, then any .py (stable sort by path)
    def _main_priority(p: Path) -> tuple:
        rel = str(p.relative_to(workspace_project)).replace("\\", "/")
        if rel.endswith("src/main.py") or rel == "main.py":
            return (0, rel)
        if p.name == "main.py":
            return (1, rel)
        return (2, rel)
    py_files = sorted(py_files, key=_main_priority)
    
    main_py = py_files[0]  # Use first Python file
    main_py_abs = main_py.resolve()
    
    execution_results = {
        "commands_run": [],
        "outputs": []
    }
    
    def _is_safe_relpath(p: str) -> bool:
        if not p:
            return False
        if p.startswith("/"):
            return False
        if ".." in p.replace("\\", "/").split("/"):
            return False
        return True

    def _norm_json_bytes(b: bytes) -> bytes:
        try:
            obj = json.loads(b.decode("utf-8", errors="replace"))
            return (json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        except Exception:
            return b

    # Ensure CLI execution does not write bytecode (replay-safe and dist-deterministic).
    import os
    exec_env = os.environ.copy()
    exec_env["PYTHONHASHSEED"] = "0"
    exec_env["PYTHONDONTWRITEBYTECODE"] = "1"
    exec_env.setdefault("LC_ALL", "C")
    exec_env.setdefault("LANG", "C")

    # Pipeline: multi-intent REQ uses a single deterministic "run" command.
    if isinstance(intents, list) and len(intents) > 1:
        cmd = ["python3", "-B", str(main_py_abs), "run"]
        command_str = " ".join(cmd)
        execution_results["commands_run"].append(command_str)

        # Build deterministic fixtures + expected outputs for supported pipelines.
        itypes = [i.get("intent_type") for i in intents if isinstance(i, dict)]
        params_by_type = {i.get("intent_type"): (i.get("params") or {}) for i in intents if isinstance(i, dict)}

        stdin_bytes = b""
        expect_stdout: bytes | None = None
        expect_files: list[tuple[str, bytes]] = []

        # Case A: stdin -> filter_contains -> unique -> output_format=json|text
        if itypes[:1] == ["stdin_support"] and "filter_contains" in itypes and "output_format" in itypes:
            # deterministic stdin fixture (covers duplicates + non-matches)
            stdin_bytes = b"ok\nerror one\nok\nerror one\nWARN\n"
            substring = str(params_by_type.get("filter_contains", {}).get("substring", ""))
            if not substring:
                return False, "pipeline fixture: missing substring", execution_results
            # expected filtered (and optionally unique) order
            lines = [b.decode("utf-8").rstrip("\n") for b in stdin_bytes.splitlines(True)]
            filtered = [ln.rstrip("\n") for ln in lines if substring.lower() in ln.lower()]
            out_lines = filtered
            if "unique" in itypes:
                seen = set()
                uniq: list[str] = []
                for x in filtered:
                    if x in seen:
                        continue
                    seen.add(x)
                    uniq.append(x)
                out_lines = uniq
            fmt = str(params_by_type.get("output_format", {}).get("format", "text")).lower()
            if fmt == "json":
                expect_stdout = (json.dumps(out_lines, ensure_ascii=False) + "\n").encode("utf-8")
            else:
                expect_stdout = ("\n".join(out_lines) + ("\n" if out_lines else "")).encode("utf-8")



        # Case A2: stdin -> filter_contains -> write_lines (optional unique)
        elif itypes[:1] == ["stdin_support"] and "filter_contains" in itypes and "write_lines" in itypes:
            outp = str(params_by_type.get("write_lines", {}).get("file_path", ""))
            substring = str(params_by_type.get("filter_contains", {}).get("substring", ""))
            if not _is_safe_relpath(outp):
                return False, f"unsafe file path(s) in REQ: {outp!r}", execution_results
            if not substring:
                return False, "pipeline fixture: missing substring", execution_results
            stdin_bytes = b"ok\nerror one\nok\nerror one\nWARN\n"
            lines = [b.decode("utf-8").rstrip("\n") for b in stdin_bytes.splitlines(True)]
            filtered = [ln.rstrip("\n") for ln in lines if substring.lower() in ln.lower()]
            out_lines = filtered
            if "unique" in itypes:
                seen = set()
                uniq: list[str] = []
                for x in filtered:
                    if x in seen:
                        continue
                    seen.add(x)
                    uniq.append(x)
                out_lines = uniq
            expect_files.append((outp, ("\n".join(out_lines) + ("\n" if out_lines else "")).encode("utf-8")))
        # Case B: read_lines -> filter_contains -> write_lines
        elif itypes[:1] == ["read_lines"] and "filter_contains" in itypes and "write_lines" in itypes:
            inp = str(params_by_type.get("read_lines", {}).get("file_path", ""))
            outp = str(params_by_type.get("write_lines", {}).get("file_path", ""))
            substring = str(params_by_type.get("filter_contains", {}).get("substring", ""))
            if not (_is_safe_relpath(inp) and _is_safe_relpath(outp)):
                return False, f"unsafe file path(s) in REQ: {inp!r} -> {outp!r}", execution_results
            if not substring:
                return False, "pipeline fixture: missing substring", execution_results
            # fixture input file content
            in_bytes = b"ok\nerror one\nerror one\nWARN\n"
            (workspace_project / inp).write_bytes(in_bytes)
            expected_lines = [ln for ln in in_bytes.decode("utf-8").splitlines() if substring.lower() in ln.lower()]
            expect_files.append((outp, ("\n".join(expected_lines) + ("\n" if expected_lines else "")).encode("utf-8")))



        # Case B2: read_lines -> filter_contains -> output_format=json|text
        elif itypes[:1] == ["read_lines"] and "filter_contains" in itypes and "output_format" in itypes and ("write_lines" not in itypes):
            inp = str(params_by_type.get("read_lines", {}).get("file_path", ""))
            substring = str(params_by_type.get("filter_contains", {}).get("substring", ""))
            fmt = str(params_by_type.get("output_format", {}).get("format", "json")).lower()
            if not _is_safe_relpath(inp):
                return False, f"unsafe file path(s) in REQ: {inp!r}", execution_results
            if not substring:
                return False, "pipeline fixture: missing substring", execution_results
            if fmt not in ("json", "text"):
                return False, f"unsupported output_format for read_lines pipeline verification: {fmt}", execution_results
            in_bytes = b"ok\nerror one\nerror one\nWARN\n"
            (workspace_project / inp).write_bytes(in_bytes)
            lines = [ln for ln in in_bytes.decode("utf-8").splitlines() if substring.lower() in ln.lower()]
            if fmt == "json":
                expect_stdout = (json.dumps(lines, ensure_ascii=False) + "\n").encode("utf-8")
            else:
                expect_stdout = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")

        # Case C: csv_read -> filter_contains -> csv_write
        elif itypes[:1] == ["csv_read"] and "filter_contains" in itypes and "csv_write" in itypes:
            inp = str(params_by_type.get("csv_read", {}).get("file_path", ""))
            outp = str(params_by_type.get("csv_write", {}).get("file_path", ""))
            substring = str(params_by_type.get("filter_contains", {}).get("substring", ""))
            if not (_is_safe_relpath(inp) and _is_safe_relpath(outp)):
                return False, f"unsafe file path(s) in REQ: {inp!r} -> {outp!r}", execution_results
            if not substring:
                return False, "pipeline fixture: missing substring", execution_results
            # fixture CSV: header + rows
            csv_in = "level,msg\ninfo,ok\nerror,bad\nwarn,ok\n"
            (workspace_project / inp).write_text(csv_in, encoding="utf-8")
            # expectation: rows where any field contains substring (case-insensitive)
            rows = [["info", "ok"], ["error", "bad"], ["warn", "ok"]]
            keep = [r for r in rows if any(substring.lower() in str(c).lower() for c in r)]
            # csv_write emits rows with csv.writer; simplest expectation: comma-joined + newline
            out_lines = [",".join(r) for r in keep]
            expect_files.append((outp, ("\n".join(out_lines) + ("\n" if out_lines else "")).encode("utf-8")))

        # Case C3: stdin/read_lines -> grep_regex -> output_format/write_lines
        elif "grep_regex" in itypes:
            patt = str(params_by_type.get("grep_regex", {}).get("pattern", ""))
            ignore_case = bool(params_by_type.get("grep_regex", {}).get("ignore_case", False))
            if not patt:
                return False, "pipeline fixture: missing regex pattern", execution_results
            try:
                _re = re.compile(patt, re.IGNORECASE if ignore_case else 0)
            except re.error as e:
                return False, f"invalid regex pattern in REQ: {e}", execution_results
            fixture_lines = ["ok", "Error one", "error two", "WARN", "note"]
            if itypes[0] == "stdin_support":
                stdin_bytes = ("\n".join(fixture_lines) + "\n").encode("utf-8")
            elif itypes[0] == "read_lines":
                inp = str(params_by_type.get("read_lines", {}).get("file_path", ""))
                if not _is_safe_relpath(inp):
                    return False, f"unsafe file path(s) in REQ: {inp!r}", execution_results
                (workspace_project / inp).write_text("\n".join(fixture_lines) + "\n", encoding="utf-8")
            else:
                return False, "Unsupported grep_regex source", execution_results

            matches = [ln for ln in fixture_lines if _re.search(ln)]
            if "write_lines" in itypes:
                outp = str(params_by_type.get("write_lines", {}).get("file_path", ""))
                if not _is_safe_relpath(outp):
                    return False, f"unsafe file path(s) in REQ: {outp!r}", execution_results
                expect_files.append((outp, ("\n".join(matches) + ("\n" if matches else "")).encode("utf-8")))
            else:
                fmt = "text"
                if "output_format" in itypes:
                    fmt = str(params_by_type.get("output_format", {}).get("format", "text")).lower()
                if fmt == "json":
                    expect_stdout = (json.dumps(matches, ensure_ascii=False) + "\n").encode("utf-8")
                else:
                    expect_stdout = ("\n".join(matches) + ("\n" if matches else "")).encode("utf-8")



        # Case C2: csv_read -> output_format=json
        elif itypes[:1] == ["csv_read"] and "output_format" in itypes and ("filter_contains" not in itypes) and ("csv_write" not in itypes):
            inp = str(params_by_type.get("csv_read", {}).get("file_path", ""))
            if not _is_safe_relpath(inp):
                return False, f"unsafe file path(s) in REQ: {inp!r}", execution_results
            fmt = str(params_by_type.get("output_format", {}).get("format", "json")).lower()
            if fmt != "json":
                return False, f"csv_read output_format must be json for verification (got {fmt})", execution_results
            csv_in = "level,msg\ninfo,ok\nerror,bad\nwarn,ok\n"
            (workspace_project / inp).write_text(csv_in, encoding="utf-8")
            expect_stdout = (json.dumps([["info", "ok"], ["error", "bad"], ["warn", "ok"]], ensure_ascii=False) + "\n").encode("utf-8")
        # Case D: stdin/read_lines -> parse_numbers -> output_format=json
        elif itypes[:2] in (["stdin_support", "parse_numbers"], ["read_lines", "parse_numbers"]) and "output_format" in itypes:
            fmt = str(params_by_type.get("output_format", {}).get("format", "json")).lower()
            if fmt != "json":
                return False, f"parse_numbers pipeline must output json for verification (got {fmt})", execution_results
            if itypes[0] == "stdin_support":
                stdin_bytes = b"1\\n2\\n3\\nnoise\\n4\\n"
            else:
                inp = str(params_by_type.get("read_lines", {}).get("file_path", ""))
                if not _is_safe_relpath(inp):
                    return False, f"unsafe file path(s) in REQ: {inp!r}", execution_results
                (workspace_project / inp).write_text("1\\n2\\n3\\nnoise\\n4\\n", encoding="utf-8")
            expect_stdout = (json.dumps([1, 2, 3, 4], ensure_ascii=False) + "\n").encode("utf-8")
        # Case E: inline numbers -> sort_numbers/stats_basic -> output_format=json
        elif itypes[:1] in (["sort_numbers"], ["stats_basic"]) and "output_format" in itypes:
            fmt = str(params_by_type.get("output_format", {}).get("format", "json")).lower()
            if fmt != "json":
                return False, f"numeric pipeline must output json for verification (got {fmt})", execution_results
            if itypes[0] == "sort_numbers":
                nums = params_by_type.get("sort_numbers", {}).get("numbers", [])
                rev = bool(params_by_type.get("sort_numbers", {}).get("reverse", False))
                expect_stdout = (json.dumps(sorted(list(nums), reverse=rev), ensure_ascii=False) + "\n").encode("utf-8")
            else:
                nums = list(params_by_type.get("stats_basic", {}).get("numbers", []))
                st = params_by_type.get("stats_basic", {}).get("stats", ["min", "max", "avg", "count"])
                out = {}
                if "count" in st:
                    out["count"] = len(nums)
                if "min" in st and nums:
                    out["min"] = min(nums)
                if "max" in st and nums:
                    out["max"] = max(nums)
                if "avg" in st and nums:
                    out["avg"] = (sum(nums) / len(nums))
                expect_stdout = (json.dumps(out, ensure_ascii=False) + "\n").encode("utf-8")

        # Additional pipelines: count_lines
        elif "count_lines" in itypes:
            fmt = "json"
            if "output_format" in itypes:
                fmt = str(params_by_type.get("output_format", {}).get("format", "json")).lower()
            if "stdin_support" in itypes:
                stdin_bytes = b"a\nb\nc\n"
            elif "read_lines" in itypes:
                inp = str(params_by_type.get("read_lines", {}).get("file_path", ""))
                if not _is_safe_relpath(inp):
                    return False, f"unsafe file path(s) in REQ: {inp!r}", execution_results
                (workspace_project / inp).write_text("a\nb\nc\n", encoding="utf-8")
            else:
                return False, "Unsupported count_lines pipeline", execution_results
            if fmt == "json":
                expect_stdout = (json.dumps({"line_count": 3}, ensure_ascii=False) + "\n").encode("utf-8")
            elif fmt == "text":
                expect_stdout = b"3\n"
            else:
                return False, f"Unsupported output_format for count_lines: {fmt}", execution_results

        # Additional pipelines: json_pretty_print
        elif "json_pretty_print" in itypes:
            fmt = "text"
            if "output_format" in itypes:
                fmt = str(params_by_type.get("output_format", {}).get("format", "text")).lower()
            pretty_text = json.dumps({"a": 1, "b": {"c": 2}}, ensure_ascii=False, indent=2)
            if "stdin_support" in itypes:
                stdin_bytes = b'{"a":1,"b":{"c":2}}'
            elif "read_lines" in itypes:
                inp = str(params_by_type.get("read_lines", {}).get("file_path", ""))
                if not _is_safe_relpath(inp):
                    return False, f"unsafe file path(s) in REQ: {inp!r}", execution_results
                (workspace_project / inp).write_text('{"a":1,"b":{"c":2}}', encoding="utf-8")
            else:
                return False, "Unsupported json_pretty_print pipeline source", execution_results
            if "write_lines" in itypes:
                outp = str(params_by_type.get("write_lines", {}).get("file_path", ""))
                if not _is_safe_relpath(outp):
                    return False, f"unsafe file path(s) in REQ: {outp!r}", execution_results
                expect_files.append((outp, (pretty_text + "\n").encode("utf-8")))
            else:
                if fmt in ("text", "json"):
                    expect_stdout = (pretty_text + "\n").encode("utf-8")
                else:
                    return False, f"Unsupported output_format for json_pretty_print: {fmt}", execution_results

        # Additional pipelines: csv_select_columns
        elif "csv_select_columns" in itypes:
            # Supported shapes: csv_read -> csv_select_columns -> (csv_write|output_format)
            if itypes[:1] != ["csv_read"]:
                return False, "csv_select_columns requires csv_read source", execution_results
            has_header = bool(params_by_type.get("csv_read", {}).get("has_header", True))
            cols = params_by_type.get("csv_select_columns", {}).get("columns", [])
            # fixture CSV
            csv_in = "name,email,age\nalice,a@example.com,30\nbob,b@example.com,25\n"
            inp = str(params_by_type.get("csv_read", {}).get("file_path", ""))
            if not _is_safe_relpath(inp):
                return False, f"unsafe file path in REQ: {inp!r}", execution_results
            (workspace_project / inp).write_text(csv_in, encoding="utf-8")
            header = ["name", "email", "age"]
            data_rows = [
                ["alice", "a@example.com", "30"],
                ["bob", "b@example.com", "25"],
            ]
            if has_header:
                # columns must be names
                if any(isinstance(c, int) for c in cols):
                    return False, "invalid columns: indices not allowed when has_header=true", execution_results
                indices = []
                for c in cols:
                    if c not in header:
                        # simulate runtime invalid
                        return False, "invalid column name", execution_results
                    indices.append(header.index(c))
                out_rows = [[header[i] for i in indices]] + [[r[i] for i in indices] for r in data_rows]
            else:
                # columns must be indices
                if any(not isinstance(c, int) for c in cols):
                    return False, "invalid columns: names not allowed when has_header=false", execution_results
                if not cols:
                    return False, "missing columns", execution_results
                if max(cols) >= len(data_rows[0]):
                    return False, "invalid column index", execution_results
                out_rows = [[r[i] for i in cols] for r in data_rows]

            if "csv_write" in itypes:
                outp = str(params_by_type.get("csv_write", {}).get("file_path", ""))
                if not _is_safe_relpath(outp):
                    return False, f"unsafe file path(s) in REQ: {outp!r}", execution_results
                out_lines = ["{}".format(",".join(r)) for r in out_rows]
                expect_files.append((outp, ("\n".join(out_lines) + "\n").encode("utf-8")))
            elif "output_format" in itypes:
                fmt = str(params_by_type.get("output_format", {}).get("format", "csv")).lower()
                if fmt != "csv":
                    return False, f"csv_select_columns output_format must be csv (got {fmt})", execution_results
                out_lines = ["{}".format(",".join(r)) for r in out_rows]
                expect_stdout = ("\n".join(out_lines) + "\n").encode("utf-8")
            else:
                return False, "Unsupported sink for csv_select_columns", execution_results

        else:
            return False, f"Unsupported pipeline for behavioral verification: {itypes}", execution_results

        # Execute pipeline
        try:
            result = subprocess.run(
                cmd,
                cwd=workspace_project,
                env=exec_env,
                input=stdin_bytes,
                capture_output=True,
                timeout=10,
            )
            execution_results["outputs"].append(
                {
                    "command": command_str,
                    "exit_code": result.returncode,
                    "stdout": result.stdout.decode("utf-8", errors="replace"),
                    "stderr": result.stderr.decode("utf-8", errors="replace"),
                }
            )
            if result.returncode != 0:
                return False, f"pipeline run nonzero exit code: {result.returncode}", execution_results

            if expect_stdout is not None:
                got = result.stdout
                # normalize JSON comparisons when expected is JSON
                if expect_stdout.strip().startswith(b"{") or expect_stdout.strip().startswith(b"["):
                    got_n = _norm_json_bytes(got)
                    exp_n = _norm_json_bytes(expect_stdout)
                    if got_n != exp_n:
                        return False, "pipeline stdout mismatch", execution_results
                else:
                    if got != expect_stdout:
                        return False, "pipeline stdout mismatch", execution_results

            for relp, expb in expect_files:
                fp = workspace_project / relp
                if not fp.exists():
                    return False, f"expected output file missing: {relp}", execution_results
                gotb = fp.read_bytes()
                if gotb != expb:
                    return False, f"output file bytes mismatch: {relp}", execution_results

        except subprocess.TimeoutExpired:
            return False, "CLI execution timed out", execution_results
        except Exception as e:
            return False, f"CLI execution failed: {e}", execution_results

        return True, None, execution_results

    # Non-pipeline: execute per-intent command (legacy).
    for intent in intents:
        intent_type = intent.get("intent_type")

        cmd = ["python3", "-B", str(main_py_abs)]
        if intent_type == "print_sequence":
            cmd.append("print-sequence")
        elif intent_type == "sum_numbers":
            cmd.append("sum-numbers")
        else:
            cmd.append(intent_type.replace("_", "-"))

        command_str = " ".join(cmd)
        execution_results["commands_run"].append(command_str)
        try:
            result = subprocess.run(
                cmd,
                cwd=workspace_project,
                env=exec_env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            execution_results["outputs"].append(
                {
                    "command": command_str,
                    "exit_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
        except subprocess.TimeoutExpired:
            execution_results["outputs"].append(
                {
                    "command": command_str,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": "Command timed out after 10 seconds",
                }
            )
            return False, "CLI execution timed out", execution_results
        except Exception as e:
            execution_results["outputs"].append(
                {
                    "command": command_str,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": str(e),
                }
            )
            return False, f"CLI execution failed: {e}", execution_results

    return True, None, execution_results



def verify_gate(
    request_id: str, 
    gate: str, 
    request_dir: Path
) -> Tuple[str, str, List[Dict[str, Any]]]:
    """
    Verify gate and return (status, text, failures).
    
    Returns:
        (status, verify_text, failures_list)
        failures_list: List of canonical failure dicts
    """
    from workers.failure_canonicalizer import (
        canonicalize_from_missing_artifact,
        canonicalize_failure,
        FailureKind,
        FailureSeverity,
    )
    
    failures: List[Dict[str, Any]] = []

    # Step 10: Snapshot resolution pinning (deterministic glue).
    # Verifier enforces:
    # - snapshot_resolution.json exists when payload declares snapshot fields
    # - bytes match payload-derived expected
    try:
        payload_for_snap = {}
        ppath = request_dir / "payload.json"
        if ppath.exists():
            try:
                payload_for_snap = json.loads(read_text(ppath))
                if not isinstance(payload_for_snap, dict):
                    payload_for_snap = {}
            except Exception:
                payload_for_snap = {}

        snap_fields_present = any(
            k in payload_for_snap for k in ("knowledge_snapshot_id", "external_snapshot_id", "db_snapshot_id")
        )

        from nlc.snapshot_resolver import expected_snapshot_resolution_bytes, SnapshotResolutionError
        sr_path = request_dir / "snapshot_resolution.json"

        if snap_fields_present:
            if not sr_path.exists():
                failure = canonicalize_failure(
                    kind=FailureKind.SNAPSHOT_VIOLATION,
                    artifact="snapshot_resolution.json",
                    locator=str(sr_path),
                    message="snapshot_resolution.json missing",
                    repro="snapshot:resolution_missing",
                    severity=FailureSeverity.BLOCKER,
                )
                failures.append(failure.to_dict())
                return ("FAIL", f"FAIL\nEVIDENCE:\n- snapshot resolution missing\n{STOP_TOKEN}\n", failures)

            try:
                expected = expected_snapshot_resolution_bytes(request_dir)
            except SnapshotResolutionError as e:
                failure = canonicalize_failure(
                    kind=FailureKind.SNAPSHOT_VIOLATION,
                    artifact="payload.json",
                    locator=str(ppath),
                    message=e.message,
                    repro=e.repro,
                    severity=FailureSeverity.BLOCKER,
                )
                failures.append(failure.to_dict())
                return ("FAIL", f"FAIL\nEVIDENCE:\n- snapshot violation\n{STOP_TOKEN}\n", failures)

            actual = sr_path.read_bytes()
            if actual != expected:
                failure = canonicalize_failure(
                    kind=FailureKind.SNAPSHOT_VIOLATION,
                    artifact="snapshot_resolution.json",
                    locator=str(sr_path),
                    message="snapshot resolution bytes do not match payload-derived expected",
                    repro="snapshot:resolution_mismatch",
                    severity=FailureSeverity.BLOCKER,
                    expected=hashlib.sha256(expected).hexdigest(),
                    actual=hashlib.sha256(actual).hexdigest(),
                )
                failures.append(failure.to_dict())
                return ("FAIL", f"FAIL\nEVIDENCE:\n- snapshot resolution mismatch\n{STOP_TOKEN}\n", failures)
    except Exception:
        # Verifier should not crash due to resolver issues; treat as no-op here.
        pass

    # Step 9: External input pinning (deterministic, no network dependency in replay).
    # Triggered only when payload explicitly declares external snapshot usage.
    payload = {}
    payload_path = request_dir / "payload.json"
    if payload_path.exists():
        try:
            payload = json.loads(read_text(payload_path))
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}

    external_snapshot_id = str(payload.get("external_snapshot_id", "")).strip() if isinstance(payload, dict) else ""
    external_required = payload.get("external_sources_required", []) if isinstance(payload, dict) else []
    if external_snapshot_id or (isinstance(external_required, list) and external_required):
        from workers.failure_canonicalizer import canonicalize_failure, FailureKind, FailureSeverity
        from nlc.external_snapshot import EXTERNAL_ROOT, compute_sha256_tree_hash
        snap_dir = EXTERNAL_ROOT / (external_snapshot_id or "")

        def ext_fail(repro: str, msg: str, locator: str = ""):
            f = canonicalize_failure(
                kind=FailureKind.EXTERNAL_INPUT_VIOLATION,
                artifact="external_snapshot",
                locator=locator or str(snap_dir),
                message=msg,
                repro=repro,
                severity=FailureSeverity.BLOCKER,
            )
            failures.append(f.to_dict())

        if not external_snapshot_id:
            ext_fail("external:snapshot_missing", "external snapshot_id missing in payload.json", locator=str(payload_path))
            return ("FAIL", f"FAIL\nEVIDENCE:\n- external snapshot missing\n{STOP_TOKEN}\n", failures)

        if not snap_dir.exists():
            ext_fail("external:snapshot_missing", f"external snapshot dir missing: {snap_dir}")
            return ("FAIL", f"FAIL\nEVIDENCE:\n- external snapshot dir missing\n{STOP_TOKEN}\n", failures)

        meta_path = snap_dir / "snapshot.meta.json"
        if not meta_path.exists():
            ext_fail("external:snapshot_hash_mismatch", f"snapshot.meta.json missing: {meta_path}")
            return ("FAIL", f"FAIL\nEVIDENCE:\n- external snapshot meta missing\n{STOP_TOKEN}\n", failures)

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            meta = {}
        expected_tree = ""
        if isinstance(meta, dict):
            expected_tree = str(meta.get("sha256_tree_hash", "")).strip()

        # Required sources
        if isinstance(external_required, list):
            manifest_path = snap_dir / "sources.manifest.json"
            manifest = {}
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8", errors="replace")) if manifest_path.exists() else {}
            except Exception:
                manifest = {}
            entries = manifest.get("entries", []) if isinstance(manifest, dict) else []
            by_id = {e.get("source_id"): e for e in entries if isinstance(e, dict) and isinstance(e.get("source_id"), str)}
            for sid in sorted([str(x) for x in external_required if isinstance(x, str) and x.strip()]):
                if sid not in by_id:
                    ext_fail(f"external:source_missing:{sid}", f"external source missing in manifest: {sid}", locator=str(manifest_path))
                    continue
                fn = str(by_id[sid].get("filename", "")).strip()
                if not fn:
                    ext_fail(f"external:source_missing:{sid}", f"external manifest entry missing filename for: {sid}", locator=str(manifest_path))
                    continue
                fp = snap_dir / fn
                if not fp.exists():
                    ext_fail(f"external:source_missing:{sid}", f"external source file missing: {fn} for {sid}", locator=str(fp))

            # If any source failures, stop early (deterministic).
            if any(f.get("kind") == "external_input_violation" for f in failures):
                return ("FAIL", f"FAIL\nEVIDENCE:\n- external sources missing\n{STOP_TOKEN}\n", failures)

        # Snapshot integrity: verify tree hash after source presence checks.
        got_tree = compute_sha256_tree_hash(snap_dir)
        if not expected_tree or expected_tree != got_tree:
            ext_fail(
                "external:snapshot_hash_mismatch",
                f"sha256_tree_hash mismatch: expected={expected_tree} got={got_tree}",
                locator=str(meta_path),
            )
            return ("FAIL", f"FAIL\nEVIDENCE:\n- external snapshot hash mismatch\n{STOP_TOKEN}\n", failures)

        # Replay-only network access detection: if NLC_NET_LOG exists and has content.
        import os
        from dcs_core.repro_env import is_repro_mode
        if is_repro_mode():
            net_log = str(os.environ.get("NLC_NET_LOG", "")).strip()
            if net_log:
                lp = Path(net_log)
                if lp.exists():
                    txt = lp.read_text(encoding="utf-8", errors="replace").strip()
                    if txt:
                        ext_fail("external:network_access_detected", "network access detected during replay (see NLC_NET_LOG)", locator=str(lp))
                        return ("FAIL", f"FAIL\nEVIDENCE:\n- network access detected during replay\n{STOP_TOKEN}\n", failures)

    # Step 11: Index DB presence + pinned hash.
    # Runs when snapshot_resolution.json exists (Step 10 implies it should).
    try:
        sr_path = request_dir / "snapshot_resolution.json"
        if sr_path.exists():
            idx_dir = request_dir / "index"
            dbp = idx_dir / "index.db"
            metap = idx_dir / "index.meta.json"
            shap = idx_dir / "index.sha256"

            def idx_fail(repro: str, msg: str, locator: str):
                f = canonicalize_failure(
                    kind=FailureKind.INDEX_VIOLATION,
                    artifact="index",
                    locator=locator,
                    message=msg,
                    repro=repro,
                    severity=FailureSeverity.BLOCKER,
                )
                failures.append(f.to_dict())

            if not dbp.exists():
                idx_fail("index:missing", "index/index.db missing", str(dbp))
                return ("FAIL", f"FAIL\nEVIDENCE:\n- index missing\n{STOP_TOKEN}\n", failures)
            if not metap.exists():
                idx_fail("index:meta_missing", "index/index.meta.json missing", str(metap))
                return ("FAIL", f"FAIL\nEVIDENCE:\n- index meta missing\n{STOP_TOKEN}\n", failures)
            if not shap.exists():
                idx_fail("index:sha_missing", "index/index.sha256 missing", str(shap))
                return ("FAIL", f"FAIL\nEVIDENCE:\n- index sha missing\n{STOP_TOKEN}\n", failures)

            expected = shap.read_text(encoding="utf-8", errors="replace").strip()
            got = sha256_bytes(dbp.read_bytes() + metap.read_bytes())
            if expected != got:
                f = canonicalize_failure(
                    kind=FailureKind.INDEX_VIOLATION,
                    artifact="index",
                    locator=str(shap),
                    message="index sha mismatch",
                    repro="index:sha_mismatch",
                    severity=FailureSeverity.BLOCKER,
                    expected=expected,
                    actual=got,
                )
                failures.append(f.to_dict())
                return ("FAIL", f"FAIL\nEVIDENCE:\n- index sha mismatch\n{STOP_TOKEN}\n", failures)
    except Exception:
        pass

    # Step 6: Contract enforcement (deterministic, no side effects).
    # Verifier remains the oracle and the single writer of verifier outputs.
    try:
        from workers.contract_checker import check_request_contract
        contract_failures = check_request_contract(BASE, request_dir, gate)
        failures.extend(contract_failures)
    except Exception:
        # Contract checker failures should not crash verifier; surface as verifier_error later if needed.
        pass

    # Step 12: Planner must be index-backed when answer_mode=index_backed.
    try:
        payload_obj = {}
        payload_path2 = request_dir / "payload.json"
        if payload_path2.exists():
            try:
                payload_obj = json.loads(read_text(payload_path2))
                if not isinstance(payload_obj, dict):
                    payload_obj = {}
            except Exception:
                payload_obj = {}

        if payload_obj.get("answer_mode") == "index_backed":
            from workers.failure_canonicalizer import canonicalize_failure, FailureKind, FailureSeverity

            # Index must exist (presence only; sha is enforced by Step 11 index_violation check).
            if not (request_dir / "index" / "index.db").exists():
                failures.append(
                    canonicalize_failure(
                        kind=FailureKind.PLANNER_VIOLATION,
                        artifact="index/index.db",
                        locator=str(request_dir / "index" / "index.db"),
                        message="index missing for planner answering",
                        repro="planner:index_missing",
                        severity=FailureSeverity.BLOCKER,
                    ).to_dict()
                )
                return ("FAIL", f"FAIL\nEVIDENCE:\n- planner index missing\n{STOP_TOKEN}\n", failures)

            plan_path = request_dir / "planner" / "plan.json"
            if not plan_path.exists():
                failures.append(
                    canonicalize_failure(
                        kind=FailureKind.PLANNER_VIOLATION,
                        artifact="planner/plan.json",
                        locator=str(plan_path),
                        message="planner plan.json missing",
                        repro="planner:plan_missing",
                        severity=FailureSeverity.BLOCKER,
                    ).to_dict()
                )
                return ("FAIL", f"FAIL\nEVIDENCE:\n- planner plan missing\n{STOP_TOKEN}\n", failures)

            raw = plan_path.read_text(encoding="utf-8", errors="replace")
            if "snapshots/external/" in raw:
                failures.append(
                    canonicalize_failure(
                        kind=FailureKind.PLANNER_VIOLATION,
                        artifact="planner/plan.json",
                        locator=str(plan_path),
                        message="raw external snapshot path reference detected in plan",
                        repro="planner:raw_access_detected",
                        severity=FailureSeverity.BLOCKER,
                    ).to_dict()
                )
                return ("FAIL", f"FAIL\nEVIDENCE:\n- planner raw access detected\n{STOP_TOKEN}\n", failures)

            try:
                plan_obj = json.loads(raw)
            except Exception:
                plan_obj = {}
            if not isinstance(plan_obj, dict) or plan_obj.get("index_used") is not True:
                failures.append(
                    canonicalize_failure(
                        kind=FailureKind.PLANNER_VIOLATION,
                        artifact="planner/plan.json",
                        locator=str(plan_path),
                        message="planner plan is not index-backed",
                        repro="planner:not_index_backed",
                        severity=FailureSeverity.BLOCKER,
                    ).to_dict()
                )
                return ("FAIL", f"FAIL\nEVIDENCE:\n- planner not index backed\n{STOP_TOKEN}\n", failures)

            queries = plan_obj.get("queries")
            answer_queries = payload_obj.get("answer_queries", [])
            needs_queries = isinstance(answer_queries, list) and len(answer_queries) > 0
            if needs_queries and (not isinstance(queries, list) or len(queries) == 0):
                failures.append(
                    canonicalize_failure(
                        kind=FailureKind.PLANNER_VIOLATION,
                        artifact="planner/plan.json",
                        locator=str(plan_path),
                        message="planner queries missing",
                        repro="planner:queries_missing",
                        severity=FailureSeverity.BLOCKER,
                    ).to_dict()
                )
                return ("FAIL", f"FAIL\nEVIDENCE:\n- planner queries missing\n{STOP_TOKEN}\n", failures)
    except Exception:
        pass

    # Step 13: Answer artifact + evidence lock (index -> plan -> answer).
    try:
        payload_obj = {}
        payload_path3 = request_dir / "payload.json"
        if payload_path3.exists():
            try:
                payload_obj = json.loads(read_text(payload_path3))
                if not isinstance(payload_obj, dict):
                    payload_obj = {}
            except Exception:
                payload_obj = {}

        if payload_obj.get("answer_mode") == "index_backed":
            from workers.failure_canonicalizer import canonicalize_failure, FailureKind, FailureSeverity

            plan_path = request_dir / "planner" / "plan.json"
            if not plan_path.exists():
                failures.append(
                    canonicalize_failure(
                        kind=FailureKind.ANSWER_VIOLATION,
                        artifact="planner/plan.json",
                        locator=str(plan_path),
                        message="planner plan.json missing for answer",
                        repro="answer:planner_missing",
                        severity=FailureSeverity.BLOCKER,
                    ).to_dict()
                )
                return ("FAIL", f"FAIL\nEVIDENCE:\n- answer planner missing\n{STOP_TOKEN}\n", failures)

            if not (request_dir / "index" / "index.db").exists():
                failures.append(
                    canonicalize_failure(
                        kind=FailureKind.ANSWER_VIOLATION,
                        artifact="index/index.db",
                        locator=str(request_dir / "index" / "index.db"),
                        message="index missing for answer",
                        repro="answer:index_missing",
                        severity=FailureSeverity.BLOCKER,
                    ).to_dict()
                )
                return ("FAIL", f"FAIL\nEVIDENCE:\n- answer index missing\n{STOP_TOKEN}\n", failures)

            answer_path = request_dir / "answer" / "answer.json"
            if not answer_path.exists():
                failures.append(
                    canonicalize_failure(
                        kind=FailureKind.ANSWER_VIOLATION,
                        artifact="answer/answer.json",
                        locator=str(answer_path),
                        message="answer.json missing",
                        repro="answer:missing",
                        severity=FailureSeverity.BLOCKER,
                    ).to_dict()
                )
                return ("FAIL", f"FAIL\nEVIDENCE:\n- answer missing\n{STOP_TOKEN}\n", failures)

            plan_obj = json.loads(read_text(plan_path))
            if not isinstance(plan_obj, dict):
                plan_obj = {}
            plan_evidence = plan_obj.get("evidence", [])
            if not isinstance(plan_evidence, list):
                plan_evidence = []

            # Build expected evidence list from plan evidence (copy exact excerpts; sort; rank 1..n).
            normalized = []
            for e in plan_evidence:
                if not isinstance(e, dict):
                    continue
                normalized.append(
                    {
                        "doc_id": str(e.get("doc_id", "")).strip(),
                        "source_id": str(e.get("source_id", "")).strip(),
                        "excerpt": str(e.get("excerpt", "") or ""),
                        "excerpt_sha256": str(e.get("excerpt_sha256", "")).strip().lower(),
                    }
                )
            normalized.sort(key=lambda x: (x.get("doc_id", ""), x.get("excerpt_sha256", "")))
            expected = []
            for i, e in enumerate(normalized, start=1):
                expected.append(
                    {
                        "doc_id": e["doc_id"],
                        "source_id": e["source_id"],
                        "excerpt": e["excerpt"],
                        "excerpt_sha256": e["excerpt_sha256"],
                        "rank": i,
                    }
                )
            expected.sort(key=lambda x: (int(x.get("rank", 0)), x.get("doc_id", ""), x.get("excerpt_sha256", "")))

            ans_obj = json.loads(read_text(answer_path))
            if not isinstance(ans_obj, dict):
                ans_obj = {}
            if ans_obj.get("answer_mode") != "index_backed":
                failures.append(
                    canonicalize_failure(
                        kind=FailureKind.ANSWER_VIOLATION,
                        artifact="answer/answer.json",
                        locator=str(answer_path),
                        message="answer_mode must be index_backed",
                        repro="answer:evidence_mismatch",
                        severity=FailureSeverity.BLOCKER,
                    ).to_dict()
                )
                return ("FAIL", f"FAIL\nEVIDENCE:\n- answer mode mismatch\n{STOP_TOKEN}\n", failures)

            evidence = ans_obj.get("evidence", [])
            if not isinstance(evidence, list):
                evidence = []

            # Validate excerpt sha256 matches bytes (deterministic).
            for e in evidence:
                if not isinstance(e, dict):
                    continue
                excerpt = str(e.get("excerpt", "") or "")
                want = str(e.get("excerpt_sha256", "")).strip().lower()
                got = sha256_bytes(excerpt.encode("utf-8"))
                if want != got:
                    failures.append(
                        canonicalize_failure(
                            kind=FailureKind.ANSWER_VIOLATION,
                            artifact="answer/answer.json",
                            locator=str(answer_path),
                            message="excerpt_sha256 mismatch",
                            repro="answer:sha_mismatch",
                            severity=FailureSeverity.BLOCKER,
                        ).to_dict()
                    )
                    return ("FAIL", f"FAIL\nEVIDENCE:\n- answer excerpt sha mismatch\n{STOP_TOKEN}\n", failures)

            # Evidence must match planner evidence exactly (after deterministic normalization).
            if evidence != expected:
                failures.append(
                    canonicalize_failure(
                        kind=FailureKind.ANSWER_VIOLATION,
                        artifact="answer/answer.json",
                        locator=str(answer_path),
                        message="answer evidence does not match planner evidence",
                        repro="answer:evidence_mismatch",
                        severity=FailureSeverity.BLOCKER,
                    ).to_dict()
                )
                return ("FAIL", f"FAIL\nEVIDENCE:\n- answer evidence mismatch\n{STOP_TOKEN}\n", failures)

            # Verify evidence_bundle_sha256
            evidence_canon = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
            ev_hash = sha256_bytes(evidence_canon.encode("utf-8"))
            if str(ans_obj.get("evidence_bundle_sha256", "")).strip().lower() != ev_hash:
                failures.append(
                    canonicalize_failure(
                        kind=FailureKind.ANSWER_VIOLATION,
                        artifact="answer/answer.json",
                        locator=str(answer_path),
                        message="evidence_bundle_sha256 mismatch",
                        repro="answer:sha_mismatch",
                        severity=FailureSeverity.BLOCKER,
                    ).to_dict()
                )
                return ("FAIL", f"FAIL\nEVIDENCE:\n- answer evidence bundle sha mismatch\n{STOP_TOKEN}\n", failures)

            # Verify answer_sha256
            answer_text = str(ans_obj.get("answer", "") or "")
            ans_hash = sha256_bytes(answer_text.encode("utf-8"))
            if str(ans_obj.get("answer_sha256", "")).strip().lower() != ans_hash:
                failures.append(
                    canonicalize_failure(
                        kind=FailureKind.ANSWER_VIOLATION,
                        artifact="answer/answer.json",
                        locator=str(answer_path),
                        message="answer_sha256 mismatch",
                        repro="answer:sha_mismatch",
                        severity=FailureSeverity.BLOCKER,
                    ).to_dict()
                )
                return ("FAIL", f"FAIL\nEVIDENCE:\n- answer sha mismatch\n{STOP_TOKEN}\n", failures)
    except Exception:
        pass
    
    if gate not in ALLOWED_GATES:
        from workers.failure_canonicalizer import canonicalize_failure, FailureKind, FailureSeverity
        failure = canonicalize_failure(
            kind=FailureKind.VERIFIER_ERROR,
            artifact="gate",
            locator=gate,
            message=f"Unknown gate name: {gate}",
            repro=f"verify_gate:{gate}",
            severity=FailureSeverity.BLOCKER,
        )
        failures.append(failure.to_dict())
        text = f"BLOCKED\nUnknown gate name: {gate}\n{STOP_TOKEN}\n"
        return ("BLOCKED", text, failures)

    behavioral_results = None
    behavioral_error = None
    deliverables_missing: List[str] = []
    deliverables_check_performed = False
    required, _optional = gate_requirements(request_dir, gate)

    missing = summarize_missing(request_dir, required)
    if missing:
        lines = ["FAIL", "EVIDENCE:"]
        for m in missing:
            lines.append(f"- {m} missing or empty")
            # Canonicalize missing artifact failure
            failure = canonicalize_from_missing_artifact(
                artifact_name=m,
                locator=str(request_dir / m),
                repro=f"verify_gate:{gate}",
            )
            failures.append(failure.to_dict())
        lines.append("REQUIRED_ACTIONS:")
        lines.append("- Create the missing artifacts (non-empty) before advancing the gate.")
        lines.append(STOP_TOKEN)
        return ("FAIL", "\n".join(lines) + "\n", failures)

    # (behavioral output is appended to PASS/FAIL below once lines exists)

    # Gate-specific semantic checks
    if gate in ("gate1_planning", "gate2_delegation", "gate3_execution"):
        ok, why = is_valid_tasks_json(request_dir / "TASKS.json")
        if not ok:
            failure = canonicalize_failure(
                kind=FailureKind.VERIFIER_ERROR,
                artifact="TASKS.json",
                locator=str(request_dir / "TASKS.json"),
                message=why,
                repro=f"verify_gate:{gate}:validate_tasks_json",
                severity=FailureSeverity.BLOCKER,
            )
            failures.append(failure.to_dict())
            lines = [
                "FAIL",
                "EVIDENCE:",
                f"- {why}",
                "REQUIRED_ACTIONS:",
                "- Fix TASKS.json to be valid JSON with a top-level {\"tasks\": [...]} structure.",
                STOP_TOKEN,
            ]
            return ("FAIL", "\n".join(lines) + "\n", failures)

    # Deliverables are now enforced via Step 6 contract rule (contract:deliverables_exist).

    # Gate3: Check workspace/project structure exists
    if gate == "gate3_execution":
        # Milestone 5.6: Debug path does not require workspace/project
        payload_path = request_dir / "payload.json"
        artifact_class_name = ""
        if payload_path.exists():
            try:
                payload = json.loads(read_text(payload_path))
                artifact_class_name = str(payload.get("artifact_class", "")).strip()
            except Exception:
                artifact_class_name = ""
        if artifact_class_name == "python_debug_script":
            return _verify_debug_artifacts(request_dir)
        
        workspace_project = request_dir / "workspace" / "project"
        if not workspace_project.exists():
            failure = canonicalize_failure(
                kind=FailureKind.VERIFIER_ERROR,
                artifact="workspace/project",
                locator=str(workspace_project),
                message="workspace/project/ directory missing",
                repro=f"verify_gate:{gate}:workspace_project_exists",
                severity=FailureSeverity.BLOCKER,
            )
            failures.append(failure.to_dict())
            lines = [
                "FAIL",
                "EVIDENCE:",
                "- workspace/project/ directory missing",
                "REQUIRED_ACTIONS:",
                "- Developer must create workspace/project/ with project structure",
                STOP_TOKEN,
            ]
            return ("FAIL", "\n".join(lines) + "\n", failures)
        
        # STEP 1: Check artifact class match (deterministic system decision)
        # Artifact class defines WHAT is being built. Verifier checks this FIRST.
        payload_path = request_dir / "payload.json"
        artifact_class_name = None
        artifact_class_def = None
        
        if payload_path.exists():
            try:
                payload = json.loads(read_text(payload_path))
                artifact_class_name = payload.get("artifact_class")
                artifact_class_def = payload.get("artifact_class_definition", {})
                
                if artifact_class_name and artifact_class_def:
                    # Check required behaviors for artifact class
                    required_behaviors = artifact_class_def.get("required_behaviors", [])
                    disallowed_behaviors = artifact_class_def.get("disallowed_behaviors", [])
                    validation_checks = artifact_class_def.get("validation_checks", {})
                    
                    project_files = list(workspace_project.glob("*"))
                    artifact_class_failures = []
                    
                    # Validate against artifact class requirements
                    if artifact_class_name == "webview":
                        # Must have HTML, JS
                        has_html = any(f.suffix == ".html" for f in project_files)
                        has_js = any(f.suffix == ".js" for f in project_files)
                        if not has_html:
                            artifact_class_failures.append(f"- Missing HTML file (required for {artifact_class_name})")
                        if not has_js:
                            artifact_class_failures.append(f"- Missing JavaScript file (required for {artifact_class_name})")
                    
                    elif artifact_class_name == "python_cli":
                        # Must have Python file with argparse/click
                        py_files = [f for f in project_files if f.suffix == ".py"]
                        if not py_files:
                            artifact_class_failures.append(f"- Missing Python file (required for {artifact_class_name})")
                    
                    # Verify intent fulfillment from REQ.json
                    if artifact_class_name in ["python_cli", "python_api", "python_gui", "webview"]:
                        intent_valid, intent_failures = verify_intent_fulfillment(request_dir, workspace_project)
                        if not intent_valid:
                            artifact_class_failures.extend([f"Intent verification failed: {f}" for f in intent_failures])
                        else:
                            has_argparse = False
                            for py_file in py_files:
                                content = read_text(py_file)
                                if "argparse" in content or "click" in content:
                                    has_argparse = True
                                    break
                            if not has_argparse:
                                artifact_class_failures.append(f"- Python CLI file missing argparse or click (required for {artifact_class_name})")
                    
                    elif artifact_class_name == "python_api":
                        # Must have Python file with Flask/FastAPI
                        py_files = [f for f in project_files if f.suffix == ".py"]
                        if not py_files:
                            artifact_class_failures.append(f"- Missing Python file (required for {artifact_class_name})")
                        else:
                            has_framework = False
                            for py_file in py_files:
                                content = read_text(py_file)
                                if ("flask" in content.lower() and ("Flask(" in content or "from flask" in content)) or \
                                   ("fastapi" in content.lower() and ("FastAPI(" in content or "from fastapi" in content)):
                                    has_framework = True
                                    break
                            if not has_framework:
                                artifact_class_failures.append(f"- Python API file missing Flask or FastAPI (required for {artifact_class_name})")
                    
                    elif artifact_class_name == "python_gui":
                        # Must have Python file with tkinter
                        py_files = [f for f in project_files if f.suffix == ".py"]
                        if not py_files:
                            artifact_class_failures.append(f"- Missing Python file (required for {artifact_class_name})")
                        else:
                            has_tkinter = False
                            for py_file in py_files:
                                content = read_text(py_file)
                                if "tkinter" in content.lower() and ("import tkinter" in content or "from tkinter" in content):
                                    has_tkinter = True
                                    break
                            if not has_tkinter:
                                artifact_class_failures.append(f"- Python GUI file missing tkinter (required for {artifact_class_name})")
                    
                    # Check disallowed behaviors
                    for py_file in [f for f in project_files if f.suffix == ".py"]:
                        content = read_text(py_file)
                        if artifact_class_name == "python_cli":
                            if "Flask(" in content or "FastAPI(" in content or "Tk()" in content:
                                artifact_class_failures.append(f"- {py_file.name}: Contains disallowed behavior (web server or GUI) for {artifact_class_name}")
                        elif artifact_class_name == "python_api":
                            if "argparse" in content or "click" in content:
                                artifact_class_failures.append(f"- {py_file.name}: Contains disallowed behavior (CLI) for {artifact_class_name}")
                    
                    # Verify intent fulfillment from REQ.json
                    if artifact_class_name in ["python_cli", "python_api", "python_gui", "webview"]:
                        intent_valid, intent_failures = verify_intent_fulfillment(request_dir, workspace_project)
                        if not intent_valid:
                            artifact_class_failures.extend([f"Intent verification failed: {f}" for f in intent_failures])
                    

                    if artifact_class_failures:
                        lines = [
                            "FAIL",
                            "EVIDENCE:",
                            f"- Artifact class mismatch: Expected {artifact_class_name} ({artifact_class_def.get('label', '')})",
                        ]
                        lines.extend(artifact_class_failures)
                        lines.append("REQUIRED_ACTIONS:")
                        lines.append(f"- Generated code must match artifact class '{artifact_class_name}'")
                        lines.append(f"- Required behaviors: {', '.join(required_behaviors[:3])}...")
                        lines.append("- Fix artifact class shape before checking functionality")
                        lines.append(STOP_TOKEN)
                        failure = canonicalize_failure(
                            kind=FailureKind.CONTRACT_MISMATCH,
                            artifact="artifact_class",
                            locator=str(payload_path),
                            message=f"artifact class mismatch: expected {artifact_class_name}",
                            repro=f"verify_gate:{gate}:artifact_class_mismatch",
                            severity=FailureSeverity.BLOCKER,
                        )
                        failures.append(failure.to_dict())
                        return ("FAIL", "\n".join(lines) + "\n", failures)
            except Exception:
                # If payload.json parsing fails, continue to structure checks
                pass
        
                # NOTE: workspace/runs/ requirement removed for deterministic Generator
        # Generator creates code directly, no trial runs needed
        
        # Check for at least one file in workspace/project (Generator must create something)
        project_files = list(workspace_project.glob("*"))
        project_files = [f for f in project_files if f.is_file()]
        if not project_files:
            lines = [
                "FAIL",
                "EVIDENCE:",
                "- workspace/project/ has no files",
                "REQUIRED_ACTIONS:",
                "- Generator must create at least one file in workspace/project/",
                STOP_TOKEN,
            ]
            failure = canonicalize_failure(
                kind=FailureKind.CONTRACT_MISMATCH,
                artifact="workspace/project",
                locator=str(workspace_project),
                message="workspace/project has no files",
                repro=f"verify_gate:{gate}:workspace_empty",
                severity=FailureSeverity.BLOCKER,
            )
            failures.append(failure.to_dict())
            return ("FAIL", "\n".join(lines) + "\n", failures)
        
        # Behavioral verification: Execute CLI and capture outputs (for python_cli)
        behavioral_results = None
        payload_path = request_dir / "payload.json"
        if payload_path.exists():
            try:
                payload = json.loads(read_text(payload_path))
                artifact_class_name = payload.get("artifact_class")
                if artifact_class_name == "python_cli":
                    behavioral_success, behavioral_error, behavioral_results = execute_cli_behavioral_test(request_dir, workspace_project)
                    if not behavioral_success:
                        lines = [
                            "FAIL",
                            "EVIDENCE:",
                            f"- Behavioral verification failed: {behavioral_error}",
                            "REQUIRED_ACTIONS:",
                            "- Fix generated code to satisfy REQ.json semantics end-to-end.",
                            STOP_TOKEN,
                        ]
                        failure = canonicalize_failure(
                            kind=FailureKind.TEST_FAILURE,
                            artifact="workspace/project",
                            locator=str(workspace_project),
                            message=f"behavioral verification failed: {behavioral_error}",
                            repro=f"verify_gate:{gate}:behavioral_verification",
                            severity=FailureSeverity.BLOCKER,
                        )
                        failures.append(failure.to_dict())
                        return ("FAIL", "\n".join(lines) + "\n", failures)
            except Exception:
                pass  # Skip behavioral verification if payload parsing fails
                

        # Generator creates complete code, no trial runs needed
        has_results = True
        
        # Gate3: Check functionality - validate acceptance criteria from TASKS.json
        tasks_path = request_dir / "TASKS.json"
        if tasks_path.exists():
            try:
                tasks_obj = json.loads(read_text(tasks_path))
                tasks = tasks_obj.get("tasks", [])
                functionality_failures = []
                
                for task in tasks:
                    if not isinstance(task, dict):
                        continue
                    
                    touches = task.get("touches", [])
                    acceptance = task.get("acceptance_criteria", [])
                    description = task.get("description", "").lower()
                    
                    # Check JavaScript files for actual implementation
                    for filename in touches:
                        if filename.endswith('.js'):
                            js_path = workspace_project / filename
                            if js_path.exists():
                                js_content = read_text(js_path)
                                # Check if it has fetch() call (not just a comment)
                                has_fetch = 'fetch(' in js_content and not js_content.strip().startswith('//')
                                # Check if it actually displays/populates data (not just "// Display data" comment)
                                has_display_logic = any(keyword in js_content for keyword in [
                                    'innerHTML', 'textContent', 'appendChild', 'createElement',
                                    'displayRequests', 'render', 'update', 'show'
                                ])
                                # Reject if only has comment like "// Display data" without actual code
                                is_just_comment = js_content.strip().endswith('// Display data') or (
                                    '// Display data' in js_content and 
                                    len([line for line in js_content.split('\n') if line.strip() and not line.strip().startswith('//')]) < 3
                                )
                                
                                if not has_fetch:
                                    functionality_failures.append(f"- {filename}: Missing fetch() call to API endpoints")
                                elif is_just_comment or not has_display_logic:
                                    functionality_failures.append(f"- {filename}: Has fetch() but missing code to display/populate data (only has comment)")
                                    functionality_failures.append("FAILURE_SIGNATURE: MISSING_DOM_MANIPULATION")
                    
                    
                    # Check Python files for actual implementation
                    for filename in touches:
                        if filename.endswith('.py'):
                            py_path = workspace_project / filename
                            if py_path.exists():
                                py_content = read_text(py_path)
                                py_lower = py_content.lower()
                                
                                # Check for placeholder comments
                                placeholder_patterns = [
                                    'placeholder', 'todo', 'fixme', 'not implemented',
                                    'should have generated', 'actual implementation'
                                ]
                                has_placeholder = any(pattern in py_lower for pattern in placeholder_patterns)
                                
                                # CLI projects - check for argparse
                                if 'cli' in description or 'command-line' in description or 'command' in description:
                                    if 'argparse' not in py_content and 'click' not in py_content:
                                        functionality_failures.append(f"- {filename}: CLI file missing argparse or click for command-line interface")
                                        functionality_failures.append("FAILURE_SIGNATURE: MISSING_CLI_PARSER")
                                    if has_placeholder:
                                        functionality_failures.append(f"- {filename}: Contains placeholder text instead of actual CLI implementation")
                                
                                # API projects - check for Flask/FastAPI routes
                                elif 'api' in description or 'rest' in description or 'endpoint' in description or 'flask' in description or 'fastapi' in description:
                                    has_flask = 'flask' in py_lower and ('Flask(' in py_content or 'from flask' in py_content)
                                    has_fastapi = 'fastapi' in py_lower and ('FastAPI(' in py_content or 'from fastapi' in py_content)
                                    has_routes = '@app.route' in py_content or '@app.get' in py_content or '@app.post' in py_content
                                    
                                    if not (has_flask or has_fastapi):
                                        functionality_failures.append(f"- {filename}: API file missing Flask or FastAPI framework")
                                        functionality_failures.append("FAILURE_SIGNATURE: MISSING_API_FRAMEWORK")
                                    elif not has_routes:
                                        functionality_failures.append(f"- {filename}: API file has framework but no route definitions")
                                        functionality_failures.append("FAILURE_SIGNATURE: MISSING_ROUTES")
                                    if has_placeholder:
                                        functionality_failures.append(f"- {filename}: Contains placeholder text instead of actual API implementation")
                                
                                # GUI projects - check for tkinter
                                elif 'gui' in description or 'tkinter' in description or 'graphical' in description:
                                    has_tkinter = 'tkinter' in py_lower and ('import tkinter' in py_content or 'from tkinter' in py_content)
                                    has_window = 'Tk()' in py_content or 'Toplevel()' in py_content
                                    
                                    if not has_tkinter:
                                        functionality_failures.append(f"- {filename}: GUI file missing tkinter import")
                                        functionality_failures.append("FAILURE_SIGNATURE: MISSING_GUI_FRAMEWORK")
                                    elif not has_window:
                                        functionality_failures.append(f"- {filename}: GUI file has tkinter but no window creation")
                                    if has_placeholder:
                                        functionality_failures.append(f"- {filename}: Contains placeholder text instead of actual GUI implementation")
                                
                                # Generic Python - check for actual code
                                else:
                                    code_lines = [line for line in py_content.split('\n') 
                                                if line.strip() and not line.strip().startswith('#') 
                                                and not (line.strip().startswith('"""') or line.strip().startswith("'''"))]
                                    if len(code_lines) < 5 and has_placeholder:
                                        functionality_failures.append(f"- {filename}: Contains placeholder or insufficient implementation")
                    
                    # Check HTML files for proper structure
                    for filename in touches:
                        if filename.endswith('.html'):
                            html_path = workspace_project / filename
                            if html_path.exists():
                                html_content = read_text(html_path)
                                if '<!DOCTYPE html>' not in html_content and '<!doctype html>' not in html_content:
                                    functionality_failures.append(f"- {filename}: Missing DOCTYPE declaration")
                                # Check if HTML references the JS files
                                if any(f.endswith('.js') for f in touches):
                                    js_refs = [f for f in touches if f.endswith('.js')]
                                    for js_file in js_refs:
                                        if f'<script' in html_content and js_file in html_content:
                                            pass  # Good
                                        elif '<script' not in html_content:
                                            functionality_failures.append(f"- {filename}: Missing <script> tag to load JavaScript")
                
                if functionality_failures:
                    lines = [
                        "FAIL",
                        "EVIDENCE:",
                    ]
                    lines.extend(functionality_failures)
                    lines.append("REQUIRED_ACTIONS:")
                    lines.append("- Developer must implement complete, functional code that meets acceptance criteria")
                    lines.append("- Code must be functional, not placeholders or comments only")
                    lines.append("- All acceptance criteria must be satisfied with actual implementation")

            except Exception:
                pass  # Skip functionality checks if TASKS.json parsing fails

    if gate == "gate5_finalize":
        dist_dir = request_dir / "dist"
        if not dist_dir.exists():
            failure = canonicalize_failure(
                kind=FailureKind.VERIFIER_ERROR,
                artifact="dist",
                locator=str(dist_dir),
                message="dist/ directory missing",
                repro=f"verify_gate:{gate}:check_dist",
                severity=FailureSeverity.BLOCKER,
            )
            failures.append(failure.to_dict())
            lines = [
                "FAIL",
                "EVIDENCE:",
                "- dist/ directory missing",
                "REQUIRED_ACTIONS:",
                "- Systems must create dist/ with artifacts, checksums, and ENTRYPOINT.md",
                STOP_TOKEN,
            ]
            return ("FAIL", "\n".join(lines) + "\n", failures)
        
        # Check for at least one artifact
        artifacts = list(dist_dir.glob("*"))
        if not artifacts:
            failure = canonicalize_failure(
                kind=FailureKind.VERIFIER_ERROR,
                artifact="dist",
                locator=str(dist_dir),
                message="dist/ directory is empty",
                repro=f"verify_gate:{gate}:check_dist_artifacts",
                severity=FailureSeverity.BLOCKER,
            )
            failures.append(failure.to_dict())
            lines = [
                "FAIL",
                "EVIDENCE:",
                "- dist/ directory is empty",
                "REQUIRED_ACTIONS:",
                "- Systems must produce at least one artifact in dist/",
                STOP_TOKEN,
            ]
            return ("FAIL", "\n".join(lines) + "\n", failures)

        # Require EXECUTE.json for artifact classes that claim runtime truth
        payload_path = request_dir / "payload.json"
        artifact_class = ""
        if payload_path.exists():
            try:
                payload = json.loads(read_text(payload_path))
                artifact_class = str(payload.get("artifact_class", "")).strip()
            except Exception:
                artifact_class = ""
        if _requires_execute_contract(artifact_class):
            execute_path = dist_dir / "EXECUTE.json"
            if not execute_path.exists():
                failure = canonicalize_failure(
                    kind=FailureKind.CONTRACT_VIOLATION,
                    artifact="dist/EXECUTE.json",
                    locator=str(execute_path),
                    message="missing EXECUTE.json for runtime truth artifact_class",
                    repro=f"verify_gate:{gate}:execute_contract_missing",
                    severity=FailureSeverity.BLOCKER,
                )
                failures.append(failure.to_dict())
                lines = [
                    "FAIL",
                    "EVIDENCE:",
                    "- EXECUTE.json missing for runtime truth artifact class",
                    "REQUIRED_ACTIONS:",
                    "- Systems must write dist/EXECUTE.json with execution contract",
                    STOP_TOKEN,
                ]
                return ("FAIL", "\n".join(lines) + "\n", failures)

    if gate == "gate6_complete":
        dist_dir = request_dir / "dist"
        payload_path = request_dir / "payload.json"
        artifact_class = ""
        if payload_path.exists():
            try:
                payload = json.loads(read_text(payload_path))
                artifact_class = str(payload.get("artifact_class", "")).strip()
            except Exception:
                artifact_class = ""
        if _requires_execute_contract(artifact_class):
            execute_path = dist_dir / "EXECUTE.json"
            if not execute_path.exists():
                failure = canonicalize_failure(
                    kind=FailureKind.CONTRACT_VIOLATION,
                    artifact="dist/EXECUTE.json",
                    locator=str(execute_path),
                    message="missing EXECUTE.json for runtime truth artifact_class",
                    repro=f"verify_gate:{gate}:execute_contract_missing",
                    severity=FailureSeverity.BLOCKER,
                )
                failures.append(failure.to_dict())
                lines = [
                    "FAIL",
                    "EVIDENCE:",
                    "- EXECUTE.json missing for runtime truth artifact class",
                    "REQUIRED_ACTIONS:",
                    "- Systems must write dist/EXECUTE.json with execution contract",
                    STOP_TOKEN,
                ]
                return ("FAIL", "\n".join(lines) + "\n", failures)

    # Contract: payload.deliverables — enforce artifact-internal paths (gate4/5/6)
    REQUEST_DIR_DELIVERABLES = {"SPEC.md", "TASKS.json", "PLAN.md", "NEEDS.json", "REQUEST.md", "payload.json"}
    if gate in ("gate4_review", "gate5_finalize", "gate6_complete"):
        workspace_project = request_dir / "workspace" / "project"
        payload_path = request_dir / "payload.json"
        if payload_path.exists() and workspace_project.exists():
            try:
                payload_obj = json.loads(read_text(payload_path))
                deliverables = payload_obj.get("deliverables", [])
                if isinstance(deliverables, list):
                    for d in deliverables:
                        path = str(d.get("path", "")).strip()
                        if not path:
                            continue
                        if path in REQUEST_DIR_DELIVERABLES:
                            continue  # Already checked by gate_requirements
                        # Artifact-internal: must exist in workspace/project (or artifact zip root)
                        check_path = workspace_project / path
                        if not check_path.exists() or not check_path.is_file():
                            deliverables_missing.append(path)
                            deliverables_check_performed = True
                            failure = canonicalize_from_missing_artifact(
                                artifact_name=path,
                                locator=str(check_path),
                                repro=f"verify_gate:{gate}:deliverable_missing",
                            )
                            failures.append(failure.to_dict())
            except Exception:
                pass
        if deliverables_missing:
            lines = ["FAIL", "EVIDENCE:"]
            for m in deliverables_missing:
                lines.append(f"- Deliverable missing from artifact: {m}")
            lines.append("REQUIRED_ACTIONS:")
            lines.append("- Add the missing file(s) to workspace/project or satisfy the deliverable contract.")
            lines.append(STOP_TOKEN)
            return ("FAIL", "\n".join(lines) + "\n", failures)

    # Any contract failures -> fail immediately (verifier remains oracle).
    if failures:
        lines = ["FAIL", "EVIDENCE:"]
        # Deterministic, human-readable summary
        for f in failures:
            msg = f.get("message", "")
            if msg:
                lines.append(f"- {msg}")
        lines.append("REQUIRED_ACTIONS:")
        lines.append("- Fix contract violations (see failures.json)")
        lines.append(STOP_TOKEN)
        return ("FAIL", "\n".join(lines) + "\n", failures)

    lines = ["PASS", "EVIDENCE:"]
    for f in required:
        lines.append(f"- {f} exists and non-empty")
    if gate in ("gate1_planning", "gate2_delegation", "gate3_execution"):
        lines.append("- TASKS.json is valid JSON with a 'tasks' list")
    if gate == "gate3_execution":
        lines.append("- workspace/project/ structure exists")
        lines.append("- At least one trial run with results.json exists")
    if gate == "gate5_finalize":
        lines.append("- dist/ artifacts exist")
    if deliverables_check_performed:
        lines.append("- All required deliverables present")
    lines.append(STOP_TOKEN)
    
    # Convert failures to dicts if needed
    failures_dicts = []
    for f in failures:
        if hasattr(f, 'to_dict'):
            failures_dicts.append(f.to_dict())
        elif isinstance(f, dict):
            failures_dicts.append(f)
    
    # Sort failures deterministically (by failure_id)
    failures_dicts.sort(key=lambda x: (
        x.get("kind", ""),
        x.get("artifact", ""),
        x.get("locator", ""),
        x.get("failure_id", ""),
    ))
    
    return ("PASS", "\n".join(lines) + "\n", failures_dicts)

def main():
    if len(sys.argv) != 4:
        die("Usage: run_verifier.py <REQUEST_ID> <REQUEST_DIR> <GATE_NAME>")

    request_id = sys.argv[1].strip()
    request_dir = Path(sys.argv[2]).resolve()
    gate = sys.argv[3].strip()

    if not request_id:
        die("REQUEST_ID empty")
    if not request_dir.exists():
        die(f"REQUEST_DIR not found: {request_dir}")
    if not gate:
        die("GATE_NAME empty")

    # Step 4: Create verifier output directory
    verifier_dir = verifier_root(request_dir)
    verifier_dir.mkdir(parents=True, exist_ok=True)

    # Load metadata from payload.json
    payload_path = request_dir / "payload.json"
    policy_version = "v1"
    knowledge_snapshot_id = None
    manifest_bundle_hash = None
    external_snapshot_id = None
    
    if payload_path.exists():
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8", errors="replace"))
            policy_version = payload.get("policy_version", "v1")
            knowledge_snapshot_id = payload.get("knowledge_snapshot_id")
            manifest_bundle_hash = payload.get("manifest_bundle_hash")
            external_snapshot_id = payload.get("external_snapshot_id")
        except Exception:
            pass

    stdout_path = request_dir / "verifier.stdout.txt"
    stderr_path = request_dir / "verifier.stderr.txt"
    raw_out_path = request_dir / "verifier.out.txt"
    verify_md = request_dir / "VERIFY.md"
    meta_path = request_dir / "verifier.meta.json"
    prompt_dump_path = request_dir / "verifier.prompt.txt"

    prompt_dump = build_prompt_dump(request_id, gate, request_dir)
    write_text(prompt_dump_path, prompt_dump)

    # Step 9: If external inputs are pinned, verifier outputs must be byte-identical across runs.
    # Freeze timestamps deterministically for external-snapshot-dependent verification.
    started_at = now_utc()
    status = "ERROR"
    verify_text = ""
    failures_list = []
    checks = []
    
    try:
        result, verify_text, failures_list = verify_gate(request_id, gate, request_dir)
        
        # Map result to status
        if result == "PASS":
            status = "PASS"
        elif result == "FAIL":
            status = "FAIL"
        elif result == "BLOCKED":
            status = "FAIL"  # BLOCKED is treated as FAIL for structured output
        
        # Build checks list from failures (stable IDs required)
        # check_id identifies the check (executed step), failure_id identifies the failure (outcome)
        check_counter = 0
        for failure in failures_list:
            failure_id = failure.get("failure_id", "")
            repro = failure.get("repro", "")
            # Ensure repro is executable or deterministic step token
            if not repro:
                repro = f"check:{check_counter}"
            
            # Generate stable check_id from check characteristics (not failure_id)
            check_id = sha256_bytes(
                f"{gate}:{failure.get('kind', '')}:{failure.get('artifact', '')}:{repro}".encode("utf-8")
            )[:16]
            
            checks.append({
                "check_id": check_id,  # Stable ID for the check (separate from failure_id)
                "status": "FAIL" if failure.get("severity") == "BLOCKER" else "WARN",
                "repro": repro,  # Executable command or deterministic step token
                "kind": failure.get("kind", ""),
                "artifact": failure.get("artifact", ""),
                "failure_ids": [failure_id],  # Link to failure(s) produced by this check
                "details_ref": f"failures.json#{failure_id}",  # Reference to failure details
            })
            check_counter += 1
        
        # If no failures, add a PASS check
        if not failures_list and status == "PASS":
            check_id = f"gate_{gate}_pass"
            checks.append({
                "check_id": check_id,  # Stable ID
                "status": "PASS",
                "repro": f"verify_gate:{gate}",  # Deterministic step token
                "kind": "gate_verification",
                "artifact": gate,
            })
        
    except Exception as e:
        # Verifier crashed - emit ERROR status
        from workers.failure_canonicalizer import canonicalize_from_verifier_error
        import traceback as tb
        
        stack_trace = "".join(tb.format_exc())
        failure = canonicalize_from_verifier_error(str(e), stack_trace)
        failures_list = [failure.to_dict()]
        
        verify_text = f"ERROR\nVerifier crashed: {e}\n{STOP_TOKEN}\n"
        status = "ERROR"
        # Generate stable check_id for verifier error check
        check_id = sha256_bytes(
            f"verifier_error:{gate}:internal".encode("utf-8")
        )[:16]
        
        checks = [{
            "check_id": check_id,  # Stable ID for the check (separate from failure_id)
            "status": "ERROR",
            "repro": failure.repro or "verifier_internal",  # Executable or step token
            "kind": "verifier_error",
            "artifact": "verifier",
            "failure_ids": [failure.failure_id],  # Link to failure
            "details_ref": f"failures.json#{failure.failure_id}",
        }]
    
    ended_at = now_utc()
    from dcs_core.repro_env import is_repro_mode
    if external_snapshot_id or is_repro_mode():
        started_at = "1970-01-01T00:00:00Z"
        ended_at = "1970-01-01T00:00:00Z"

    # Milestone 3.0: compile/test validation hooks (artifact-class aware).
    # Deterministic outputs under request_dir/validation/.
    validation_bundle_sha256 = None
    try:
        workspace_project = request_dir / "workspace" / "project"
        if gate in ("gate3_execution", "gate4_review", "gate5_finalize", "gate6_complete") and workspace_project.exists():
            payload_obj = {}
            if payload_path.exists():
                try:
                    payload_obj = json.loads(payload_path.read_text(encoding="utf-8", errors="replace"))
                except Exception:
                    payload_obj = {}
            artifact_class = str(payload_obj.get("artifact_class", "")).strip()
            if artifact_class.startswith("python_"):
                from workers.validation_runner import run_python_validation, write_validation_result
                # Gate3: syntax/structure only (py_compile). Tests required in gate4+.
                run_tests = gate not in ("gate3_execution",)
                steps, vfailures = run_python_validation(
                    request_dir=request_dir,
                    workspace_project=workspace_project,
                    python_exe=sys.executable,
                    run_tests_if_present=run_tests,
                )
                validation_bundle_sha256 = write_validation_result(request_dir, steps)
                if vfailures:
                    failures_list.extend(vfailures)
                    status = "FAIL"
                    # Add a deterministic validation check entry (linked to failures via failure_ids).
                    try:
                        fids = [f.get("failure_id", "") for f in vfailures if isinstance(f, dict)]
                        checks.append({
                            "check_id": sha256_bytes(f"{gate}:validation:python".encode("utf-8"))[:16],
                            "status": "FAIL",
                            "repro": "validation:python",
                            "kind": "compile_error" if any((f.get("kind") == "compile_error") for f in vfailures if isinstance(f, dict)) else "test_failure",
                            "artifact": "validation",
                            "failure_ids": [x for x in fids if x],
                            "details_ref": "validation/result.json",
                        })
                    except Exception:
                        pass
                
                # Milestone 4.2: Runtime smoke validation (verifier-owned)
                if artifact_class == "python_cli" and gate in ("gate4_review", "gate5_finalize", "gate6_complete"):
                    # Check for smoke args in suite metadata (if available)
                    smoke_args = None
                    # TODO: Load smoke args from suite metadata if available
                    # For now, no smoke args (just --help)
                    
                    from workers.validation_runner import run_runtime_smoke_validation
                    runtime_success, runtime_failures = run_runtime_smoke_validation(
                        request_dir=request_dir,
                        workspace_project=workspace_project,
                        python_exe=sys.executable,
                        artifact_class=artifact_class,
                        smoke_args=smoke_args,
                    )
                    if not runtime_success:
                        failures_list.extend(runtime_failures)
                        status = "FAIL"
                        # Add runtime smoke check entry
                        try:
                            fids = [f.get("failure_id", "") for f in runtime_failures if isinstance(f, dict)]
                            checks.append({
                                "check_id": sha256_bytes(f"{gate}:validation:runtime_smoke".encode("utf-8"))[:16],
                                "status": "FAIL",
                                "repro": "validation:runtime_smoke",
                                "kind": "runtime_exception",
                                "artifact": "validation:runtime",
                                "failure_ids": [x for x in fids if x],
                                "details_ref": "validation/runtime/result.json",
                            })
                        except Exception:
                            pass
    except Exception:
        # Validation must never crash verifier; failures come only from explicit results.
        validation_bundle_sha256 = validation_bundle_sha256

    # Step 4: Write structured outputs
    verifier_result = {
        "request_id": request_id,
        "policy_version": policy_version,
        "knowledge_snapshot_id": knowledge_snapshot_id,
        "manifest_bundle_hash": manifest_bundle_hash,
        "external_snapshot_id": external_snapshot_id,
        "status": status,
        "verifier_version": "v1",
        "started_at": started_at,
        "ended_at": ended_at,
        "checks": checks,
        "summary": {
            "total_checks": len(checks),
            "passed": len([c for c in checks if c.get("status") == "PASS"]),
            "failed": len([c for c in checks if c.get("status") == "FAIL"]),
            "errors": len([c for c in checks if c.get("status") == "ERROR"]),
            "failures_by_kind": {},
        },
    }
    if validation_bundle_sha256:
        verifier_result["validation_bundle_sha256"] = validation_bundle_sha256
    
    # Count failures by kind
    for failure in failures_list:
        kind = failure.get("kind", "unknown")
        verifier_result["summary"]["failures_by_kind"][kind] = \
            verifier_result["summary"]["failures_by_kind"].get(kind, 0) + 1
    
    result_path = verifier_dir / "verifier.result.json"
    write_text(result_path, json.dumps(verifier_result, indent=2, sort_keys=True) + "\n")
    
    # Write failures.json
    failures_json = {
        "request_id": request_id,
        "policy_version": policy_version,
        "knowledge_snapshot_id": knowledge_snapshot_id,
        "manifest_bundle_hash": manifest_bundle_hash,
        "failures": failures_list,
    }
    failures_path = verifier_dir / "failures.json"
    write_text(failures_path, json.dumps(failures_json, indent=2, sort_keys=True) + "\n")

    # Keep legacy outputs
    write_text(stdout_path, verify_text)
    write_text(stderr_path, "")
    write_text(raw_out_path, verify_text)
    write_text(verify_md, verify_text)  # Derived from structured output

    meta = {
        "REQUEST_ID": request_id,
        "GATE": gate,
        "RESULT": result if 'result' in locals() else status,
        "AT_UTC": now_utc(),
        "LLAMA_RC": None,
        "KILLED_REASON": "deterministic_python_verifier",
        "HASHES": {
            "verifier.prompt.txt": sha256_bytes(prompt_dump.encode("utf-8", errors="replace")),
            "verifier.out.txt": sha256_bytes(verify_text.encode("utf-8", errors="replace")),
            "VERIFY.md": sha256_bytes(verify_text.encode("utf-8", errors="replace")),
        },
    }
    if validation_bundle_sha256:
        meta["HASHES"]["validation/bundle.json"] = validation_bundle_sha256
    write_text(meta_path, json.dumps(meta, indent=2) + "\n")

    print(result if 'result' in locals() else status)

if __name__ == "__main__":
    main()
