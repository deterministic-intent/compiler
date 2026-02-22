#!/usr/bin/env python3
"""
Deterministic planner (NO model calls).

Produces:
- SPEC.md
- TASKS.json
- PLAN.md
- NEEDS.json (always empty for deterministic mode)

This replaces the previous planner runner and keeps the orchestrator gate contract
without any model-based generation.
"""

import sys
import json
import importlib.util
import hashlib
from pathlib import Path

# Ensure repository root is on sys.path when run as a script.
BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def die(msg: str, code: int = 2):
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def write_text(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")


def extract_objective_from_request_md(request_md: str) -> str:
    # Deterministic: first non-empty line under "## Objective"
    lines = request_md.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    in_obj = False
    for ln in lines:
        t = ln.strip()
        if t.startswith("## ") and t.lower() == "## objective":
            in_obj = True
            continue
        if in_obj:
            if t.startswith("## "):
                break
            if t:
                return t
    return ""


def main():
    if len(sys.argv) != 3:
        die("Usage: run_planner.py <REQUEST_ID> <REQUEST_DIR>")

    request_id = sys.argv[1].strip()
    request_dir = Path(sys.argv[2]).resolve()
    if not request_id:
        die("REQUEST_ID empty")
    if not request_dir.exists():
        die(f"REQUEST_DIR not found: {request_dir}")

    # Repo root
    base = Path(__file__).resolve().parents[1]

    req_md_path = request_dir / "REQUEST.md"
    if not req_md_path.exists():
        die("REQUEST.md missing")
    request_md = read_text(req_md_path)
    objective = extract_objective_from_request_md(request_md)
    if not objective:
        die("Could not extract objective from REQUEST.md")

    # Step 3: Check for clarification mode - planner must halt deterministically
    clarify_path = request_dir / "CLARIFY.json"
    if clarify_path.exists():
        try:
            clarify_obj = json.loads(read_text(clarify_path))
            print(f"CLARIFICATION_NEEDED: {clarify_obj.get('reason', 'UNKNOWN')}", file=sys.stderr)
            print(f"Questions: {clarify_obj.get('questions', [])}", file=sys.stderr)
            # Planner halts - do not generate plans
            die("Clarification required. See CLARIFY.json for details.", 1)
        except Exception as e:
            die(f"CLARIFY.json invalid JSON: {e}", 1)
    
    # If python_debug_script, generate deterministic plan artifacts without intent compilation
    payload_path = request_dir / "payload.json"
    artifact_class = ""
    if payload_path.exists():
        try:
            payload = json.loads(read_text(payload_path))
            artifact_class = str(payload.get("artifact_class", "")).strip()
        except Exception:
            artifact_class = ""
    if artifact_class == "python_debug_script":
        spec_text = "\n".join([
            "# SPEC",
            "",
            "## Objective",
            objective,
            "",
            "## Constraints",
            "- Deterministic debug execution",
            "- Evidence-anchored report",
            "",
            "## Non-goals",
            "- No code generation",
            "",
            "## Definition of Done",
            "- Debug report and repro artifacts are produced",
        ]) + "\n"
        tasks_obj = {
            "tasks": [
                {
                    "id": "T1",
                    "type": "other",
                    "owner": "PLANNER (deterministic)",
                    "acceptance": [
                        "debug/repro/steps.json exists",
                        "debug/report.md exists",
                        "debug/report.json exists",
                    ],
                    "touches": ["debug/"],
                    "blocking": True,
                }
            ]
        }
        plan_text = "\n".join([
            "# PLAN",
            "",
            "1. Run deterministic debug runner",
            "2. Produce evidence-anchored report",
            "3. Optional repair loop if enabled",
        ]) + "\n"
        write_text(request_dir / "SPEC.md", spec_text)
        write_text(request_dir / "TASKS.json", json.dumps(tasks_obj, indent=2, sort_keys=True) + "\n")
        write_text(request_dir / "PLAN.md", plan_text)
        write_text(request_dir / "NEEDS.json", json.dumps({"needs": []}, indent=2, sort_keys=True) + "\n")
        print("OK")
        return

    # Load deterministic prompt compiler and intent→tasks
    pc_spec = importlib.util.spec_from_file_location("prompt_compiler", base / "nlc" / "prompt_compiler.py")
    prompt_compiler = importlib.util.module_from_spec(pc_spec)
    pc_spec.loader.exec_module(prompt_compiler)

    it_spec = importlib.util.spec_from_file_location("intent_to_tasks", base / "nlc" / "intent_to_tasks.py")
    intent_to_tasks = importlib.util.module_from_spec(it_spec)
    it_spec.loader.exec_module(intent_to_tasks)

    # Ensure REQ.json exists (compile deterministically from objective if missing)
    req_path = request_dir / "REQ.json"
    if req_path.exists():
        try:
            req_obj = json.loads(read_text(req_path))
        except Exception as e:
            die(f"REQ.json invalid JSON: {e}")
    else:
        # Load metadata from payload.json if available
        payload_path = request_dir / "payload.json"
        metadata = {}
        if payload_path.exists():
            try:
                metadata = json.loads(read_text(payload_path))
            except Exception:
                pass
        
        ok, req_obj, err = prompt_compiler.compile_with_fallback(
            objective, 
            request_dir,
            request_id=request_id,
            policy_version=metadata.get("policy_version"),
            knowledge_snapshot_id=metadata.get("knowledge_snapshot_id"),
            manifest_bundle_hash=metadata.get("manifest_bundle_hash"),
            manifest_hashes=metadata.get("manifest_hashes"),
        )
        if not ok or not req_obj:
            # Check if clarification was emitted
            if err and err.startswith("CLARIFICATION_NEEDED::"):
                # Clarification was emitted - planner should halt
                if clarify_path.exists():
                    die("Clarification required. See CLARIFY.json for details.", 1)
            die(err or "Failed to compile objective to REQ.json", 1)

    # Generate planning artifacts deterministically
    tasks_json = intent_to_tasks.generate_tasks_from_req(req_obj)
    spec_md = intent_to_tasks.generate_spec_from_req(req_obj, objective)
    plan_md = intent_to_tasks.generate_plan_from_tasks(tasks_json)

    write_text(request_dir / "TASKS.json", json.dumps(tasks_json, indent=2) + "\n")
    write_text(request_dir / "SPEC.md", spec_md)
    write_text(request_dir / "PLAN.md", plan_md)
    write_text(request_dir / "NEEDS.json", json.dumps({"needs": []}, indent=2) + "\n")

    # Step 12: Index-backed answering (no ad-hoc parsing).
    payload = {}
    payload_path = request_dir / "payload.json"
    if payload_path.exists():
        try:
            payload = json.loads(read_text(payload_path))
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}

    if payload.get("answer_mode") == "index_backed":
        planner_dir = request_dir / "planner"
        planner_dir.mkdir(parents=True, exist_ok=True)

        answer_queries = payload.get("answer_queries", [])
        if not isinstance(answer_queries, list):
            answer_queries = []

        from nlc.index.query_service import open_request_index, normalize_query, query_index
        conn = open_request_index(str(request_dir))
        try:
            canonical_queries = [normalize_query(q) for q in answer_queries if isinstance(q, dict)]
            results = []
            evidence = []
            for q in canonical_queries:
                res = query_index(conn, q)
                results.append(res)
                # Collect evidence for search ops (doc_id + excerpt)
                if res.get("status") == "OK" and res.get("op") == "search":
                    for r in (res.get("results") or []):
                        if not isinstance(r, dict):
                            continue
                        doc_id = str(r.get("doc_id", "")).strip()
                        source_id = str(r.get("source_id", "")).strip()
                        excerpt = str(r.get("snippet", "") or "")
                        excerpt_sha256 = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
                        evidence.append(
                            {
                                "doc_id": doc_id,
                                "source_id": source_id,
                                "excerpt": excerpt,
                                "excerpt_sha256": excerpt_sha256,
                            }
                        )
        finally:
            conn.close()

        # Deterministic ordering
        evidence = sorted(evidence, key=lambda e: (e.get("doc_id", ""), e.get("excerpt_sha256", "")))

        plan_obj = {
            "index_used": True,
            "queries": canonical_queries,
            "evidence": evidence,
            "tasks": [],  # answering-only mode emits no execution tasks
        }
        write_text(planner_dir / "plan.json", json.dumps(plan_obj, indent=2, sort_keys=True) + "\n")

    print("OK")


if __name__ == "__main__":
    main()
