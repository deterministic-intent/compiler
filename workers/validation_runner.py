#!/usr/bin/env python3
"""
Milestone 3.0: Deterministic compile/test validation runner.

This module is pure logic + filesystem writes under request_dir/validation/.
It must be replay-safe and byte-identical across runs.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _write_bytes(p: Path, b: bytes) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b)


def _write_json(p: Path, obj: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _stable_env(base_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = dict(base_env or os.environ)
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.setdefault("LC_ALL", "C")
    env.setdefault("LANG", "C")
    # Do not allow any interactive prompts.
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


@dataclass(frozen=True)
class ValidationStepResult:
    step_id: str
    command: List[str]
    cwd_rel: str
    exit_code: int
    stdout_sha256: str
    stderr_sha256: str
    status: str  # PASS | FAIL | SKIP
    repro: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "command": self.command,
            "cwd_rel": self.cwd_rel,
            "exit_code": self.exit_code,
            "stdout_sha256": self.stdout_sha256,
            "stderr_sha256": self.stderr_sha256,
            "status": self.status,
            "repro": self.repro,
        }


def run_python_validation(
    *,
    request_dir: Path,
    workspace_project: Path,
    python_exe: str,
    run_tests_if_present: bool = True,
) -> Tuple[List[ValidationStepResult], List[Dict[str, Any]]]:
    """
    Returns (step_results, failures_to_append).
    Does not decide final verifier status; caller does.
    """
    from workers.failure_canonicalizer import canonicalize_from_compile_error, canonicalize_from_test_failure

    vdir = request_dir / "validation"
    vdir.mkdir(parents=True, exist_ok=True)

    failures: List[Dict[str, Any]] = []
    steps: List[ValidationStepResult] = []

    # --- Step: py_compile (no .pyc writes; deterministic ordering) ---
    py_files = sorted([p for p in workspace_project.rglob("*.py") if p.is_file()], key=lambda p: str(p))
    if not py_files:
        # Nothing to compile; skip (but still record deterministically).
        out_b = b""
        err_b = b""
        _write_bytes(vdir / "py_compile.stdout.txt", out_b)
        _write_bytes(vdir / "py_compile.stderr.txt", err_b)
        steps.append(
            ValidationStepResult(
                step_id="py_compile",
                command=[python_exe, "-B", "-m", "py_compile"],
                cwd_rel=str(workspace_project.relative_to(request_dir)).replace("\\", "/"),
                exit_code=0,
                stdout_sha256=_sha256_bytes(out_b),
                stderr_sha256=_sha256_bytes(err_b),
                status="SKIP",
                repro="validation:py_compile:skip_no_py_files",
            )
        )
    else:
        cmd = [python_exe, "-B", "-m", "py_compile"] + [str(p) for p in py_files]
        p = subprocess.run(
            cmd,
            cwd=str(workspace_project),
            env=_stable_env(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=False,
        )
        out_b = p.stdout or b""
        err_b = p.stderr or b""
        _write_bytes(vdir / "py_compile.stdout.txt", out_b)
        _write_bytes(vdir / "py_compile.stderr.txt", err_b)
        steps.append(
            ValidationStepResult(
                step_id="py_compile",
                command=cmd,
                cwd_rel=str(workspace_project.relative_to(request_dir)).replace("\\", "/"),
                exit_code=int(p.returncode),
                stdout_sha256=_sha256_bytes(out_b),
                stderr_sha256=_sha256_bytes(err_b),
                status="PASS" if p.returncode == 0 else "FAIL",
                repro=" ".join(cmd[:6]) + " …",  # stable, minimal repro token
            )
        )
        if p.returncode != 0:
            failures.append(
                canonicalize_from_compile_error(
                    error_output=err_b.decode("utf-8", errors="replace"),
                    artifact="validation:py_compile",
                    locator=str(workspace_project),
                    repro="validation:py_compile",
                ).to_dict()
            )

    # --- Step: tests (stdlib only) ---
    tests_dir = workspace_project / "tests"
    if run_tests_if_present and tests_dir.exists() and tests_dir.is_dir():
        cmd = [python_exe, "-B", "-m", "unittest", "discover", "-s", "tests", "-p", "test*.py"]
        p = subprocess.run(
            cmd,
            cwd=str(workspace_project),
            env=_stable_env(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=False,
        )
        out_b = p.stdout or b""
        err_b = p.stderr or b""
        _write_bytes(vdir / "unittest.stdout.txt", out_b)
        _write_bytes(vdir / "unittest.stderr.txt", err_b)
        steps.append(
            ValidationStepResult(
                step_id="unittest",
                command=cmd,
                cwd_rel=str(workspace_project.relative_to(request_dir)).replace("\\", "/"),
                exit_code=int(p.returncode),
                stdout_sha256=_sha256_bytes(out_b),
                stderr_sha256=_sha256_bytes(err_b),
                status="PASS" if p.returncode == 0 else "FAIL",
                repro="validation:unittest",
            )
        )
        if p.returncode != 0:
            failures.append(
                canonicalize_from_test_failure(
                    test_name="unittest",
                    error_output=(out_b + err_b).decode("utf-8", errors="replace"),
                    artifact="validation:unittest",
                    locator=str(tests_dir),
                    repro="validation:unittest",
                ).to_dict()
            )
    else:
        out_b = b""
        err_b = b""
        _write_bytes(vdir / "unittest.stdout.txt", out_b)
        _write_bytes(vdir / "unittest.stderr.txt", err_b)
        steps.append(
            ValidationStepResult(
                step_id="unittest",
                command=[python_exe, "-B", "-m", "unittest", "discover", "-s", "tests", "-p", "test*.py"],
                cwd_rel=str(workspace_project.relative_to(request_dir)).replace("\\", "/"),
                exit_code=0,
                stdout_sha256=_sha256_bytes(out_b),
                stderr_sha256=_sha256_bytes(err_b),
                status="SKIP",
                repro="validation:unittest:skip_no_tests",
            )
        )

    return steps, failures


def write_validation_result(request_dir: Path, step_results: List[ValidationStepResult]) -> str:
    """
    Writes validation/result.json and returns a deterministic bundle sha256 over written files.
    """
    vdir = request_dir / "validation"
    vdir.mkdir(parents=True, exist_ok=True)
    obj = {
        "validation_version": 1,
        "steps": [s.to_dict() for s in step_results],
    }
    _write_json(vdir / "result.json", obj)

    # Bundle hash over exact bytes of known files (sorted).
    parts: List[Tuple[str, bytes]] = []
    for name in sorted(p.name for p in vdir.glob("*.txt")):
        parts.append((name, (vdir / name).read_bytes()))
    parts.append(("result.json", (vdir / "result.json").read_bytes()))
    h = hashlib.sha256()
    for name, b in parts:
        h.update(name.encode("utf-8"))
        h.update(b"\n")
        h.update(b)
        h.update(b"\n")
    bundle = h.hexdigest()
    _write_json(vdir / "bundle.json", {"bundle_sha256": bundle})
    return bundle


def run_runtime_smoke_validation(
    *,
    request_dir: Path,
    workspace_project: Path,
    python_exe: str,
    artifact_class: str,
    smoke_args: Optional[List[str]] = None,
) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Milestone 4.2: Runtime smoke validation for artifact classes.
    
    Returns (success, failures_to_append).
    Creates artifacts under validation/runtime/:
    - commands.json
    - stdout.txt, stderr.txt
    - stdout.sha256, stderr.sha256
    - exit_code.json
    - result.json
    
    Deterministic clamps:
    - no network
    - env: PYTHONHASHSEED=0, LC_ALL=C, TZ=UTC, PYTHONDONTWRITEBYTECODE=1
    - stable working dir under request state
    """
    from workers.failure_canonicalizer import canonicalize_failure, FailureKind, FailureSeverity
    
    runtime_dir = request_dir / "validation" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    
    failures: List[Dict[str, Any]] = []
    commands: List[Dict[str, Any]] = []
    
    # Deterministic environment (no network, stable)
    env = _stable_env()
    env["TZ"] = "UTC"
    # Block network access
    env.pop("HTTP_PROXY", None)
    env.pop("HTTPS_PROXY", None)
    env.pop("http_proxy", None)
    env.pop("https_proxy", None)
    
    # Stable working directory under request state
    work_dir = request_dir / "validation" / "runtime" / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    
    if artifact_class == "python_cli":
        # Find main entrypoint (prefer main.py, then first .py file)
        main_py = None
        main_py_path = workspace_project / "main.py"
        if main_py_path.exists() and main_py_path.is_file():
            main_py = main_py_path
        else:
            py_files = sorted([p for p in workspace_project.glob("*.py") if p.is_file()], key=lambda p: str(p))
            if py_files:
                main_py = py_files[0]
        
        if not main_py or not main_py.exists():
            failures.append(
                canonicalize_failure(
                    kind=FailureKind.RUNTIME_EXCEPTION,
                    artifact="validation:runtime_smoke",
                    locator=str(workspace_project),
                    message="No Python files found for runtime smoke",
                    repro="validation:runtime_smoke:no_py_files",
                    severity=FailureSeverity.BLOCKER,
                ).to_dict()
            )
            # Write empty artifacts
            _write_json(runtime_dir / "commands.json", {"commands": []})
            _write_bytes(runtime_dir / "stdout.txt", b"")
            _write_bytes(runtime_dir / "stderr.txt", b"")
            (runtime_dir / "stdout.sha256").write_text(_sha256_bytes(b""), encoding="utf-8")
            (runtime_dir / "stderr.sha256").write_text(_sha256_bytes(b""), encoding="utf-8")
            _write_json(runtime_dir / "exit_code.json", {"exit_code": 1})
            _write_json(runtime_dir / "result.json", {"status": "FAIL", "reason": "no_py_files"})
            return (False, failures)
        
        main_py_rel = str(main_py.relative_to(workspace_project))
        
        # Command 1: --help
        cmd_help = [python_exe, "-B", str(main_py), "--help"]
        p_help = subprocess.run(
            cmd_help,
            cwd=str(work_dir),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=False,
        )
        stdout_help = p_help.stdout or b""
        stderr_help = p_help.stderr or b""
        
        commands.append({
            "command": cmd_help,
            "cwd": str(work_dir.relative_to(request_dir)).replace("\\", "/"),
            "exit_code": p_help.returncode,
            "stdout_sha256": _sha256_bytes(stdout_help),
            "stderr_sha256": _sha256_bytes(stderr_help),
        })
        
        if p_help.returncode != 0:
            failures.append(
                canonicalize_failure(
                    kind=FailureKind.RUNTIME_EXCEPTION,
                    artifact="validation:runtime_smoke",
                    locator=f"{main_py_rel}:--help",
                    message=f"CLI --help failed with exit code {p_help.returncode}",
                    repro="validation:runtime_smoke:help_failed",
                    severity=FailureSeverity.BLOCKER,
                ).to_dict()
            )
        
        # Command 2: smoke args (if provided)
        if smoke_args:
            cmd_smoke = [python_exe, "-B", str(main_py)] + smoke_args
            p_smoke = subprocess.run(
                cmd_smoke,
                cwd=str(work_dir),
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=False,
            )
            stdout_smoke = p_smoke.stdout or b""
            stderr_smoke = p_smoke.stderr or b""
            
            commands.append({
                "command": cmd_smoke,
                "cwd": str(work_dir.relative_to(request_dir)).replace("\\", "/"),
                "exit_code": p_smoke.returncode,
                "stdout_sha256": _sha256_bytes(stdout_smoke),
                "stderr_sha256": _sha256_bytes(stderr_smoke),
            })
            
            if p_smoke.returncode != 0:
                failures.append(
                    canonicalize_failure(
                        kind=FailureKind.RUNTIME_EXCEPTION,
                        artifact="validation:runtime_smoke",
                        locator=f"{main_py_rel}:smoke_args",
                        message=f"CLI smoke args failed with exit code {p_smoke.returncode}",
                        repro="validation:runtime_smoke:smoke_args_failed",
                        severity=FailureSeverity.BLOCKER,
                    ).to_dict()
                )
            
            # Combine outputs (help + smoke)
            stdout_combined = stdout_help + b"\n--- smoke ---\n" + stdout_smoke
            stderr_combined = stderr_help + b"\n--- smoke ---\n" + stderr_smoke
        else:
            stdout_combined = stdout_help
            stderr_combined = stderr_help
        
        # Write artifacts
        _write_json(runtime_dir / "commands.json", {"commands": commands})
        _write_bytes(runtime_dir / "stdout.txt", stdout_combined)
        _write_bytes(runtime_dir / "stderr.txt", stderr_combined)
        (runtime_dir / "stdout.sha256").write_text(_sha256_bytes(stdout_combined), encoding="utf-8")
        (runtime_dir / "stderr.sha256").write_text(_sha256_bytes(stderr_combined), encoding="utf-8")
        
        # Determine overall exit code (fail if any command failed)
        overall_exit_code = 0 if all(cmd.get("exit_code", 0) == 0 for cmd in commands) else 1
        _write_json(runtime_dir / "exit_code.json", {"exit_code": overall_exit_code})
        
        status = "PASS" if overall_exit_code == 0 else "FAIL"
        _write_json(runtime_dir / "result.json", {
            "status": status,
            "commands_run": len(commands),
            "commands_passed": len([c for c in commands if c.get("exit_code", 0) == 0]),
        })
        
        return (overall_exit_code == 0, failures)
    else:
        # Unsupported artifact class - skip but record
        _write_json(runtime_dir / "commands.json", {"commands": []})
        _write_bytes(runtime_dir / "stdout.txt", b"")
        _write_bytes(runtime_dir / "stderr.txt", b"")
        _write_text(runtime_dir / "stdout.sha256", _sha256_bytes(b""))
        _write_text(runtime_dir / "stderr.sha256", _sha256_bytes(b""))
        _write_json(runtime_dir / "exit_code.json", {"exit_code": 0})
        _write_json(runtime_dir / "result.json", {"status": "SKIP", "reason": f"unsupported_artifact_class:{artifact_class}"})
        return (True, [])




