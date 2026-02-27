#!/usr/bin/env python3
"""
Step 14: DCS CLI Productization (Control Plane).

UX-only shell that orchestrates existing deterministic gates and presents results.
Must not write deterministic artifacts directly (only orchestrator/workers do).
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import hashlib
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dcs_cli import ux


BASE = Path(__file__).resolve().parents[1]


# Locked branding (docs/dcs_cli_branding_r1.md). Render exactly.
BANNER = (
    "    __                  _____     _____    _____                       ____   \n"
    "   / /                 |  __ \\   / ____|  / ____|                     / /\\ \\  \n"
    "  / /   ______ ______  | |  | | | |      | (___    ______ ______     / /  \\ \\ \n"
    " < <   |______|______| | |  | | | |       \\___ \\  |______|______|   / /    > >\n"
    "  \\ \\                  | |__| | | |____   ____) |                  / /    / / \n"
    "   \\_\\                 |_____/   \\_____| |_____/                  /_/    /_/  \n"
    "\n"
    "Deterministic Compiler System\n"
)

# Compact fallback banner (terminal width < 80 columns OR explicit compact banner mode).
COMPACT_BANNER = "DCS - Deterministic Compiler System\n"
PROMPT = "dcs> "
DOTS = ".........."


GATE_TABLE = [
    (0, "wiring + context"),
    (1, "snapshot + manifests"),
    (2, "deterministic selection"),
    (3, "verifier"),
    (4, "repair loop"),
    (5, "contract enforcement"),
    (6, "replay readiness"),
    (7, "deliver"),
]


ORCH_GATE_CMDS = {
    0: "gate0_init",
    1: "gate1_planning",
    2: "gate2_delegation",
    3: "gate3_execution",
    4: "gate4_review",
    5: "gate5_finalize",
    6: "gate6_complete",
}


ERRORS = {
    "bad_args": ("DCS-E0001", 2),
    "missing_request": ("DCS-E1001", 2),
    "gate_failed": ("DCS-E2001", 1),
    "clarify": ("DCS-E3001", 12),
    "file_not_found": ("DCS-E4001", 2),
}

_BINARY_SUFFIXES = {
    ".zip",
    ".tar",
    ".tgz",
    ".gz",
    ".bin",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}

def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()

_COMPILE_DCS_KEYS_ORDER = [
    "request_id",
    "artifact_class",
    "goal",
    "constraints",
    "non_goals",
    "policy_version",
    "knowledge_snapshot_id",
    "manifest_bundle_hash",
    "answer_mode",
]


def _is_replay() -> bool:
    from dcs_core.repro_env import is_repro_mode
    return is_repro_mode()


def _isatty() -> bool:
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


def _ux_mode(args) -> ux.UXMode:
    return ux.UXMode(
        isatty=_isatty(),
        json=bool(getattr(args, "json", False)),
        replay=_is_replay(),
        spinner=str(getattr(args, "spinner", "auto")),
        effects_env=str(os.environ.get("DCS_EFFECTS", "1")),
    )


def _print_banner(args) -> None:
    if not ux.should_banner(_ux_mode(args)):
        return
    cols = shutil.get_terminal_size(fallback=(80, 24)).columns
    compact = bool(getattr(args, "compact_banner", False) or getattr(args, "no_banner", False) or cols < 80)
    sys.stdout.write(COMPACT_BANNER if compact else BANNER)
    sys.stdout.flush()


def _err(kind: str, msg: str) -> int:
    code, exit_code = ERRORS.get(kind, ("DCS-E9999", 1))
    sys.stderr.write(f"{code}: {msg}\n")
    sys.stderr.flush()
    return exit_code


def _request_dir(request_id: str) -> Path:
    root = os.environ.get("NLC_REQUESTS_ROOT", "").strip()
    req_root = Path(root).resolve() if root else BASE / "state" / "requests"
    return req_root / request_id


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")

def _normalize_ws(s: str) -> str:
    return " ".join((s or "").strip().split())

def _is_binary_file(p: Path, sample_bytes: int = 2048) -> bool:
    # Deterministic heuristic: suffix allowlist OR NUL byte OR strict UTF-8 decode failure.
    if p.suffix.lower() in _BINARY_SUFFIXES:
        return True
    try:
        b = p.read_bytes()[:sample_bytes]
    except Exception:
        return False
    if b"\x00" in b:
        return True
    try:
        b.decode("utf-8", errors="strict")
    except Exception:
        return True
    return False


def _safe_path(p: str) -> Optional[Path]:
    if not p:
        return None
    pp = Path(p)
    if not pp.is_absolute():
        pp = (Path.cwd() / pp).resolve()
    return pp


def _snapshot_root() -> Path:
    return BASE / "nlc" / "db" / "snapshots"


def _list_snapshot_ids() -> List[str]:
    root = _snapshot_root()
    if not root.exists():
        return []
    ids: List[str] = []
    for p in root.iterdir():
        if p.is_dir():
            ids.append(p.name)
    ids.sort()
    return ids


def _resolve_snapshot_id(explicit_snapshot: str = "", allow_policy_default: bool = True) -> Tuple[Optional[str], Optional[dict]]:
    """
    Deterministically resolve knowledge_snapshot_id.
    Rule: if explicit_snapshot is provided, validate and use it.
          Else use policy.defaults.snapshot_id ONLY if allow_policy_default and present.
          Never uses env or hardcoded fallback.
    Returns (snapshot_id, None) on success, (None, clarify_dict) on failure.
    Canonical reason codes: SNAPSHOT_ID_REQUIRED, SNAPSHOT_ID_INVALID, MANIFEST_BUNDLE_HASH_MISSING.
    """
    sid = _normalize_ws(explicit_snapshot)
    ids = _list_snapshot_ids()

    if sid:
        if sid not in ids:
            return None, {
                "reason": "SNAPSHOT_ID_INVALID",
                "reason_codes": ["SNAPSHOT_ID_INVALID"],
                "questions": [f"Snapshot not found: {sid}. Provide a valid snapshot id or create/build snapshots."],
                "candidates": ids,
                "suggested_flag": "--snapshot-id",
                "suggested_env": "NLC_DB_SNAPSHOT_ID",
            }
        return sid, None

    # No explicit snapshot: use policy default only
    if allow_policy_default:
        try:
            from policy import get_default_snapshot_id
            default_sid = get_default_snapshot_id()
            if default_sid:
                if default_sid not in ids:
                    return None, {
                        "reason": "SNAPSHOT_ID_INVALID",
                        "reason_codes": ["SNAPSHOT_ID_INVALID"],
                        "questions": [f"Policy default snapshot {default_sid} not found. Update policy or provide --snapshot-id."],
                        "candidates": ids,
                        "suggested_flag": "--snapshot-id",
                    }
                return default_sid, None
        except Exception:
            pass

    if not ids:
        return None, {
            "reason": "SNAPSHOT_ID_REQUIRED",
            "reason_codes": ["SNAPSHOT_ID_REQUIRED"],
            "questions": ["No snapshots found. Build a snapshot, then pass --snapshot-id <id>."],
            "candidates": [],
            "suggested_flag": "--snapshot-id",
            "suggested_env": "NLC_DB_SNAPSHOT_ID",
        }

    return None, {
        "reason": "SNAPSHOT_ID_REQUIRED",
        "reason_codes": ["SNAPSHOT_ID_REQUIRED"],
        "questions": ["Snapshot id required. Pass --snapshot-id <id>. Policy has no defaults.snapshot_id."],
        "candidates": ids,
        "suggested_flag": "--snapshot-id",
        "suggested_env": "NLC_DB_SNAPSHOT_ID",
    }


def _resolve_manifest_bundle_hash(snapshot_id: str) -> Tuple[Optional[str], Optional[dict]]:
    """
    Deterministically resolve manifest_bundle_hash from snapshot manifests.
    No empty hash fallback. Canonical: MANIFEST_BUNDLE_HASH_MISSING.
    """
    manifest_dir = _snapshot_root() / snapshot_id / "manifest"
    if not manifest_dir.exists():
        return None, {
            "reason": "MANIFEST_BUNDLE_HASH_MISSING",
            "reason_codes": ["MANIFEST_BUNDLE_HASH_MISSING"],
            "questions": [f"Snapshot {snapshot_id} is missing manifest/. Build snapshot manifests first."],
            "candidates": [snapshot_id],
            "snapshot_id": snapshot_id,
        }
    try:
        from nlc.reproducibility import get_manifest_hashes
        info = get_manifest_hashes(snapshot_id)
        got = str(info.get("manifest_bundle_hash", "")).strip()
        if not got:
            return None, {
                "reason": "MANIFEST_BUNDLE_HASH_MISSING",
                "reason_codes": ["MANIFEST_BUNDLE_HASH_MISSING"],
                "questions": [f"Snapshot {snapshot_id} has no manifest bundle hash. Ensure required manifest files exist."],
                "candidates": [snapshot_id],
                "snapshot_id": snapshot_id,
            }
        return got, None
    except Exception:
        return None, {
            "reason": "MANIFEST_BUNDLE_HASH_MISSING",
            "reason_codes": ["MANIFEST_BUNDLE_HASH_MISSING"],
            "questions": [f"Could not compute manifest bundle hash for snapshot {snapshot_id}."],
            "candidates": [snapshot_id],
            "snapshot_id": snapshot_id,
        }


def _infer_artifact_class(text: str) -> Tuple[Optional[str], Optional[dict]]:
    """
    Deterministic, minimal v1 classifier. No LLM. No guessing.
    """
    t = _normalize_ws(text).lower()
    if "python" in t and "cli" in t:
        return "python_cli", None
    return None, {
        "reason": "EMPTY_INPUT" if not _normalize_ws(text) else "MISSING_ARTIFACT_CLASS",
        "questions": ["Specify the artifact type explicitly (e.g., include 'python cli')."],
        "candidates": ["python_cli"],
    }


def _compile_to_dcs_obj(text: str, policy_version: str, snapshot_id: str, bundle_hash: str) -> dict:
    goal = _normalize_ws(text)
    seed = f"{policy_version}\n{snapshot_id}\n{bundle_hash}\n{goal}".encode("utf-8")
    rid = "COMPILED_" + hashlib.sha256(seed).hexdigest()[:12].upper()
    obj: Dict[str, Any] = {
        "request_id": rid,
        "artifact_class": "python_cli",  # set by classifier above
        "goal": goal,
        "constraints": [],
        "non_goals": [],
        "policy_version": policy_version,
        "knowledge_snapshot_id": snapshot_id,
        "manifest_bundle_hash": bundle_hash,
        "answer_mode": "index_backed",
    }
    # Emit in strict key order (stable, non-sorted).
    return {k: obj[k] for k in _COMPILE_DCS_KEYS_ORDER}


def _write_dcs_file(path: Path, obj: dict) -> None:
    # Canonical formatting: stable key order, indent=2, trailing newline.
    s = json.dumps(obj, indent=2, sort_keys=False, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(s, encoding="utf-8")


def _emit_gate_status(args, gate_n: int, gate_status: str) -> None:
    label = dict(GATE_TABLE).get(gate_n, f"gate{gate_n}")
    ux.emit_gate_status(_ux_mode(args), gate_n, label, DOTS, gate_status)


def _run_subprocess(
    cmd: List[str],
    spinner_message: str,
    mode: ux.UXMode,
    *,
    env: Optional[Dict[str, str]] = None,
) -> Tuple[int, str, str]:
    with ux.GateProgress(mode, spinner_message):
        p = subprocess.run(cmd, cwd=str(BASE), env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    return p.returncode, p.stdout or "", p.stderr or ""


def _run_orch_gate(args, request_id: str, gate_n: int, orch_args: List[str], env: Optional[Dict[str, str]] = None) -> Tuple[int, str]:
    if gate_n not in ORCH_GATE_CMDS:
        return 0, "PASS"
    rd = _request_dir(request_id)
    if gate_n >= 1:
        try:
            if (rd / "INTENT_RESOLUTION.json").exists() or (rd / "FIELD_RESOLUTION.json").exists():
                cp = rd / "CLARIFY.json"
                if cp.exists():
                    cp.unlink()
        except Exception:
            pass
    cmd = [sys.executable, str(BASE / "orchestrator" / "orchestrator.py"), ORCH_GATE_CMDS[gate_n], request_id] + orch_args
    label = dict(GATE_TABLE).get(gate_n, f"gate{gate_n}")
    rc, out, err = _run_subprocess(
        cmd,
        # When spinner is clamped and fallback is used, requirement is:
        # exactly "[loading] <gate name>".
        spinner_message=str(label),
        mode=_ux_mode(args),
        env=env,
    )
    # Orchestrator writes gate status file; trust that as the gate result.
    status_path = rd / f"gate{gate_n}.status"
    gate_status = status_path.read_text(encoding="utf-8", errors="replace").strip() if status_path.exists() else "FAIL"

    # If orchestrator signaled clarification, propagate as exit 12 (and do not invent answers).
    if gate_status == "CLARIFY":
        return ERRORS["clarify"][1], gate_status

    # On failure, print captured output deterministically (stdout then stderr).
    if rc != 0 or gate_status != "PASS":
        sys.stderr.write(f"{ERRORS['gate_failed'][0]}: gate{gate_n} failed\n")
        # Gate0 BLOCKED should surface machine-readable reason codes, if present.
        if gate_n == 0 and gate_status == "BLOCKED":
            rp = rd / "gate0.result.json"
            if rp.exists():
                try:
                    robj = json.loads(_read_text(rp))
                except Exception:
                    robj = {}
                if isinstance(robj, dict):
                    rcs = robj.get("reason_codes", [])
                    if isinstance(rcs, list) and rcs:
                        sys.stderr.write(f"{ERRORS['gate_failed'][0]}: gate0 BLOCKED reason_codes={rcs}\n")
        if out.strip():
            sys.stderr.write(out)
            if not out.endswith("\n"):
                sys.stderr.write("\n")
        if err.strip():
            sys.stderr.write(err)
            if not err.endswith("\n"):
                sys.stderr.write("\n")
        sys.stderr.flush()
    return (0 if gate_status == "PASS" else ERRORS["gate_failed"][1]), gate_status


def _deliverable_primary(rd: Path) -> Optional[Path]:
    # Deterministic selection: avoid timestamped verifier.result.json in plain text mode.
    # Prefer artifacts without timestamps to keep display deterministic across reruns.
    candidates = [
        rd / "dist" / "artifact.zip",
        rd / "answer" / "answer.json",
        rd / "planner" / "plan.json",
        rd / "PLAN.md",
        rd / "SPEC.md",
        rd / "TASKS.json",
        rd / "VERIFY.md",
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return p
    return None


def _count_lines(s: str) -> int:
    return s.replace("\r\n", "\n").replace("\r", "\n").count("\n") + (0 if s.endswith("\n") else 1)


def _present_deliverable(args, path: Path) -> None:
    # Use canonical dcs command for copy/paste.
    dcs_abs = "dcs"
    # Binary deliverables must never be auto-printed.
    if path.suffix.lower() in (".zip", ".gz", ".tar", ".tgz"):
        n_lines = 0
        sys.stdout.write("DELIVERABLE\n")
        sys.stdout.write("type: binary\n")
        sys.stdout.write(f"lines: {n_lines}\n")
        sys.stdout.write(f"path: {str(path.resolve())}\n\n")
        sys.stdout.write("COPY\n")
        sys.stdout.write(f"{dcs_abs} inspect cat --path {str(path.resolve())}\n")
        sys.stdout.write("\nDETAILS\n")
        sys.stdout.write(f"path: {str(path.resolve())}\n")
        sys.stdout.write(f"lines: {n_lines}\n")
        sys.stdout.flush()
        return

    content = _read_text(path)
    n_lines = _count_lines(content)
    if n_lines <= 30:
        sys.stdout.write("-----BEGIN DELIVERABLE-----\n")
        sys.stdout.write(content if content.endswith("\n") else content + "\n")
        sys.stdout.write("-----END DELIVERABLE-----\n")
    else:
        sys.stdout.write("DELIVERABLE\n")
        sys.stdout.write(f"type: {'json' if path.suffix == '.json' else 'text'}\n")
        sys.stdout.write(f"lines: {n_lines}\n")
        sys.stdout.write(f"path: {str(path.resolve())}\n\n")
        sys.stdout.write("COPY\n")
        sys.stdout.write(f"{dcs_abs} inspect cat --path {str(path.resolve())}\n")
    # DETAILS block (stable, no timestamps)
    sys.stdout.write("\nDETAILS\n")
    sys.stdout.write(f"path: {str(path.resolve())}\n")
    sys.stdout.write(f"lines: {n_lines}\n")
    sys.stdout.flush()


def _print_clarify_and_repl(request_id: str) -> int:
    rd = _request_dir(request_id)
    cp = rd / "CLARIFY.json"
    if cp.exists():
        try:
            obj = json.loads(_read_text(cp))
        except Exception:
            obj = {}
        questions = obj.get("questions", [])
        sys.stdout.write("CLARIFY\n")
        for q in questions if isinstance(questions, list) else []:
            sys.stdout.write(f"- {q}\n")
        sys.stdout.flush()
    return _repl()




def _repl() -> int:
    # UX-only; read-only commands; never triggers gates.
    last_req = ""
    while True:
        try:
            line = input(PROMPT)
        except EOFError:
            return 0
        except KeyboardInterrupt:
            sys.stdout.write("\n")
            continue

        s = (line or "").strip()
        if not s:
            continue
        if s in (":quit", ":q", "quit", "exit"):
            return 0
        if s in (":help", ":h"):
            sys.stdout.write(":help\n:quit\n:config\n:last\n:cat <path>\n:open <path>\n")
            sys.stdout.flush()
            continue
        if s == ":config":
            cfg = {"replay": _is_replay(), "cwd": str(Path.cwd().resolve())}
            sys.stdout.write(json.dumps(cfg, indent=2, sort_keys=True) + "\n")
            sys.stdout.flush()
            continue
        if s == ":last":
            # Read-only: compute "last" deterministically from state/requests.
            rid = _find_last_request_id()
            sys.stdout.write((rid or "") + "\n")
            sys.stdout.flush()
            continue
        if s.startswith(":cat "):
            p = _safe_path(s[len(":cat ") :].strip())
            if not p or not p.exists():
                sys.stderr.write(f"{ERRORS['file_not_found'][0]}: file not found\n")
                sys.stderr.flush()
                continue
            sys.stdout.write(_read_text(p))
            if not _read_text(p).endswith("\n"):
                sys.stdout.write("\n")
            sys.stdout.flush()
            continue
        if s.startswith(":open "):
            p = _safe_path(s[len(":open ") :].strip())
            if not p:
                sys.stderr.write(f"{ERRORS['file_not_found'][0]}: file not found\n")
                sys.stderr.flush()
                continue
            sys.stdout.write(f"OPEN\npath: {str(p)}\n")
            sys.stdout.flush()
            continue
        # Unknown: read-only REPL, so do nothing beyond message.
        sys.stderr.write(f"{ERRORS['bad_args'][0]}: unknown command\n")
        sys.stderr.flush()

def _find_last_request_id() -> str:
    # Read-only: choose lexicographically greatest request id under state/requests.
    root = BASE / "state" / "requests"
    if not root.exists():
        return ""
    ids = []
    for p in root.iterdir():
        if p.is_dir():
            ids.append(p.name)
    ids.sort()
    return ids[-1] if ids else ""


def _parse_dcs_file(path: Path) -> Dict[str, Any]:
    # .dcs is a JSON file (deterministic, no code execution).
    obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(obj, dict):
        raise ValueError("dcs file must be a JSON object")
    return obj


def _derive_request_id_from_path(path: Path) -> str:
    # Deterministic request id derived from filename.
    stem = path.stem.strip().upper().replace("-", "_")
    stem = "".join([c for c in stem if (c.isalnum() or c == "_")])
    return f"DCS_{stem}" if stem else "DCS_REQUEST"


def cmd_init(args) -> int:
    _print_banner(args)
    if not args.request_id or not args.objective:
        return _err("bad_args", "init requires --request-id and --objective")
    env = os.environ.copy()
    objective = json.dumps(args.objective)
    constraints = json.dumps(args.constraints or [])
    non_goals = json.dumps(args.non_goals or [])
    dod = json.dumps(args.dod or [])
    rc, gate_status = _run_orch_gate(args, args.request_id, 0, [objective, constraints, non_goals, dod], env=env)
    if args.json:
        sys.stdout.write(json.dumps({"command": "init", "request_id": args.request_id, "gate": 0, "status": gate_status}, indent=2, sort_keys=True) + "\n")
        return 0 if gate_status == "PASS" else rc
    _emit_gate_status(args, 0, gate_status)
    if rc == ERRORS["clarify"][1]:
        return _print_clarify_and_repl(args.request_id)
    return rc


def _require_request(request_id: str) -> Optional[int]:
    if not request_id:
        return _err("bad_args", "--request-id required")
    rd = _request_dir(request_id)
    if not rd.exists():
        return _err("missing_request", f"request not found: {request_id}")
    return None


def _cmd_build_legacy(args) -> int:
    """Legacy: run gates 1-2 on existing request."""
    _print_banner(args)
    errc = _require_request(args.request_id)
    if errc is not None:
        return errc
    statuses: Dict[int, str] = {}
    env = os.environ.copy()
    for n in (1, 2):
        rc, st = _run_orch_gate(args, args.request_id, n, [], env=env)
        statuses[n] = st
        if args.json:
            continue
        _emit_gate_status(args, n, st)
        if rc == ERRORS["clarify"][1]:
            return _print_clarify_and_repl(args.request_id)
        if rc != 0:
            return rc
    if args.json:
        sys.stdout.write(json.dumps({"command": "build", "request_id": args.request_id, "gates": statuses}, indent=2, sort_keys=True) + "\n")
    return 0


def cmd_run(args) -> int:
    # Interactive mode: read stdin, run pipeline, and print run command
    if getattr(args, "interactive", False) or (not getattr(args, "spec_path", None) and not getattr(args, "request_id", None)):
        args.json = False
        _print_banner(args)
        prompt_text = _read_prompt_from_stdin()
        if not prompt_text:
            return _err("bad_args", "empty prompt")
        _clamp_stdin()
        snapshot_id, clarify = _resolve_snapshot_id("", allow_policy_default=True)
        if clarify:
            sys.stdout.write(json.dumps(clarify, indent=2, sort_keys=True) + "\n")
            sys.stdout.flush()
            return ERRORS["clarify"][1]
        bundle_hash, clarify = _resolve_manifest_bundle_hash(snapshot_id)
        if clarify:
            sys.stdout.write(json.dumps(clarify, indent=2, sort_keys=True) + "\n")
            sys.stdout.flush()
            return 2
        dcs_path = _create_intake_dcs(prompt_text, snapshot_id, bundle_hash)
        return _run_one_command_pipeline(dcs_path, include_run_this=True)

    _print_banner(args)
    # File-based run: `dcs run examples/hello_world.dcs`
    if getattr(args, "spec_path", None):
        spec_path = Path(args.spec_path).resolve()
        if not spec_path.exists():
            return _err("file_not_found", f"spec not found: {spec_path}")
        try:
            spec = _parse_dcs_file(spec_path)
        except Exception as e:
            return _err("bad_args", f"invalid .dcs file: {e}")

        request_id = str(spec.get("request_id") or _derive_request_id_from_path(spec_path)).strip()
        objective = str(spec.get("goal") or spec.get("objective", "")).strip()
        constraints = spec.get("constraints", [])
        non_goals = spec.get("non_goals", [])
        dod = spec.get("dod", [])
        policy_version = str(spec.get("policy_version", "v1")).strip() or "v1"
        snapshot_id = str(spec.get("knowledge_snapshot_id", "")).strip()
        bundle_hash = str(spec.get("manifest_bundle_hash", "")).strip()
        artifact_class = str(spec.get("artifact_class", "")).strip()
        files = spec.get("files", {})
        entrypoint = str(spec.get("entrypoint", "")).strip()
        runtime_args = spec.get("runtime_args", [])

        # Milestone 5.6: Embed python_debug_script inputs into objective as JSON block
        if artifact_class == "python_debug_script" and isinstance(files, dict) and files:
            payload_block = {
                "artifact_class": artifact_class,
                "files": files,
                "entrypoint": entrypoint,
                "runtime_args": runtime_args if isinstance(runtime_args, list) else [],
            }
            json_block = json.dumps(payload_block, indent=2, sort_keys=True)
            objective = objective + "\n\n```json\n" + json_block + "\n```\n"

        # Configure env pins deterministically for gate0 payload binding (do not mutate parent env).
        env = os.environ.copy()
        env["NLC_POLICY_VERSION"] = policy_version
        if snapshot_id:
            env["NLC_DB_SNAPSHOT_ID"] = snapshot_id
            env["NLC_SNAPSHOT_ID"] = snapshot_id
            env["NLC_KB_SNAPSHOT_ID"] = snapshot_id
        else:
            env.pop("NLC_DB_SNAPSHOT_ID", None)
            env.pop("NLC_SNAPSHOT_ID", None)
            env.pop("NLC_KB_SNAPSHOT_ID", None)

        # If bundle hash is provided in spec, ensure it matches pinned snapshot manifests deterministically.
        if snapshot_id and bundle_hash:
            try:
                from nlc.reproducibility import get_manifest_hashes
                info = get_manifest_hashes(snapshot_id)
                got = str(info.get("manifest_bundle_hash", "")).strip()
                if got and got != bundle_hash:
                    sys.stderr.write(f"{ERRORS['bad_args'][0]}: manifest_bundle_hash mismatch\n")
                    sys.stderr.flush()
                    return ERRORS["bad_args"][1]
            except Exception:
                # If reproducibility lookup fails, allow gate0 to deterministically BLOCK later.
                pass

        # Deterministic reruns: remove existing request dir to avoid gate0 FileExistsError.
        rd = _request_dir(request_id)
        if rd.exists():
            import shutil
            shutil.rmtree(rd, ignore_errors=True)

        # init + build + run sequence
        statuses: Dict[int, str] = {}
        attempts = 0
        while True:
            rc, st = _run_orch_gate(
                args,
                request_id,
                0,
                [json.dumps(objective), json.dumps(constraints or []), json.dumps(non_goals or []), json.dumps(dod or [])],
                env=env,
            )
            statuses[0] = st
            _emit_gate_status(args, 0, st)
            if rc == ERRORS["clarify"][1]:
                return _print_clarify_and_repl(request_id)
            if rc != 0:
                return rc if rc != ERRORS["clarify"][1] else _print_clarify_and_repl(request_id)
            break
        for n in (1, 2, 3, 4, 5, 6):
            attempts = 0
            while True:
                rc, st = _run_orch_gate(args, request_id, n, [], env=env)
                statuses[n] = st
                _emit_gate_status(args, n, st)
                if rc == ERRORS["clarify"][1]:
                    return _print_clarify_and_repl(request_id)
                if rc == ERRORS["clarify"][1]:
                    return _print_clarify_and_repl(request_id)
                if rc != 0:
                    return rc
                break

        # Gate 7: deliver (UX-only)
        label = dict(GATE_TABLE).get(7, "deliver")
        with ux.GateProgress(_ux_mode(args), label):
            pass
        primary = _deliverable_primary(rd)
        deliver_ok = primary is not None
        statuses[7] = "PASS" if deliver_ok else "FAIL"
        if args.json:
            out = {"command": "run", "spec_path": str(spec_path), "request_id": request_id, "gates": statuses}
            sys.stdout.write(json.dumps(out, indent=2, sort_keys=True) + "\n")
            return 0 if deliver_ok else ERRORS["gate_failed"][1]
        _emit_gate_status(args, 7, statuses[7])
        if primary:
            _present_deliverable(args, primary)
            return 0
        return ERRORS["gate_failed"][1]

    # Request-id run: `dcs run --request-id ...`
    errc = _require_request(args.request_id)
    if errc is not None:
        return errc

    statuses: Dict[int, str] = {}
    env = os.environ.copy()
    # Run gates 3..6 (existing orchestrator). Gate 7 is UX-only deliver step.
    for n in (3, 4, 5, 6):
        attempts = 0
        while True:
            rc, st = _run_orch_gate(args, args.request_id, n, [], env=env)
            statuses[n] = st
            if args.json:
                break
            _emit_gate_status(args, n, st)
            if rc == ERRORS["clarify"][1]:
                return _print_clarify_and_repl(args.request_id)
            if rc == ERRORS["clarify"][1]:
                return _print_clarify_and_repl(args.request_id)
            if rc != 0:
                return rc
            break

    # Gate 7: deliver (UX-only)
    label = dict(GATE_TABLE).get(7, "deliver")
    with ux.GateProgress(_ux_mode(args), label):
        pass
    rd = _request_dir(args.request_id)
    primary = _deliverable_primary(rd)
    deliver_ok = primary is not None
    statuses[7] = "PASS" if deliver_ok else "FAIL"
    if args.json:
        out = {"command": "run", "request_id": args.request_id, "gates": statuses, "deliverable": str(primary.resolve()) if primary else ""}
        sys.stdout.write(json.dumps(out, indent=2, sort_keys=True) + "\n")
        return 0 if deliver_ok else ERRORS["gate_failed"][1]
    _emit_gate_status(args, 7, statuses[7])
    if primary:
        _present_deliverable(args, primary)
        return 0
    return ERRORS["gate_failed"][1]


def cmd_verify(args) -> int:
    _print_banner(args)
    errc = _require_request(args.request_id)
    if errc is not None:
        return errc
    gate = str(args.gate_name).strip()
    if not gate:
        return _err("bad_args", "--gate-name required")
    rd = _request_dir(args.request_id)
    cmd = [sys.executable, str(BASE / "workers" / "run_verifier.py"), args.request_id, str(rd), gate]
    rc, out, err = _run_subprocess(
        cmd,
        spinner_message="verify",
        mode=_ux_mode(args),
        env=os.environ.copy(),
    )
    if args.json:
        sys.stdout.write(json.dumps({"command": "verify", "request_id": args.request_id, "gate_name": gate, "exit": rc}, indent=2, sort_keys=True) + "\n")
        return 0 if rc == 0 else ERRORS["gate_failed"][1]
    if out.strip():
        sys.stdout.write(out)
        if not out.endswith("\n"):
            sys.stdout.write("\n")
    if err.strip():
        sys.stderr.write(err)
        if not err.endswith("\n"):
            sys.stderr.write("\n")
    sys.stdout.flush()
    sys.stderr.flush()
    return 0 if rc == 0 else ERRORS["gate_failed"][1]


def cmd_repair(args) -> int:
    _print_banner(args)
    errc = _require_request(args.request_id)
    if errc is not None:
        return errc
    rd = _request_dir(args.request_id)
    cmd = [sys.executable, str(BASE / "workers" / "run_repair.py"), args.request_id, str(rd), args.gate_name]
    rc, out, err = _run_subprocess(
        cmd,
        spinner_message="repair",
        mode=_ux_mode(args),
        env=os.environ.copy(),
    )
    if out.strip():
        sys.stdout.write(out if out.endswith("\n") else out + "\n")
    if err.strip():
        sys.stderr.write(err if err.endswith("\n") else err + "\n")
    sys.stdout.flush()
    sys.stderr.flush()
    return 0 if rc == 0 else ERRORS["gate_failed"][1]


def cmd_replay_pipeline(args) -> int:
    """
    Replay = new request dir from captured inputs, run gates 1-3, diff dist hashes.
    Contract: replay must run on a fresh directory (same inputs, same snapshot).
    """
    _print_banner(args)
    source_request_id = (
        str(getattr(args, "request_id_pos", "") or getattr(args, "request_id", "") or "").strip()
    )
    if not source_request_id:
        return _err("bad_args", "replay --request-id required")
    errc = _require_request(source_request_id)
    if errc is not None:
        return errc

    replay_request_id = (source_request_id + "_replay")[:80]
    orig_rd = _request_dir(source_request_id)
    replay_rd = _request_dir(replay_request_id)

    if replay_rd.exists():
        shutil.rmtree(replay_rd, ignore_errors=True)
    replay_rd.mkdir(parents=True, exist_ok=True)

    for name in ("REQUEST.md", "REQ.json", "payload.json"):
        src = orig_rd / name
        if src.exists():
            shutil.copy2(src, replay_rd / name)

    payload = json.loads((replay_rd / "payload.json").read_text(encoding="utf-8", errors="replace"))
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    state = {
        "REQUEST_ID": replay_request_id,
        "GATE": 1,
        "ITERATION": 0,
        "CREATED_AT_UTC": now,
        "UPDATED_AT_UTC": now,
        "ARTIFACTS": {},
        "HISTORY": [{"AT_UTC": now, "EVENT": "GATE0_INIT"}, {"AT_UTC": now, "EVENT": "GATE0_RESULT_PASS"}],
        "FAILURES": [],
    }
    (replay_rd / "state.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for g in range(7):
        (replay_rd / f"gate{g}.status").write_text("PASS" if g == 0 else "NOT_RUN", encoding="utf-8")
    (replay_rd / "gate0.result.json").write_text(
        json.dumps({"status": "PASS", "reason_codes": [], "details": ""}, indent=2) + "\n", encoding="utf-8"
    )

    env = os.environ.copy()
    env["NLC_DB_SNAPSHOT_ID"] = str(payload.get("knowledge_snapshot_id", ""))
    env["DCS_REPRO"] = "1"
    env.setdefault("PYTHONHASHSEED", "0")
    env.setdefault("TZ", "UTC")

    for n in (1, 2, 3):
        rc, st = _run_orch_gate(args, replay_request_id, n, [], env=env)
        if args.json:
            continue
        _emit_gate_status(args, n, st)
        if rc != 0:
            sys.stderr.write(f"replay gate{n} failed: {st}\n")
            return rc

    orig_dist = orig_rd / "dist"
    replay_dist = replay_rd / "dist"
    dist_files = ["manifest.json", "checksums.sha256", "ENTRYPOINT.md"]
    zip_candidates = ["artifact.zip", "site.zip"]
    zip_name = None
    for z in zip_candidates:
        if (orig_dist / z).exists() and (replay_dist / z).exists():
            zip_name = z
            break
    if zip_name:
        dist_files.append(zip_name)
    mismatches = []
    for fn in dist_files:
        o = orig_dist / fn
        r = replay_dist / fn
        if not o.exists():
            mismatches.append("%s: missing in original" % fn)
            continue
        if not r.exists():
            mismatches.append("%s: missing in replay" % fn)
            continue
        h_o = _sha256_file(o)
        h_r = _sha256_file(r)
        if h_o != h_r:
            mismatches.append("%s: hash mismatch original=%s replay=%s" % (fn, h_o, h_r))
    if mismatches:
        for m in mismatches:
            sys.stderr.write("replay dist mismatch: %s\n" % m)
        if args.json:
            sys.stdout.write(json.dumps({
                "command": "replay",
                "original": source_request_id,
                "replay": replay_request_id,
                "dist_match": False,
                "mismatches": mismatches,
            }, indent=2, sort_keys=True) + "\n")
        return 1
    if not zip_name:
        if args.json:
            sys.stdout.write(json.dumps({
                "command": "replay",
                "original": source_request_id,
                "replay": replay_request_id,
                "dist_match": False,
                "reason": "no artifact.zip or site.zip in both dirs",
            }, indent=2, sort_keys=True) + "\n")
        sys.stderr.write("replay: no artifact.zip or site.zip in both dirs to compare\n")
        return 1
    if args.json:
        hashes = {fn: _sha256_file(orig_dist / fn) for fn in dist_files}
        sys.stdout.write(json.dumps({
            "command": "replay",
            "original": source_request_id,
            "replay": replay_request_id,
            "dist_match": True,
            "hashes": hashes,
        }, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write("replay dist all match: %s\n" % ", ".join(dist_files))
    return 0


def cmd_replay(args) -> int:
    # Replay clamps: banner/effects already gated on NLC_REPRO.
    _print_banner(args)
    # Full pipeline replay: dcs replay --request-id X (no --gate-name) -> new dir, run 1-3, diff dist
    gate = str(getattr(args, "gate_name", "") or getattr(args, "gate_name_pos", "") or "").strip()
    if not gate:
        return cmd_replay_pipeline(args)

    # Verifier replay: dcs replay --request-id X --gate-name gate3
    if args.request_id_pos and args.gate_name_pos:
        source_request_id = str(args.request_id_pos).strip()
        replay_id = str(getattr(args, "request_id", "") or "").strip() or "replay1"
    else:
        source_request_id = str(getattr(args, "request_id", "") or "").strip()
        replay_id = "replay1"
    if not source_request_id:
        return _err("bad_args", "--request-id required")
    errc = _require_request(source_request_id)
    if errc is not None:
        return errc
    cmd = [sys.executable, str(BASE / "scripts" / "run_replay.py"), source_request_id, gate, "--replay-id", replay_id]
    rc, out, err = _run_subprocess(
        cmd,
        spinner_message="replay",
        mode=_ux_mode(args),
        env=os.environ.copy(),
    )
    if out.strip():
        sys.stdout.write(out if out.endswith("\n") else out + "\n")
    if err.strip():
        sys.stderr.write(err if err.endswith("\n") else err + "\n")
    sys.stdout.flush()
    sys.stderr.flush()
    return 0 if rc == 0 else ERRORS["gate_failed"][1]


def cmd_user_verify(args) -> int:
    _print_banner(args)
    request_id = str(args.request_id or "").strip()
    if not request_id:
        return _err("bad_args", "--request-id required")
    rd = _request_dir(request_id)
    if not rd.exists():
        return _err("missing_request", f"request not found: {request_id}")
    dist_dir = rd / "dist"
    execute_path = dist_dir / "EXECUTE.json"
    if not execute_path.exists():
        return _err("bad_args", f"EXECUTE.json missing: {execute_path}")
    try:
        execute_contract = json.loads(execute_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return _err("bad_args", "EXECUTE.json invalid JSON")
    entry_command = execute_contract.get("entry_command", [])
    if not isinstance(entry_command, list) or not entry_command:
        return _err("bad_args", "EXECUTE.json entry_command must be non-empty array")
    cwd_rel = str(execute_contract.get("cwd_rel", ".")).strip() or "."
    expected_exit = int(execute_contract.get("expected_exit_code", 0))
    artifact_zip = dist_dir / "artifact.zip"
    if not artifact_zip.exists():
        return _err("bad_args", f"artifact.zip missing: {artifact_zip}")
    out_root = BASE / "out" / "user_verify" / request_id
    if out_root.exists():
        shutil.rmtree(out_root, ignore_errors=True)
    out_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(artifact_zip, "r") as zf:
        zf.extractall(out_root)
    run_cwd = out_root / cwd_rel
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.setdefault("LC_ALL", "C")
    env.setdefault("LANG", "C")
    env.setdefault("TZ", "UTC")
    p = subprocess.run(entry_command, cwd=str(run_cwd), env=env, capture_output=True)
    stdout = p.stdout or b""
    stderr = p.stderr or b""
    (out_root / "stdout.txt").write_bytes(stdout)
    (out_root / "stderr.txt").write_bytes(stderr)
    result = {
        "request_id": request_id,
        "artifact_path": str(artifact_zip.relative_to(BASE)).replace("\\", "/"),
        "execute_contract": str(execute_path.relative_to(BASE)).replace("\\", "/"),
        "entry_command": entry_command,
        "cwd_rel": cwd_rel,
        "expected_exit_code": expected_exit,
        "exit_code": p.returncode,
        "stdout_sha256": _sha256_bytes(stdout),
        "stderr_sha256": _sha256_bytes(stderr),
        "stdout_path": str((out_root / "stdout.txt").relative_to(BASE)).replace("\\", "/"),
        "stderr_path": str((out_root / "stderr.txt").relative_to(BASE)).replace("\\", "/"),
    }
    (out_root / "user_verify.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if p.returncode == expected_exit else 1


def cmd_inspect(args) -> int:
    # Read-only
    _print_banner(args)
    if args.inspect_cmd == "last":
        rid = _find_last_request_id()
        if not rid:
            return _err("missing_request", "no requests found")
        sys.stdout.write(rid + "\n")
        sys.stdout.flush()
        return 0
    if args.inspect_cmd == "cat":
        p = _safe_path(args.path)
        if not p or not p.exists():
            return _err("file_not_found", "file not found")
        # Never dump binary blobs to the terminal.
        if _is_binary_file(p):
            abs_p = str(p.resolve())
            sys.stdout.write("BINARY\n")
            sys.stdout.write(f"path: {abs_p}\n")
            sys.stdout.write("\nCOPY\n")
            sys.stdout.write(f"python3 -m zipfile -l {abs_p}\n")
            sys.stdout.write(f"python3 -m zipfile -t {abs_p}\n")
            sys.stdout.flush()
            return 0
        sys.stdout.write(_read_text(p))
        if not _read_text(p).endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
        return 0
    return _err("bad_args", "unknown inspect command")


def cmd_doctor(args) -> int:
    # Read-only (may run audit which writes request artifacts; allowed as diagnostic tool)
    _print_banner(args)

    base_cmd = [sys.executable, str(BASE / "scripts" / "audit" / "run_audit.py"), "--policy", "v1"]
    deps_cmd = [sys.executable, str(BASE / "scripts" / "check_scraper_deps.py")]

    # Compute statuses without dumping full audit logs.
    env = os.environ.copy()
    env.setdefault("AUDIT_SCOPE", "v1")
    p = subprocess.run(base_cmd, cwd=str(BASE), stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env)
    base_ok = (p.returncode == 0)

    deps = subprocess.run(deps_cmd, cwd=str(BASE), stdin=subprocess.DEVNULL, capture_output=True, text=True)
    deps_ok = (deps.returncode == 0)
    deps_line = (deps.stdout or deps.stderr or "").strip().splitlines()[:1]

    # Output: no timestamps, no randomness; just truth + exact commands.
    sys.stdout.write(f"Base audit: {'PASS' if base_ok else 'FAIL'}\n")
    sys.stdout.write(f"Scraper deps installed: {'yes' if deps_ok else 'no'}\n")
    sys.stdout.write(f"Full audit available: {'yes' if deps_ok else 'no'}\n")
    sys.stdout.write("python3 scripts/audit/run_audit.py\n")
    if not deps_ok:
        if deps_line:
            sys.stdout.write(deps_line[0] + "\n")
        sys.stdout.write("bash scripts/install_scraper_deps.sh\n")
    sys.stdout.write("python3 scripts/audit/run_audit_full.py\n")
    sys.stdout.flush()

    return int(p.returncode)


def _emit_structured_failure(reason_code: str, detail: str = "") -> int:
    """Emit canonical failure for structured intake. Exit non-zero."""
    msg = f"DCS-E0001: {reason_code}"
    if detail:
        msg += f": {detail}"
    sys.stderr.write(msg + "\n")
    return 2


def _resolve_intent_to_req(
    args: Any,
    intent_id: str,
    lang: str,
    snapshot_arg: str,
) -> dict | None:
    """Resolve --intent to req_obj (flat format). Returns None on error (emits to stderr)."""
    if not lang:
        sys.stderr.write("DCS-E0001: Pass --lang (e.g. python)\n")
        return None
    sid_input = _normalize_ws(snapshot_arg)
    if not sid_input or sid_input.lower() == "none":
        sys.stderr.write("DCS-E0001: Pass --snapshot-id (required for --intent)\n")
        return None
    snapshot_id, clarify = _resolve_snapshot_id(sid_input, allow_policy_default=False)
    if clarify or not snapshot_id or snapshot_id.lower() == "none":
        sys.stderr.write("DCS-E0001: Valid --snapshot-id required\n")
        return None
    try:
        from orchestrator.intent_registry import resolve_intent, validate_params
    except ImportError:
        sys.stderr.write("DCS-E0001: intent_registry not found\n")
        return None
    entry, err = resolve_intent(intent_id, lang, snapshot_id)
    if err:
        sys.stderr.write(f"DCS-E0001: {err}\n")
        return None
    params = {}
    if intent_id == "print_sequence":
        p_from = getattr(args, "param_from", None)
        p_to = getattr(args, "param_to", None)
        p_step = getattr(args, "step", None)
        if p_from is None or p_to is None:
            sys.stderr.write("DCS-E0001: print_sequence requires --param-from and --param-to\n")
            return None
        params = {"from": p_from, "to": p_to, "step": p_step if p_step is not None else 1}
    ok, err_code = validate_params(entry, params)
    if not ok:
        sys.stderr.write(f"DCS-E0001: {err_code or 'PARAM_SCHEMA_INVALID'}\n")
        return None
    bundle_hash, clarify = _resolve_manifest_bundle_hash(snapshot_id)
    if clarify or not bundle_hash:
        sys.stderr.write("DCS-E0001: Could not resolve manifest_bundle_hash\n")
        return None
    return {
        "kind": "REQ",
        "req_version": "v1",
        "intent_id": intent_id,
        "language": lang,
        "params": params,
        "snapshot_id": snapshot_id,
        "manifest_bundle_hash": bundle_hash,
        "module_refs": entry.get("module_refs") or [],
        "artifact_class": entry.get("artifact_class") or "python_cli",
    }


def _cmd_build_intent(
    args: Any,
    intent_id: str,
    lang: str,
    snapshot_arg: str,
    no_policy_default: bool,
) -> int:
    """Build from --intent. Snapshot ID is mandatory for v1 structured path; no fallback."""
    req_obj = _resolve_intent_to_req(args, intent_id, lang, snapshot_arg)
    if req_obj is None:
        return 2
    return _run_structured_intake(req_obj, snapshot_arg, no_policy_default)


def _run_structured_intake(req_obj: dict, snapshot_arg: str, no_policy_default: bool) -> int:
    """
    Run pipeline from v1 REQ. Bootstrap request dir, run gates 1-6 (skip gate0).
    """
    from nlc.net_guard import activate_network_guard
    activate_network_guard()
    from policy.req_validator import validate_req_v1
    from orchestrator.intent_registry import resolve_intent

    ok, err = validate_req_v1(req_obj)
    if not ok:
        return _emit_structured_failure("REQ_SCHEMA_INVALID", err)
    intent_id = str(req_obj.get("intent_id", "")).strip()
    lang = str(req_obj.get("language", "")).strip()
    params = req_obj.get("params") or {}
    snapshot_id = str(req_obj.get("snapshot_id", "")).strip()
    bundle_hash = str(req_obj.get("manifest_bundle_hash", "")).strip()
    if not snapshot_id or snapshot_id == "none":
        sid_input = _normalize_ws(snapshot_arg)
        if not sid_input or sid_input.lower() == "none":
            return _emit_structured_failure("POLICY.SNAPSHOT_ID_REQUIRED", "REQ must have snapshot_id or pass --snapshot-id (required for v1)")
        sid, clarify = _resolve_snapshot_id(sid_input, allow_policy_default=False)
        if clarify or not sid:
            return _emit_structured_failure("POLICY.SNAPSHOT_ID_REQUIRED", "REQ must have snapshot_id or pass --snapshot-id (required for v1)")
        snapshot_id = sid
    if not bundle_hash:
        if snapshot_id and snapshot_id != "none":
            bh, clarify = _resolve_manifest_bundle_hash(snapshot_id)
            if not clarify:
                bundle_hash = bh or ""
        if not bundle_hash:
            return _emit_structured_failure("MANIFEST_BUNDLE_HASH_MISSING")
    entry, resolve_err = resolve_intent(intent_id, lang, snapshot_id)
    if resolve_err:
        return _emit_structured_failure(resolve_err)
    module_refs = entry.get("module_refs") or []
    artifact_class = entry.get("artifact_class") or "python_cli"
    # intent_type for generator (from intent_id for single-intent v1)
    intent_type = intent_id
    # Request id: NLC_REQUEST_ID (proof kit) or deterministic from REQ content
    req_bytes = json.dumps(req_obj, sort_keys=True).encode("utf-8")
    request_id = os.environ.get("NLC_REQUEST_ID", "").strip()
    if not request_id:
        request_id = "V1_" + hashlib.sha256(req_bytes).hexdigest()[:12].upper()
    rd = _request_dir(request_id)
    if rd.exists():
        shutil.rmtree(rd, ignore_errors=True)
    rd.mkdir(parents=True, exist_ok=True)
    # REQ.json in intents-array format (generator expects this)
    internal_req = {
        "schema_version": "req_v1",
        "kind": "REQ",
        "intents": [
            {
                "intent_type": intent_type,
                "intent_id": intent_id,
                "params": params,
                "module_refs": module_refs,
                "artifact_class": artifact_class,
                "language": lang,
            }
        ],
    }
    (rd / "REQ.json").write_text(json.dumps(internal_req, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    req_sha256 = hashlib.sha256((rd / "REQ.json").read_bytes()).hexdigest()
    payload = {
        "schema_version": "ir_v1",
        "request_id": request_id,
        "goal": f"{intent_id}({lang}): {params}",
        "artifact_class": artifact_class,
        "policy_version": "v1",
        "knowledge_snapshot_id": snapshot_id,
        "manifest_bundle_hash": bundle_hash,
        "req_sha256": req_sha256,
        "module_refs": module_refs,
        "constraints": [],
        "non_goals": [],
        "success_criteria": [],
        "deliverables": [],
        "inputs": {},
        "tooling": {},
    }
    (rd / "payload.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (rd / "REQUEST.md").write_text(
        f"# REQUEST {request_id}\n\n## Objective\n{intent_id} ({lang})\n\n## Definition of Done\n- Artifact generated\n",
        encoding="utf-8",
    )
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    state = {
        "REQUEST_ID": request_id,
        "GATE": 1,
        "ITERATION": 0,
        "CREATED_AT_UTC": now,
        "UPDATED_AT_UTC": now,
        "ARTIFACTS": {},
        "HISTORY": [{"AT_UTC": now, "EVENT": "GATE0_INIT"}, {"AT_UTC": now, "EVENT": "GATE0_RESULT_PASS"}],
        "FAILURES": [],
    }
    (rd / "state.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for g in range(7):
        (rd / f"gate{g}.status").write_text("PASS" if g == 0 else "NOT_RUN", encoding="utf-8")
    (rd / "gate0.result.json").write_text(
        json.dumps({"status": "PASS", "reason_codes": [], "details": ""}, indent=2) + "\n",
        encoding="utf-8",
    )
    (rd / "replay_pins.json").write_text(
        json.dumps({"req_sha256": req_sha256}, indent=2) + "\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["DCS_REPRO"] = "1"  # v1 structured: offline; orchestrator subprocess activates guard
    env["NLC_DB_SNAPSHOT_ID"] = snapshot_id
    env["NLC_SNAPSHOT_ID"] = snapshot_id
    env["NLC_KB_SNAPSHOT_ID"] = snapshot_id
    env["NLC_POLICY_VERSION"] = "v1"
    class Args:
        json = False
        no_banner = False
        compact_banner = False
        spinner = "auto"
    args = Args()
    for n in (1, 2, 3, 4, 5, 6):
        rc, st = _run_orch_gate(args, request_id, n, [], env=env)
        if rc == ERRORS["clarify"][1]:
            _print_one_command_output(request_id, "CLARIFY", None, _create_proof_bundle(request_id) if rd.exists() else None, include_run_this=True)
            return rc
        if rc != 0 or st != "PASS":
            final_status = st if st in ("PASS", "FAIL", "CLARIFY", "BLOCKED") else "FAIL"
            _print_one_command_output(request_id, final_status, _deliverable_primary(rd) if rd.exists() else None, _create_proof_bundle(request_id) if rd.exists() else None, include_run_this=True)
            return rc if rc != 0 else 1
    artifact_path = _deliverable_primary(rd)
    final_status = "PASS" if (artifact_path and artifact_path.exists()) else "FAIL"
    _print_one_command_output(request_id, final_status, artifact_path, _create_proof_bundle(request_id), include_run_this=True)
    return 0 if final_status == "PASS" else 1


def cmd_build(args) -> int:
    """
    Build: legacy --request-id (gates 1-2) OR intake --prompt/--req/--intent (full pipeline).
    Snapshot from --snapshot-id or policy default. No implicit fallback.
    """
    req_id = _normalize_ws(getattr(args, "request_id", "") or "")
    if req_id:
        return _cmd_build_legacy(args)
    _print_banner(args)
    prompt = _normalize_ws(getattr(args, "prompt", "") or "")
    req_path = getattr(args, "req", "") or ""
    intent_arg = _normalize_ws(getattr(args, "intent", "") or "")
    lang_arg = _normalize_ws(getattr(args, "lang", "") or "")
    snapshot_arg = _normalize_ws(getattr(args, "snapshot_id", "") or "")
    no_policy_default = bool(getattr(args, "no_policy_default", False))

    has_prompt = bool(prompt)
    has_intent = bool(intent_arg)
    has_req = bool(req_path)
    if has_prompt and (has_intent or has_req):
        sys.stderr.write("DCS-E0001: --prompt is mutually exclusive with --req and --intent\n")
        return 2
    if not (has_prompt or has_intent or has_req):
        sys.stderr.write("DCS-E0001: Provide --prompt, --req, or --intent\n")
        return 2

    if has_intent and has_req:
        intent_req_obj = _resolve_intent_to_req(args, intent_arg, lang_arg, snapshot_arg)
        if intent_req_obj is None:
            return 2
        p = Path(req_path).resolve()
        if not p.exists() or p.suffix != ".json":
            sys.stderr.write("DCS-E0001: With --intent and --req both provided, --req must point to existing REQ.json\n")
            return 2
        try:
            req_obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            sys.stderr.write(f"DCS-E0001: Invalid JSON: {e}\n")
            return 2
        try:
            from verifier.schema_validate import validate_req
            validate_req(req_obj)
        except Exception as e:
            sys.stderr.write(f"DCS-E0001: {e}\n")
            return 2
        try:
            from verifier.intake_equivalence import assert_equivalent, IntakeEquivalenceError
            assert_equivalent(intent_req_obj, req_obj)
        except IntakeEquivalenceError as e:
            sys.stderr.write(f"DCS-E0001: {e}\n")
            return 2
        return _run_structured_intake(req_obj, snapshot_arg, no_policy_default)

    if has_intent:
        return _cmd_build_intent(args, intent_arg, lang_arg, snapshot_arg, no_policy_default)

    if has_req:
        p = Path(req_path).resolve()
        if not p.exists():
            sys.stderr.write(f"DCS-E4001: File not found: {p}\n")
            return 2
        if p.suffix == ".json":
            # REQ.json v1
            try:
                req_obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except json.JSONDecodeError as e:
                sys.stderr.write(f"DCS-E0001: Invalid JSON: {e}\n")
                return 2
            try:
                from verifier.schema_validate import validate_req
                validate_req(req_obj)
            except Exception as e:
                sys.stderr.write(f"DCS-E0001: {e}\n")
                return 2
            if req_obj.get("schema_version") == "req_v1" or req_obj.get("req_version") == "v1":
                return _run_structured_intake(req_obj, snapshot_arg, no_policy_default)
        if p.suffix == ".dcs":
            return _run_one_command_pipeline(p, include_run_this=True)
        sys.stderr.write("DCS-E0001: --req must point to REQ.json or .dcs file\n")
        return 2

    # --prompt: resolve snapshot, create dcs, run pipeline
    allow_default = not no_policy_default
    snapshot_id, clarify = _resolve_snapshot_id(snapshot_arg, allow_policy_default=allow_default)
    if clarify:
        sys.stdout.write(json.dumps(clarify, indent=2, sort_keys=True) + "\n")
        sys.stdout.flush()
        return ERRORS["clarify"][1]
    bundle_hash, clarify = _resolve_manifest_bundle_hash(snapshot_id)
    if clarify:
        sys.stdout.write(json.dumps(clarify, indent=2, sort_keys=True) + "\n")
        sys.stdout.flush()
        return 2
    dcs_path = _create_intake_dcs(prompt, snapshot_id, bundle_hash)
    return _run_one_command_pipeline(dcs_path, include_run_this=True)


def cmd_compile(args) -> int:
    """
    Step 17: Natural-language -> .dcs compiler (intake layer).
    Must not run gates or create request directories.
    """
    _print_banner(args)
    if isinstance(args.text, list):
        text = _normalize_ws(" ".join([str(x) for x in args.text]))
    else:
        text = _normalize_ws(str(args.text))
    out_path = Path(args.out).resolve() if args.out else (Path.cwd() / "out" / "request.dcs").resolve()
    policy_version = "v1"

    snapshot_id, clarify = _resolve_snapshot_id(getattr(args, "snapshot", "") or "")
    if clarify:
        sys.stdout.write(json.dumps(clarify, indent=2, sort_keys=True) + "\n")
        sys.stdout.flush()
        return ERRORS["clarify"][1]
    assert snapshot_id is not None

    bundle_hash, clarify = _resolve_manifest_bundle_hash(snapshot_id)
    if clarify:
        sys.stdout.write(json.dumps(clarify, indent=2, sort_keys=True) + "\n")
        sys.stdout.flush()
        return ERRORS["clarify"][1]
    assert bundle_hash is not None

    # Capability-bound classification (Step 21 hardening):
    # - choose only from capabilities.json for the pinned snapshot
    # - ambiguous/unspecified -> CLARIFY (no fallback)
    # - explicit unsupported -> FAIL UNSUPPORTED_CAPABILITY (no fallback)
    caps_path = _snapshot_root() / snapshot_id / "capabilities.json"
    if not caps_path.exists():
        sys.stdout.write(
            json.dumps(
                {
                    "reason": "MISSING_CAPABILITIES",
                    "questions": [f"Snapshot {snapshot_id} is missing capabilities.json. Build capabilities first."],
                    "candidates": [snapshot_id],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        sys.stdout.flush()
        return ERRORS["clarify"][1]
    try:
        caps = json.loads(caps_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        caps = {}
    supported_acs = caps.get("supported_artifact_classes", []) if isinstance(caps, dict) else []
    supported_langs = caps.get("languages", []) if isinstance(caps, dict) else []

    try:
        from nlc.capability_classifier import classify_request

        dec = classify_request(text, capabilities=caps if isinstance(caps, dict) else {})
    except Exception:
        dec = None

    if not dec or dec.status == "CLARIFY" or not dec.artifact_class:
        sys.stdout.write(
            json.dumps(
                {
                    "reason": getattr(dec, "reason", "MISSING_ARTIFACT_CLASS"),
                    "questions": getattr(dec, "questions", ["Specify the artifact type explicitly (e.g., include 'cli', 'api', 'gui', or 'web ui')."]),
                    "supported_artifact_classes": supported_acs if isinstance(supported_acs, list) else [],
                    "languages": supported_langs if isinstance(supported_langs, list) else [],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        sys.stdout.flush()
        return ERRORS["clarify"][1]

    if dec.status == "UNSUPPORTED":
        sys.stdout.write(
            json.dumps(
                {
                    "reason": "UNSUPPORTED_CAPABILITY",
                    "details": f"Requested artifact_class not supported: {dec.artifact_class}",
                    "supported_artifact_classes": supported_acs if isinstance(supported_acs, list) else [],
                    "languages": supported_langs if isinstance(supported_langs, list) else [],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        sys.stdout.flush()
        return 2

    artifact_class = dec.artifact_class

    obj = _compile_to_dcs_obj(text, policy_version=policy_version, snapshot_id=snapshot_id, bundle_hash=bundle_hash)
    obj["artifact_class"] = artifact_class  # fixed by classifier result
    _write_dcs_file(out_path, obj)
    sys.stdout.write(str(out_path) + "\n")
    sys.stdout.flush()
    return 0


def cmd_debug(args) -> int:
    """
    Milestone 3.1: Deterministic debug report UX (read-only).
    Must not execute any pipeline steps and must not write any files.
    """
    _print_banner(args)
    request_id = _normalize_ws(getattr(args, "request_id", "") or "")
    if not request_id:
        return _err("bad_args", "missing --request-id")
    rd = _request_dir(request_id)
    if not rd.exists():
        return _err("missing_request", f"request not found: {request_id}")

    def _rel(p: Path) -> str:
        try:
            return str(p.resolve().relative_to(BASE.resolve())).replace("\\", "/")
        except Exception:
            return str(p).replace("\\", "/")

    def _read_json(p: Path) -> Any:
        return json.loads(_read_text(p))

    def _maybe_json(p: Path) -> Any:
        if not p.exists():
            return None
        try:
            return _read_json(p)
        except Exception:
            return None

    def _maybe_text(p: Path) -> str:
        if not p.exists():
            return ""
        try:
            return _read_text(p)
        except Exception:
            return ""

    # --- gather inputs (read-only) ---
    payload = _maybe_json(rd / "payload.json")

    verifier_result = _maybe_json(rd / "verifier" / "verifier.result.json")
    verifier_failures = _maybe_json(rd / "verifier" / "failures.json")

    validation_result = _maybe_json(rd / "validation" / "result.json")

    repair_status = _maybe_json(rd / "repair" / "status.json")
    repair_iter0_failures = _maybe_json(rd / "repair" / "iter_0" / "failures.json")

    # --- failure classification ---
    kinds_verifier: List[str] = []
    if isinstance(verifier_failures, dict):
        fs = verifier_failures.get("failures", [])
        if isinstance(fs, list):
            for f in fs:
                if isinstance(f, dict) and isinstance(f.get("kind"), str):
                    kinds_verifier.append(f.get("kind"))
    kinds_verifier = sorted({k.strip() for k in kinds_verifier if k and k.strip()})

    kinds_repair0: List[str] = []
    if isinstance(repair_iter0_failures, dict):
        fs = repair_iter0_failures.get("failures", [])
        if isinstance(fs, list):
            for f in fs:
                if isinstance(f, dict) and isinstance(f.get("kind"), str):
                    kinds_repair0.append(f.get("kind"))
    kinds_repair0 = sorted({k.strip() for k in kinds_repair0 if k and k.strip()})

    # --- minimal repro commands (no inference; only recorded fields) ---
    repros: List[str] = []
    if isinstance(verifier_result, dict):
        checks = verifier_result.get("checks", [])
        if isinstance(checks, list):
            for c in checks:
                if isinstance(c, dict):
                    r = c.get("repro")
                    if isinstance(r, str) and r.strip():
                        repros.append(r.strip())
    if isinstance(verifier_failures, dict):
        fs = verifier_failures.get("failures", [])
        if isinstance(fs, list):
            for f in fs:
                if isinstance(f, dict):
                    r = f.get("repro")
                    if isinstance(r, str) and r.strip():
                        repros.append(r.strip())
    if isinstance(validation_result, dict):
        steps = validation_result.get("steps", [])
        if isinstance(steps, list):
            for s in steps:
                if isinstance(s, dict):
                    r = s.get("repro")
                    if isinstance(r, str) and r.strip():
                        repros.append(r.strip())
    repros = sorted({r for r in repros})

    # --- relevant artifact paths (state/requests/<id>/ only; stable order) ---
    paths: List[str] = []
    # Fixed top-level
    for name in (
        "REQUEST.md",
        "payload.json",
        "REQ.json",
        "INTENT_TRACE.json",
        "snapshot_resolution.json",
        "SPEC.md",
        "TASKS.json",
        "PLAN.md",
        "NEEDS.json",
        "VERIFY.md",
    ):
        p = rd / name
        if p.exists():
            paths.append(_rel(p))
    # Gate statuses
    for g in range(0, 7):
        p = rd / f"gate{g}.status"
        if p.exists():
            paths.append(_rel(p))
        rp = rd / f"gate{g}.result.json"
        if rp.exists():
            paths.append(_rel(rp))
    # Verifier
    for p in (
        rd / "verifier" / "verifier.result.json",
        rd / "verifier" / "failures.json",
        rd / "verifier.meta.json",
        rd / "verifier.prompt.txt",
        rd / "verifier.out.txt",
        rd / "verifier.stdout.txt",
        rd / "verifier.stderr.txt",
    ):
        if p.exists():
            paths.append(_rel(p))
    # Validation
    for p in (
        rd / "validation" / "result.json",
        rd / "validation" / "bundle.json",
        rd / "validation" / "py_compile.stdout.txt",
        rd / "validation" / "py_compile.stderr.txt",
        rd / "validation" / "unittest.stdout.txt",
        rd / "validation" / "unittest.stderr.txt",
    ):
        if p.exists():
            paths.append(_rel(p))
    # Repair: list iter_0..iters_run deterministically (no globbing)
    if isinstance(repair_status, dict):
        iters_run = repair_status.get("iters_run", None)
        if isinstance(iters_run, int) and iters_run >= 0:
            for i in range(0, iters_run + 1):
                idir = rd / "repair" / f"iter_{i}"
                if not idir.exists():
                    continue
                for fn in (
                    "failures.json",
                    "verifier.result.json",
                    "proposal.diff",
                    "patch_gate.json",
                    "decision.json",
                    "workspace_hashes.json",
                    "workspace_hashes.before.json",
                    "workspace_hashes.after.json",
                    "workspace_hashes.after_rollback.json",
                ):
                    p = idir / fn
                    if p.exists():
                        paths.append(_rel(p))
        sp = rd / "repair" / "status.json"
        if sp.exists():
            paths.append(_rel(sp))

    paths = sorted({p for p in paths})

    # --- stable output ---
    lines: List[str] = []
    lines.append("DCS DEBUG REPORT")
    lines.append(f"request_id: {request_id}")
    if isinstance(payload, dict):
        lines.append(f"artifact_class: {str(payload.get('artifact_class','')).strip()}")
        lines.append(f"policy_version: {str(payload.get('policy_version','')).strip()}")
        lines.append(f"knowledge_snapshot_id: {str(payload.get('knowledge_snapshot_id','')).strip()}")
        lines.append(f"manifest_bundle_hash: {str(payload.get('manifest_bundle_hash','')).strip()}")
    lines.append("")

    lines.append("FAILURE_CLASSIFICATION")
    lines.append("verifier_failure_kinds: " + json.dumps(kinds_verifier, sort_keys=True))
    lines.append("repair_iter0_failure_kinds: " + json.dumps(kinds_repair0, sort_keys=True))
    if isinstance(repair_status, dict):
        lines.append(f"repair_final_status: {str(repair_status.get('final_status','')).strip()}")
        lines.append(f"repair_stop_reason: {str(repair_status.get('stop_reason','')).strip()}")
        lines.append(f"repair_stop_reason_short: {str(repair_status.get('stop_reason_short','')).strip()}")
    lines.append("")

    lines.append("MIN_REPRO")
    for r in repros:
        lines.append(f"- {r}")
    lines.append("")

    lines.append("ARTIFACT_PATHS")
    for p in paths:
        # Only paths under state/requests/<id>/ should appear; enforce defensively.
        if not p.startswith(f"state/requests/{request_id}/"):
            continue
        lines.append(f"- {p}")

    sys.stdout.write("\n".join(lines).rstrip("\n") + "\n")
    sys.stdout.flush()
    return 0


def cmd_capabilities(args) -> int:
    _print_banner(args)
    try:
        from policy import get_default_snapshot_id
        snapshot_id = (os.environ.get("NLC_DB_SNAPSHOT_ID") or os.environ.get("DCS_PROOF_SNAPSHOT_ID") or get_default_snapshot_id() or "").strip()
    except ImportError:
        snapshot_id = (os.environ.get("NLC_DB_SNAPSHOT_ID") or os.environ.get("DCS_PROOF_SNAPSHOT_ID") or "").strip()
    if not snapshot_id:
        return _err("bad_args", "MISSING_SNAPSHOT_ID: set NLC_DB_SNAPSHOT_ID or DCS_PROOF_SNAPSHOT_ID")
    caps_path = _snapshot_root() / snapshot_id / "capabilities.json"
    if not caps_path.exists():
        return _err("bad_args", f"capabilities.json missing for snapshot {snapshot_id}")
    try:
        caps = json.loads(caps_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return _err("bad_args", "capabilities.json invalid JSON")
    intents_path = _snapshot_root() / snapshot_id / "manifest" / "intents.json"
    mined_path = _snapshot_root() / snapshot_id / "manifest" / "intents_mined.json"
    intents_map = {}
    if intents_path.exists():
        try:
            obj = json.loads(intents_path.read_text(encoding="utf-8", errors="replace"))
            for it in obj.get("intents", []) if isinstance(obj, dict) else []:
                if isinstance(it, dict) and it.get("intent_id"):
                    intents_map[it["intent_id"]] = it.get("name", it["intent_id"])
        except Exception:
            intents_map = {}
    if mined_path.exists():
        try:
            obj = json.loads(mined_path.read_text(encoding="utf-8", errors="replace"))
            for it in obj.get("intents", []) if isinstance(obj, dict) else []:
                if isinstance(it, dict) and it.get("intent_id"):
                    intents_map.setdefault(it["intent_id"], it.get("name", it["intent_id"]))
        except Exception:
            pass
    languages = caps.get("languages", [])
    reachable_intents = caps.get("reachable_intents_from_text", [])
    truth_backed = caps.get("truth_backed_artifact_classes", [])
    mined_total = caps.get("mined_intents_total", 0)
    mined_active = caps.get("mined_intents_active", 0)
    sys.stdout.write("DCS CAPABILITIES\n")
    sys.stdout.write(f"snapshot_id: {snapshot_id}\n")
    sys.stdout.write(f"languages: {', '.join(languages)}\n")
    sys.stdout.write(f"mined_intents_total: {mined_total}\n")
    sys.stdout.write(f"mined_intents_active: {mined_active}\n")
    sys.stdout.write("reachable_intents:\n")
    for iid in reachable_intents:
        name = intents_map.get(iid, iid)
        sys.stdout.write(f"- {iid}: {name}\n")
    sys.stdout.write(f"truth_backed_artifact_classes: {', '.join(truth_backed)}\n")
    sys.stdout.write("run: dcs\n")
    sys.stdout.flush()
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="dcs")
    ap.add_argument("--json", action="store_true", help="JSON output (no banner/effects)")
    # Back-compat flag name: --no-banner now means "compact banner mode" (banner still appears in TTY).
    ap.add_argument("--no-banner", action="store_true", help="Use compact banner (TTY only)")
    ap.add_argument("--compact-banner", dest="compact_banner", action="store_true", help="Use compact banner (TTY only)")
    ap.add_argument("--no-color", action="store_true", help="Disable color/effects")
    ap.add_argument("--spinner", default="auto", choices=["auto", "on", "off"], help="Spinner mode")
    ap.add_argument("--version", action="store_true", help="Show version and exit")

    sub = ap.add_subparsers(dest="cmd")

    p_init = sub.add_parser("init")
    p_init.add_argument("--request-id", required=True)
    p_init.add_argument("--objective", required=True)
    p_init.add_argument("--constraints", nargs="*", default=[])
    p_init.add_argument("--non-goals", nargs="*", default=[])
    p_init.add_argument("--dod", nargs="*", default=[])
    p_init.set_defaults(func=cmd_init)

    # build: legacy --request-id (gates 1-2) OR intake --prompt/--req

    p_run = sub.add_parser("run")
    # Supports either:
    # - dcs run examples/hello_world.dcs
    # - dcs run --request-id <id>
    p_run.add_argument("spec_path", nargs="?", default=None)
    p_run.add_argument("--request-id", required=False, default="")
    p_run.add_argument("--interactive", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_start = sub.add_parser("start")
    p_start.add_argument("spec_path", nargs="?", default=None)
    p_start.add_argument("--request-id", required=False, default="")
    p_start.add_argument("--interactive", action="store_true")
    p_start.set_defaults(func=cmd_run)

    p_verify = sub.add_parser("verify")
    p_verify.add_argument("--request-id", required=True)
    p_verify.add_argument("--gate-name", required=True)
    p_verify.set_defaults(func=cmd_verify)

    p_repair = sub.add_parser("repair")
    p_repair.add_argument("--request-id", required=True)
    p_repair.add_argument("--gate-name", required=True)
    p_repair.set_defaults(func=cmd_repair)

    p_replay = sub.add_parser("replay")
    p_replay.add_argument("--request-id", required=False)
    p_replay.add_argument("--gate-name", required=False)
    p_replay.add_argument("request_id_pos", nargs="?")
    p_replay.add_argument("gate_name_pos", nargs="?")
    p_replay.set_defaults(func=cmd_replay)

    p_user_verify = sub.add_parser("user-verify")
    p_user_verify.add_argument("--request-id", required=True)
    p_user_verify.set_defaults(func=cmd_user_verify)

    p_inspect = sub.add_parser("inspect")
    ins_sub = p_inspect.add_subparsers(dest="inspect_cmd")
    p_last = ins_sub.add_parser("last")
    p_last.set_defaults(func=cmd_inspect)
    p_cat = ins_sub.add_parser("cat")
    p_cat.add_argument("--path", required=True)
    p_cat.set_defaults(func=cmd_inspect)

    p_doctor = sub.add_parser("doctor")
    p_doctor.set_defaults(func=cmd_doctor)

    p_compile = sub.add_parser("compile")
    # Accept unquoted multi-word text: `dcs compile make a cli ...`
    p_compile.add_argument("text", nargs="+", help="Natural-language request text")
    p_compile.add_argument("--out", default=str(Path("out") / "request.dcs"))
    p_compile.add_argument("--snapshot", default="", help="Optional snapshot id override (deterministic)")
    p_compile.set_defaults(func=cmd_compile)

    p_build = sub.add_parser("build")
    p_build.add_argument("--request-id", default="", help="Legacy: run gates 1-2 on existing request")
    p_build.add_argument("--prompt", default="", help="Intake: natural-language request")
    p_build.add_argument("--req", default="", help="Intake: path to REQ.json or .dcs file")
    p_build.add_argument("--intent", default="", help="Structured intake: intent_id (e.g. print_sequence)")
    p_build.add_argument("--lang", default="", help="Structured intake: language (e.g. python)")
    p_build.add_argument("--from", dest="param_from", type=int, default=None, help="print_sequence: start value")
    p_build.add_argument("--to", dest="param_to", type=int, default=None, help="print_sequence: end value")
    p_build.add_argument("--step", type=int, default=None, help="print_sequence: step (default 1)")
    p_build.add_argument("--snapshot-id", default="", help="Snapshot id (for --prompt/--req/--intent)")
    p_build.add_argument("--no-policy-default", action="store_true", help="Disable policy default (test SNAPSHOT_ID_REQUIRED)")
    p_build.set_defaults(func=cmd_build)

    p_debug = sub.add_parser("debug")
    p_debug.add_argument("--request-id", required=True)
    p_debug.set_defaults(func=cmd_debug)

    p_caps = sub.add_parser("capabilities")
    p_caps.set_defaults(func=cmd_capabilities)

    return ap


# Milestone 5.5: One-command UX functions

def _read_prompt_from_stdin() -> str:
    """Read prompt from stdin until EOF. No timestamps. No randomness."""
    try:
        if sys.stdin.isatty() and sys.stdout.isatty():
            sys.stdout.write("Enter prompt:")
            sys.stdout.flush()
    except Exception:
        pass
    try:
        if sys.stdin.isatty():
            line = sys.stdin.readline()
            return (line or "").strip()
    except Exception:
        pass
    lines = []
    try:
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            lines.append(line)
    except EOFError:
        pass
    return "".join(lines).strip()


def _clamp_stdin() -> None:
    try:
        sys.stdin = open(os.devnull, "r", encoding="utf-8", errors="replace")
    except Exception:
        pass


def _create_intake_dcs(prompt_text: str, snapshot_id: str, bundle_hash: str) -> Path:
    """
    Create .dcs file deterministically under state/intake/prompt_<sha256>.dcs.
    Requires snapshot_id and bundle_hash; no fallbacks. Caller must resolve first.
    Returns the path to the created .dcs file.
    """
    if not snapshot_id or not str(snapshot_id).strip():
        raise ValueError("snapshot_id is required (no fallback)")
    if not bundle_hash or not str(bundle_hash).strip():
        raise ValueError("manifest_bundle_hash is required (no empty hash fallback)")

    prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    intake_dir = BASE / "state" / "intake"
    intake_dir.mkdir(parents=True, exist_ok=True)
    dcs_path = intake_dir / f"prompt_{prompt_hash}.dcs"

    policy_version = "v1"
    caps_path = _snapshot_root() / snapshot_id / "capabilities.json"
    caps = {}
    if caps_path.exists():
        try:
            caps = json.loads(caps_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass

    try:
        from nlc.capability_classifier import classify_request
        dec = classify_request(prompt_text, capabilities=caps if isinstance(caps, dict) else {})
    except Exception:
        dec = None

    artifact_class = "python_cli"
    if dec and dec.artifact_class:
        artifact_class = dec.artifact_class

    obj = _compile_to_dcs_obj(prompt_text, policy_version=policy_version, snapshot_id=snapshot_id, bundle_hash=bundle_hash)
    obj["artifact_class"] = artifact_class
    _write_dcs_file(dcs_path, obj)

    return dcs_path


def _create_proof_bundle(request_id: str) -> Optional[Path]:
    """
    Create proof bundle zip under state/requests/<id>/dist/proof_bundle.zip.
    Deterministic: sorted file list, fixed timestamp (1980-01-01), fixed mode, no machine-specific files.
    Returns path to proof bundle, or None if creation failed.
    """
    rd = _request_dir(request_id)
    if not rd.exists():
        return None

    dist_dir = rd / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    proof_bundle_path = dist_dir / "proof_bundle.zip"

    # Exclude machine-specific / noisy paths
    _EXCLUDE_PARTS = frozenset({
        "__pycache__", ".pyc", ".pyo", ".pycache", ".git", ".svn", ".hg",
        ".DS_Store", "Thumbs.db", ".tmp", ".temp", ".log", ".cache",
    })

    def _should_include(path: Path, arcname: str) -> bool:
        for part in path.parts:
            if part in _EXCLUDE_PARTS:
                return False
        if arcname.endswith((".pyc", ".pyo", ".log", ".tmp", ".temp")):
            return False
        return True

    fixed_dt = (1980, 1, 1, 0, 0, 0)

    def _make_zipinfo(arcname: str, data: bytes) -> zipfile.ZipInfo:
        zi = zipfile.ZipInfo(arcname)
        zi.date_time = fixed_dt
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.external_attr = (0o644 & 0xFFFF) << 16
        return zi

    # 1) Collect (arcname, bytes) for all files
    entries: list[tuple[str, bytes]] = []

    for arcname, src in [
        ("dist/artifact.zip", dist_dir / "artifact.zip"),
        ("dist/checksums.sha256", dist_dir / "checksums.sha256"),
        ("dist/ENTRYPOINT.md", dist_dir / "ENTRYPOINT.md"),
        ("dist/EXECUTE.json", dist_dir / "EXECUTE.json"),
    ]:
        if src.exists():
            data = src.read_bytes() if arcname != "dist/ENTRYPOINT.md" else src.read_text(encoding="utf-8").encode("utf-8")
            entries.append((arcname, data))

    for subdir in ("verifier", "validation", "repair", "replay"):
        subpath = rd / subdir
        if subpath.exists():
            for f in sorted(subpath.rglob("*"), key=lambda p: str(p).replace("\\", "/")):
                if f.is_file():
                    rel = str(f.relative_to(rd)).replace("\\", "/")
                    if _should_include(f, rel):
                        entries.append((rel, f.read_bytes()))

    # 2) Sort by arcname (lexicographic)
    entries.sort(key=lambda x: x[0])

    # 3) Build PROOF.md content from collected entries
    proof_lines = ["# PROOF Bundle\n\n", "## Included Files\n\n"]
    for arcname, data in entries:
        h = hashlib.sha256(data).hexdigest()
        proof_lines.append(f"- {arcname} (sha256: {h})\n")
    proof_bytes = "".join(proof_lines).encode("utf-8")
    entries.append(("PROOF.md", proof_bytes))
    entries.sort(key=lambda x: x[0])

    # 4) Single write pass: all entries in sorted order
    with zipfile.ZipFile(proof_bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arcname, data in entries:
            zi = _make_zipinfo(arcname, data)
            zf.writestr(zi, data)

    return proof_bundle_path


def _format_run_this(request_id: str, artifact_path: Path, execute_contract: dict) -> str:
    out_root = BASE / "out" / "user_run" / request_id
    cwd_rel = str(execute_contract.get("cwd_rel", ".")).strip() or "."
    entry_cmd = execute_contract.get("entry_command", [])
    import shlex
    unzip_cmd = f"python3 -m zipfile -e {shlex.quote(str(artifact_path))} {shlex.quote(str(out_root))}"
    run_dir = str(out_root / cwd_rel)
    run_cmd = " ".join([shlex.quote(str(x)) for x in entry_cmd])
    return f"{unzip_cmd} && (cd {shlex.quote(run_dir)} && {run_cmd})"


def _print_one_command_output(request_id: str, status: str, artifact_path: Optional[Path], proof_bundle_path: Optional[Path], include_run_this: bool = False) -> None:
    """Print request_id, status, artifact, proof_bundle, and optional RUN THIS line."""
    sys.stdout.write(f"request_id: {request_id}\n")
    sys.stdout.write(f"status: {status}\n")
    if artifact_path and artifact_path.exists():
        rel_path = artifact_path.relative_to(BASE)
        sys.stdout.write(f"artifact: {str(rel_path).replace(chr(92), '/')}\n")
    else:
        sys.stdout.write("artifact: NONE\n")
    if proof_bundle_path and proof_bundle_path.exists():
        rel_path = proof_bundle_path.relative_to(BASE)
        sys.stdout.write(f"proof_bundle: {str(rel_path).replace(chr(92), '/')}\n")
    else:
        sys.stdout.write("proof_bundle: NONE\n")
    if include_run_this:
        if artifact_path and (artifact_path.parent / "EXECUTE.json").exists():
            try:
                execute_contract = json.loads((artifact_path.parent / "EXECUTE.json").read_text(encoding="utf-8", errors="replace"))
                run_line = _format_run_this(request_id, artifact_path, execute_contract)
                sys.stdout.write(f"RUN THIS: {run_line}\n")
            except Exception:
                sys.stdout.write("RUN THIS: NONE\n")
        else:
            sys.stdout.write("RUN THIS: NONE\n")
    sys.stdout.flush()


def _run_one_command_pipeline(dcs_path: Path, include_run_this: bool = False) -> int:
    """
    Run the full pipeline on a .dcs file and return exit code.
    Creates proof bundle and prints 4-line output.
    """
    # Parse .dcs file
    try:
        spec = _parse_dcs_file(dcs_path)
    except Exception as e:
        sys.stderr.write(f"Error parsing .dcs file: {e}\n")
        return 2
    
    request_id = str(spec.get("request_id") or _derive_request_id_from_path(dcs_path)).strip()
    objective = str(spec.get("goal") or spec.get("objective", "")).strip()
    constraints = spec.get("constraints", [])
    non_goals = spec.get("non_goals", [])
    dod = spec.get("dod", [])
    policy_version = str(spec.get("policy_version", "v1")).strip() or "v1"
    snapshot_id = str(spec.get("knowledge_snapshot_id", "")).strip()
    bundle_hash = str(spec.get("manifest_bundle_hash", "")).strip()
    
    # Configure env
    env = os.environ.copy()
    env["NLC_POLICY_VERSION"] = policy_version
    if snapshot_id:
        env["NLC_DB_SNAPSHOT_ID"] = snapshot_id
        env["NLC_SNAPSHOT_ID"] = snapshot_id
        env["NLC_KB_SNAPSHOT_ID"] = snapshot_id
    
    # Remove existing request dir for deterministic reruns
    rd = _request_dir(request_id)
    if rd.exists():
        shutil.rmtree(rd, ignore_errors=True)
    
    # Create minimal args object for _run_orch_gate
    class Args:
        json = False
        no_banner = False
        compact_banner = False
        spinner = "auto"
    
    args = Args()
    
    # Run gates 0-6
    statuses: Dict[int, str] = {}
    final_status = "FAIL"
    
    attempts = 0
    while True:
        rc, st = _run_orch_gate(
            args,
            request_id,
            0,
            [json.dumps(objective), json.dumps(constraints or []), json.dumps(non_goals or []), json.dumps(dod or [])],
            env=env,
        )
        statuses[0] = st
        if rc == ERRORS["clarify"][1]:
            final_status = "CLARIFY"
            artifact_path = None
            proof_bundle_path = _create_proof_bundle(request_id) if rd.exists() else None
            _print_one_command_output(request_id, final_status, artifact_path, proof_bundle_path, include_run_this=include_run_this)
            return rc
        if rc != 0 or st != "PASS":
            final_status = st if st in ("PASS", "FAIL", "CLARIFY", "BLOCKED") else "FAIL"
            artifact_path = _deliverable_primary(rd) if rd.exists() else None
            proof_bundle_path = _create_proof_bundle(request_id) if rd.exists() else None
            _print_one_command_output(request_id, final_status, artifact_path, proof_bundle_path, include_run_this=include_run_this)
            return rc if rc != 0 else 1
        break
    
    for n in (1, 2, 3, 4, 5, 6):
        attempts = 0
        while True:
            rc, st = _run_orch_gate(args, request_id, n, [], env=env)
            statuses[n] = st
            if rc == ERRORS["clarify"][1]:
                final_status = "CLARIFY"
                artifact_path = None
                proof_bundle_path = _create_proof_bundle(request_id) if rd.exists() else None
                _print_one_command_output(request_id, final_status, artifact_path, proof_bundle_path, include_run_this=include_run_this)
                return rc
            if rc == ERRORS["clarify"][1]:
                final_status = "CLARIFY"
                artifact_path = None
                proof_bundle_path = _create_proof_bundle(request_id) if rd.exists() else None
                _print_one_command_output(request_id, final_status, artifact_path, proof_bundle_path, include_run_this=include_run_this)
                return rc
            if rc != 0 or st != "PASS":
                final_status = st if st in ("PASS", "FAIL", "CLARIFY", "BLOCKED") else "FAIL"
                artifact_path = _deliverable_primary(rd) if rd.exists() else None
                proof_bundle_path = _create_proof_bundle(request_id) if rd.exists() else None
                _print_one_command_output(request_id, final_status, artifact_path, proof_bundle_path, include_run_this=include_run_this)
                return rc if rc != 0 else 1
            break
    
    # Gate 7: deliver (check if artifact exists)
    label = dict(GATE_TABLE).get(7, "deliver")
    with ux.GateProgress(_ux_mode(args), label):
        pass
    artifact_path = _deliverable_primary(rd)
    if artifact_path and artifact_path.exists():
        final_status = "PASS"
    else:
        final_status = "FAIL"
    
    # Create proof bundle
    proof_bundle_path = _create_proof_bundle(request_id)
    
    # Print 4-line output
    _print_one_command_output(request_id, final_status, artifact_path, proof_bundle_path, include_run_this=include_run_this)
    
    return 0 if final_status == "PASS" else 1


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Milestone 5.5: If invoked as `dcs` with no args: read stdin, create .dcs, run pipeline
    if len(argv) == 0:
        class Args:
            json = False
            no_banner = False
            compact_banner = False
            spinner = "auto"

        _print_banner(Args())
        prompt_text = _read_prompt_from_stdin()
        if not prompt_text:
            sys.stderr.write("Error: empty prompt\n")
            return 2
        _clamp_stdin()
        # Resolve snapshot (policy default allowed when no explicit --snapshot-id)
        snapshot_id, clarify = _resolve_snapshot_id("", allow_policy_default=True)
        if clarify:
            sys.stdout.write(json.dumps(clarify, indent=2, sort_keys=True) + "\n")
            sys.stdout.flush()
            return ERRORS["clarify"][1]
        bundle_hash, clarify = _resolve_manifest_bundle_hash(snapshot_id)
        if clarify:
            sys.stdout.write(json.dumps(clarify, indent=2, sort_keys=True) + "\n")
            sys.stdout.flush()
            return 2  # FAIL (MANIFEST_BUNDLE_HASH_MISSING - not user-fixable by CLARIFY)
        dcs_path = _create_intake_dcs(prompt_text, snapshot_id, bundle_hash)
        return _run_one_command_pipeline(dcs_path, include_run_this=True)
    
    # Milestone 5.5: If first arg is a .dcs file: run pipeline on it (check before argparse)
    if len(argv) >= 1:
        potential_dcs = Path(argv[0]).resolve()
        if potential_dcs.exists() and potential_dcs.suffix == ".dcs":
            return _run_one_command_pipeline(potential_dcs, include_run_this=False)

    ap = build_parser()
    # Ensure banner appears for `dcs --help` on TTY (argparse exits before subcommand handlers run).
    if any(a in ("-h", "--help") for a in argv):
        # Lightweight clamp evaluation without argparse parsing full args.
        if _isatty() and (not _is_replay()) and ("--json" not in argv):
            cols = shutil.get_terminal_size(fallback=(80, 24)).columns
            compact = ("--no-banner" in argv) or ("--compact-banner" in argv) or (cols < 80)
            sys.stdout.write(COMPACT_BANNER if compact else BANNER)
            sys.stdout.flush()
        try:
            ap.parse_args(argv)
        except SystemExit as e:
            return int(e.code or 0)
        return 0

    args = ap.parse_args(argv)

    if getattr(args, "version", False):
        # Banner must appear in `dcs --version` (TTY only; replay/json suppressed).
        if _isatty() and (not _is_replay()) and (not getattr(args, "json", False)):
            cols = shutil.get_terminal_size(fallback=(80, 24)).columns
            compact = bool(getattr(args, "compact_banner", False) or getattr(args, "no_banner", False) or cols < 80)
            sys.stdout.write(COMPACT_BANNER if compact else BANNER)
            sys.stdout.flush()
        sys.stdout.write("dcs 1.0\n")
        sys.stdout.flush()
        return 0

    # Subcommands required by spec but not implemented here should error deterministically.
    if not getattr(args, "cmd", ""):
        return _err("bad_args", "missing command")
    if not hasattr(args, "func"):
        return _err("bad_args", f"unimplemented command: {args.cmd}")
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())


