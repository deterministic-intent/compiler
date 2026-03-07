#!/usr/bin/env python3
"""
Generate Golden Suite v1 from DB-derived capabilities and language_artifact_matrix.
Iterates over (language, artifact_class) pairs from the matrix; emits REQs via normal pipeline.
No env overrides; no bypass. Unroutable languages produce BLOCK report.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
from scripts._repo_guard import require_repo_root
require_repo_root()

SUITE_ROOT = BASE / "suites" / "golden" / "v1" / "requests"
REQS_ROOT = BASE / "state" / "requests"
SNAPSHOT_ID = "20260215T120000Z"
CAPS_PATH = BASE / "nlc" / "db" / "snapshots" / SNAPSHOT_ID / "capabilities.json"

# 19×1 canonical: language -> primary artifact_class (when matrix has multiple)
_PRIMARY_AC: dict[str, str] = {
    "python": "python_cli",  # python_api, python_debug_script, python_gui also exist
}

# artifact_class -> module_ref (project_v1.json per v1 expansion)
def _module_ref(ac: str, lang: str) -> str | None:
    _MAP = {
        "bash_cli": "bash_cli/project_v1.json",
        "c_cli": "c_cli/project_v1.json",
        "cpp_cli": "cpp_cli/project_v1.json",
        "csharp_cli": "csharp_cli/project_v1.json",
        "docker_image": "docker_image/project_v1.json",
        "go_cli": "go_cli/project_v1.json",
        "html_site": "html_site/project_v1.json",
        "java_cli": "java_cli/project_v1.json",
        "javascript_web": "javascript_web/project_v1.json",
        "kotlin_cli": "kotlin_cli/project_v1.json",
        "mongodb_pack": "mongodb_pack/project_v1.json",
        "php_cli": "php_cli/project_v1.json",
        "python_cli": "python_cli/project_v1.json",
        "python_api": "python_cli/project_v1.json",
        "python_gui": "python_cli/project_v1.json",
        "python_debug_script": "python_debug_script/debug_runner.json",
        "ruby_cli": "ruby_cli/project_v1.json",
        "rust_cli": "rust_cli/project_v1.json",
        "solidity_contract": "solidity_contract/project_v1.json",
        "sql_pack": "sql_pack/project_v1.json",
        "typescript_cli": "typescript_cli/project_v1.json",
        "yaml_config": "yaml_config/project_v1.json",
    }
    return _MAP.get(ac)

# Minimal fixture for python_debug_script (REQ schema requires files+entrypoint in embedded JSON)
PYTHON_DEBUG_SCRIPT_FIXTURE: dict = {
    "files": {"main.py": "#!/usr/bin/env python3\n\"\"\"Minimal Python debug script for Golden Suite v1.\"\"\"\nprint('hello')"},
    "entrypoint": "main.py",
}


def _run(cmd: list[str], env: dict | None = None, cwd: Path | None = None) -> int:
    e = os.environ.copy()
    if env:
        e.update(env)
    r = subprocess.run(cmd, cwd=str(cwd or BASE), env=e, capture_output=True, text=True, timeout=300)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def _run_dcs(request_id: str, objective: str, ac: str, mod_ref: str, language: str, extra: dict | None = None) -> int:
    block: dict = {
        "artifact_class": ac,
        "language": language,
        "module_refs": [mod_ref],
    }
    if extra:
        block.update(extra)
    json_block = json.dumps(block, indent=2)
    full_objective = objective.strip() + "\n\n```json\n" + json_block + "\n```\n"
    env = {
        "NLC_DB_SNAPSHOT_ID": SNAPSHOT_ID,
        "NLC_SNAPSHOT_ID": SNAPSHOT_ID,
    }
    orch = BASE / "orchestrator" / "orchestrator.py"
    rd = REQS_ROOT / request_id
    if rd.exists():
        shutil.rmtree(rd)
    rc = _run(
        [sys.executable, str(orch), "gate0_init", request_id, json.dumps(full_objective), "[]", "[]", "[]"],
        env=env,
    )
    if rc != 0:
        return rc
    for cmd in ["gate1_planning", "gate2_delegation", "gate3_execution", "gate4_review", "gate5_finalize", "gate6_complete"]:
        rc = _run([sys.executable, str(orch), cmd, request_id], env=env)
        if rc != 0:
            return rc
    return 0


def _has_artifacts(rd: Path) -> bool:
    if not (rd / "payload.json").exists():
        return False
    if not ((rd / "dist" / "artifact.zip").exists() or (rd / "dist" / "site.zip").exists()):
        return False
    proof = rd / "dist" / "proof_bundle.zip"
    if not proof.exists():
        try:
            if str(BASE) not in sys.path:
                sys.path.insert(0, str(BASE))
            from dcs_cli.main import _create_proof_bundle
            _create_proof_bundle(rd.name)
        except Exception:
            pass
    return proof.exists()


def main() -> int:
    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))

    from nlc.snapshot_authority import get_v1_languages_from_snapshot

    try:
        langs = get_v1_languages_from_snapshot(SNAPSHOT_ID)
    except (FileNotFoundError, ValueError) as e:
        sys.stderr.write(f"FAIL: {e}\n")
        return 2

    if not CAPS_PATH.exists():
        sys.stderr.write(f"FAIL: capabilities not found: {CAPS_PATH}\n")
        return 2

    caps = json.loads(CAPS_PATH.read_text(encoding="utf-8"))
    matrix = caps.get("language_artifact_matrix", {})

    # Snapshot language inventory is authority (no scope shrink).
    routable_langs = [lang for lang in langs if matrix.get(lang)]
    if len(routable_langs) < 19:
        sys.stderr.write(f"BLOCK: need 19 routable languages, got {len(routable_langs)}: {sorted(routable_langs)}\n")
        return 2

    SUITE_ROOT.mkdir(parents=True, exist_ok=True)
    failed: list[tuple[str, str]] = []
    generated = 0

    # 19×1 binding: exactly one artifact_class per language (primary from matrix)
    for lang in sorted(routable_langs):
        classes = matrix.get(lang) or []
        ac = _PRIMARY_AC.get(lang) or (sorted(classes)[0] if classes else None)
        if not ac or ac not in classes:
            continue
        mod_ref = _module_ref(ac, lang)
        if not mod_ref or not (BASE / "orchestrator" / "modules" / mod_ref).exists():
            failed.append((lang, ac))
            continue
        request_id = f"LANG_{lang}__{ac}"
        objective = f"Generate minimal {lang} {ac} project for Golden Suite v1."
        extra = PYTHON_DEBUG_SCRIPT_FIXTURE if ac == "python_debug_script" else None
        rc = _run_dcs(request_id, objective, ac, mod_ref, lang, extra)
        rd = REQS_ROOT / request_id
        if rc != 0 or not _has_artifacts(rd):
            failed.append((lang, ac))
            continue
        dest = SUITE_ROOT / request_id
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(rd, dest)
        generated += 1

    # Negative cases (run create_neg_dirs.py separately if LANG generation skipped)
    neg_script = BASE / "scripts" / "create_neg_dirs.py"
    if neg_script.exists():
        subprocess.run([sys.executable, str(neg_script)], cwd=str(BASE), check=True)

    if failed:
        sys.stderr.write(f"FAIL: (lang, ac) pairs failed: {failed}\n")
        req_ids = [f"LANG_{lang}__{ac}" for lang, ac in failed]
        capture_script = BASE / "scripts" / "capture_gate1_failures_v1.py"
        if capture_script.exists():
            subprocess.run(
                [sys.executable, str(capture_script), "--request-ids"] + req_ids,
                cwd=str(BASE),
                capture_output=True,
            )
        return 2
    print(f"generate_golden_suite_v1: OK ({generated} REQs + negatives)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
