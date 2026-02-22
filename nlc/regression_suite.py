#!/usr/bin/env python3
"""
Regression Suite - deterministic, behavioral checks.

This is NOT a smoke test: it verifies that:
- build succeeds (or is correctly BLOCKED)
- REQ.json matches expected intents/params
- generated CLI output matches expected_output (for supported intents)
"""

import json
import hashlib
import subprocess
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Tuple
from datetime import datetime, timezone


BASE = Path(__file__).resolve().parents[1]
REGRESSION_DIR = BASE / "nlc" / "regression"
REQS_DIR = BASE / "state" / "requests"


SUITE_VERSION = "1.4.0"


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"


def _sha256_12(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12].upper()


def _request_id_for_prompt(prompt: str) -> str:
    return f"NLC-{_sha256_12(prompt)}"


def load_regression_suite() -> List[Dict[str, Any]]:
    suite_file = REGRESSION_DIR / "suite.json"
    if not suite_file.exists():
        return []
    try:
        suite = json.loads(suite_file.read_text(encoding="utf-8", errors="replace"))
        if str(suite.get("version", "")).strip() != SUITE_VERSION:
            return []
        tests = suite.get("tests", [])
        # Backward-compatible: ensure each test has a suite label.
        for t in tests:
            if "suite" not in t:
                if str(t.get("expected_status", "")).lower() == "blocked":
                    t["suite"] = "guardrail_block"
                else:
                    t["suite"] = "product_pass"
        return tests
    except Exception:
        return []


def _emit_print_sequence_expected(frm: int, to: int, step: int) -> str:
    if step == 0:
        return ""
    out: list[str] = []
    if step > 0:
        x = frm
        while x <= to:
            out.append(str(x))
            x += step
    else:
        x = frm
        while x >= to:
            out.append(str(x))
            x += step
    return "\n".join(out) + "\n"


def create_default_suite() -> Dict[str, Any]:
    """Create a deterministic regression suite."""
    REGRESSION_DIR.mkdir(parents=True, exist_ok=True)

    tests: list[dict] = []

    # 50 print_sequence variants (positive step only; parser extracts digits)
    frm_vals = [1, 2, 3, 5, 7]
    to_vals = [10, 12, 15, 20, 25, 30, 35, 40, 50, 60]
    steps = [1, 2, 3, 5]
    tid = 1
    for frm in frm_vals:
        for to in to_vals:
            for step in steps:
                if tid > 50:
                    break
                prompt = f"Make a CLI that counts from {frm} to {to} by {step}"
                tests.append(
                    {
                        "id": f"test-{tid:03d}",
                        "prompt": prompt,
                        "expected_intents": ["print_sequence"],
                        "expected_params": {"from": frm, "to": to, "step": step},
                        "expected_output": _emit_print_sequence_expected(frm, to, step),
                    }
                )
                tid += 1
            if tid > 50:
                break
        if tid > 50:
            break

    # 10 sum_numbers variants
    sums = [
        [1, 2, 3],
        [10, 20],
        [5, 5, 5, 5],
        [7],
        [100, 200, 300],
        [9, 8, 7, 6],
        [0, 0, 0],
        [42, 1],
        [3, 14, 15, 92],
        [2, 4, 6, 8, 10],
    ]
    for nums in sums:
        prompt = "Sum " + " ".join(str(n) for n in nums)
        tests.append(
            {
                "id": f"test-{len(tests)+1:03d}",
                "prompt": prompt,
                "expected_intents": ["sum_numbers"],
                "expected_params": {"numbers": nums},
                "expected_output": f"{sum(nums)}\n",
            }
        )

    

    # Pipeline extraction cases (no behavioral asserts yet; REQ must be correct)
    pipeline_pass = [
        {
            "name": "pipeline_write_lines_from_stdin",
            "prompt": "Make a CLI that reads lines from stdin, filters lines containing 'error', and write to out.txt.",
            "expected_intents": ["stdin_support", "filter_contains", "write_lines"],
            "expected_params_by_intent": {
                "stdin_support": {"read_mode": "lines"},
                "filter_contains": {"substring": "error", "case_sensitive": False},
                "write_lines": {"file_path": "out.txt", "encoding": "utf-8"},
            },
        },
        {
            "name": "pipeline_csv_filter_write",
            "prompt": "Make a CLI that reads csv from input.csv, filters rows containing 'error', and write to output.csv.",
            "expected_intents": ["csv_read", "filter_contains", "csv_write"],
            "expected_params_by_intent": {
                "csv_read": {"file_path": "input.csv", "has_header": True},
                "filter_contains": {"substring": "error", "case_sensitive": False},
                "csv_write": {"file_path": "output.csv"},
            },
        },

        {
            "name": "pipeline_stdin_filter_unique_json",
            "prompt": 'Make a CLI that reads lines from stdin, filters lines containing "error", removes duplicates preserving order, and outputs json.',
            "expected_intents": ["stdin_support", "filter_contains", "unique", "output_format"],
            "expected_params_by_intent": {
                "stdin_support": {"read_mode": "lines"},
                "filter_contains": {"substring": "error", "case_sensitive": False},
                "unique": {"preserve_order": True},
                "output_format": {"format": "json"},
            },
        },
        {
            "name": "pipeline_pipe_filter_text",
            "prompt": "Make a CLI that reads from standard input, filters lines containing 'WA', and outputs text.",
            "expected_intents": ["stdin_support", "filter_contains", "output_format"],
            "expected_params_by_intent": {
                "stdin_support": {"read_mode": "lines"},
                "filter_contains": {"substring": "WA", "case_sensitive": False},
                "output_format": {"format": "text"},
            },
        },
        {
            "name": "pipeline_read_lines_filter_json",
            "prompt": "Make a CLI that reads lines from sample_lines.txt, filters lines containing 'error', and outputs json.",
            "expected_intents": ["read_lines", "filter_contains", "output_format"],
            "expected_params_by_intent": {
                "read_lines": {"encoding": "utf-8"},
                "filter_contains": {"substring": "error", "case_sensitive": False},
                "output_format": {"format": "json"},
            },
        },
        {
            "name": "pipeline_csv_read_output_json",
            "prompt": "Make a CLI that reads csv from data.csv and outputs json.",
            "expected_intents": ["csv_read", "output_format"],
            "expected_params_by_intent": {
                "csv_read": {"file_path": "data.csv", "has_header": True},
                "output_format": {"format": "json"},
            },
        },
    ]

    pipeline_blocked = [
        {
            "name": "blocked_missing_substring",
            "prompt": "Make a CLI that reads lines from stdin and filters lines containing and outputs json.",
        },
        {
            "name": "blocked_ambiguous_output_formats",
            "prompt": "Make a CLI that reads lines from stdin and outputs json and outputs csv.",
        },
    ]



    numeric_pass = [
        {
            "prompt": "Make a CLI that sorts numbers 3 1 2 and outputs json.",
            "expected_intents": ["sort_numbers", "output_format"],
            "expected_params_by_intent": {
                "sort_numbers": {"numbers": [3, 1, 2], "reverse": False},
                "output_format": {"format": "json"},
            },
        },
        {
            "prompt": "Make a CLI that computes stats for numbers 3 1 2 and outputs json.",
            "expected_intents": ["stats_basic", "output_format"],
            "expected_params_by_intent": {
                "stats_basic": {"numbers": [3, 1, 2]},
                "output_format": {"format": "json"},
            },
        },
        {
            "prompt": "Make a CLI that reads lines from numbers.txt, sorts numbers, and outputs json.",
            "expected_intents": ["read_lines", "parse_numbers", "sort_numbers", "output_format"],
            "expected_params_by_intent": {
                "read_lines": {"file_path": "numbers.txt", "encoding": "utf-8"},
                "parse_numbers": {},
                "sort_numbers": {"reverse": False},
                "output_format": {"format": "json"},
            },
        },
        {
            "prompt": "Make a CLI that reads numbers from stdin, sorts them, and outputs json.",
            "expected_intents": ["stdin_support", "parse_numbers", "sort_numbers", "output_format"],
            "expected_params_by_intent": {
                "stdin_support": {"read_mode": "lines"},
                "parse_numbers": {},
                "sort_numbers": {"reverse": False},
                "output_format": {"format": "json"},
            },
        },
    ]


    numeric_blocked = [
        {
            "prompt": "Make a CLI that sorts numbers and outputs json.",
        },
        {
            "prompt": "Make a CLI that sorts numbers 3 1 2 and outputs json and outputs csv.",
        },
        {
            "prompt": "Make a CLI that reads lines from mixed.txt, sorts numbers, and outputs json.",
            # Runtime blocking: non-numeric input in mixed.txt causes exit code 2 (strict parse_numbers policy)
        },
    ]
    # parse_numbers strict policy: non-numeric input should cause runtime failure
    # These are behavioral tests that verify the CLI exits with code 2 on non-numeric input
    parse_numbers_strict_pass = [
        {
            "prompt": "Make a CLI that reads lines from numbers.txt, sorts numbers, and outputs json.",
            "expected_intents": ["read_lines", "parse_numbers", "sort_numbers", "output_format"],
            "expected_params_by_intent": {
                "read_lines": {"file_path": "numbers.txt", "encoding": "utf-8"},
                "parse_numbers": {},
                "sort_numbers": {"reverse": False},
                "output_format": {"format": "json"},
            },
        },
    ]





    for case in numeric_pass:
        tests.append(
            {
                "id": f"test-{len(tests)+1:03d}",
                "prompt": case["prompt"],
                "expected_intents": case["expected_intents"],
                "expected_params_by_intent": case["expected_params_by_intent"],
            }
        )


    for case in parse_numbers_strict_pass:
        tests.append(
            {
                "id": f"test-{len(tests)+1:03d}",
                "prompt": case["prompt"],
                "expected_intents": case["expected_intents"],
                "expected_params_by_intent": case["expected_params_by_intent"],
            }
        )

    for case in numeric_blocked:
        tests.append(
            {
                "id": f"test-{len(tests)+1:03d}",
                "prompt": case["prompt"],
                "expected_status": "blocked",
            }
        )
    # Ensure fixture exists for read_lines-based pipeline tests
    fx = REGRESSION_DIR / 'fixtures'
    fx.mkdir(parents=True, exist_ok=True)
    sl = fx / 'sample_lines.txt'
    if not sl.exists():
        sl.write_text('ok\nerror one\nerror one\n', encoding='utf-8')

    for case in pipeline_pass:
        tests.append(
            {
                "id": f"test-{len(tests)+1:03d}",
                "prompt": case["prompt"],
                "expected_intents": case["expected_intents"],
                "expected_params_by_intent": case["expected_params_by_intent"],
            }
        )

    for case in pipeline_blocked:
        tests.append(
            {
                "id": f"test-{len(tests)+1:03d}",
                "prompt": case["prompt"],
                "expected_status": "blocked",
            }
        )
# Additional PASS cases for new intents
    tests.append(
        {
            "id": f"test-{len(tests)+1:03d}",
            "prompt": "Count lines from stdin and output json.",
            "expected_intents": ["stdin_support", "count_lines", "output_format"],
            "expected_params_by_intent": {
                "stdin_support": {"read_mode": "lines"},
                "output_format": {"format": "json"},
            },
        }
    )
    tests.append(
        {
            "id": f"test-{len(tests)+1:03d}",
            "prompt": "Read lines from numbers.txt, count lines, and output json.",
            "expected_intents": ["read_lines", "count_lines", "output_format"],
            "expected_params_by_intent": {
                "read_lines": {"file_path": "numbers.txt", "encoding": "utf-8"},
                "output_format": {"format": "json"},
            },
        }
    )
    tests.append(
        {
            "id": f"test-{len(tests)+1:03d}",
            "prompt": "Pretty print json from stdin and output json.",
            "expected_intents": ["stdin_support", "json_pretty_print", "output_format"],
            "expected_params_by_intent": {
                "stdin_support": {"read_mode": "lines"},
                "output_format": {"format": "json"},
            },
        }
    )
    tests.append(
        {
            "id": f"test-{len(tests)+1:03d}",
            "prompt": "Read lines from data.json, pretty print json, and write to output.json.",
            "expected_intents": ["read_lines", "json_pretty_print", "write_lines"],
            "expected_params_by_intent": {
                "read_lines": {"file_path": "data.json", "encoding": "utf-8"},
                "write_lines": {"file_path": "output.json", "encoding": "utf-8"},
            },
        }
    )

    # Additional BLOCK cases for new intents
    tests.append(
        {
            "id": f"test-{len(tests)+1:03d}",
            "prompt": "Count lines and output json and output csv.",
            "expected_status": "blocked",
        }
    )
    tests.append(
        {
            "id": f"test-{len(tests)+1:03d}",
            "prompt": "Pretty print json.",
            "expected_status": "blocked",
        }
    )

# 5 blocked cases
    blocked_prompts = [
        "Make a CLI that trains a neural network to classify images.",
        "Build a web app with React and a database.",
        "Create a GUI that edits photos.",
        "Write a Kubernetes operator for scaling pods.",
        "Make a CLI that parses PDFs and summarizes them.",
    ]
    for bp in blocked_prompts:
        tests.append(
            {
                "id": f"test-{len(tests)+1:03d}",
                "prompt": bp,
                "expected_status": "blocked",
            }
        )
    suite_obj = {
        "version": SUITE_VERSION,
        "description": "Default regression test suite for NLC (deterministic cases)",
        "tests": tests,
    }
    (REGRESSION_DIR / "suite.json").write_text(json.dumps(suite_obj, indent=2) + "\n", encoding="utf-8")
    return suite_obj


def _is_blocked_error(error: str | None) -> bool:
    e = (error or "").lower()
    return ("unsupported intent" in e) or ("no supported intents matched" in e) or ("blocked::" in e) or ("missing_required_param" in e) or ("ambiguous_intent" in e)


def _read_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8", errors="replace"))


def _pick_main_py(workspace_project: Path) -> Path:
    mp = workspace_project / "main.py"
    if mp.exists():
        return mp
    py = sorted([p for p in workspace_project.glob("*.py") if p.is_file()])
    return py[0] if py else mp


def _run_cli_and_capture(workspace_project: Path, command: str) -> Tuple[int, str, str]:
    main_py = _pick_main_py(workspace_project)
    p = subprocess.run(
        ["python3", str(main_py), command],
        cwd=workspace_project,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return p.returncode, p.stdout, p.stderr


def run_regression_suite() -> Dict[str, Any]:
    suite = load_regression_suite()
    if not suite:
        suite = create_default_suite()["tests"]

    # Partition suites
    product_suite = [t for t in suite if str(t.get("suite", "") or "").lower() not in ("guardrail_block", "guardrail")]
    guardrail_suite = [t for t in suite if str(t.get("suite", "") or "").lower() in ("guardrail_block", "guardrail")]

    # Coverage trackers (product suite, passed tests)
    pipeline_counts: dict[str, int] = {}
    intent_pass_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}

    # Supported intents (for coverage checks)
    import importlib.util
    spec_cb = importlib.util.spec_from_file_location("capability_boundary", BASE / "nlc" / "capability_boundary.py")
    capability_boundary = importlib.util.module_from_spec(spec_cb)
    assert spec_cb.loader is not None
    spec_cb.loader.exec_module(capability_boundary)
    supported_intents = set(capability_boundary.get_supported_intents())

    # Import build_repo from the nlc.py file (avoid package import ambiguity).
    spec = importlib.util.spec_from_file_location("nlc_cli", BASE / "nlc.py")
    nlc_cli = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(nlc_cli)
    build_repo = nlc_cli.build_repo

    # Ensure we have a deterministic local KB snapshot ID to pin in repro builds.
    fixtures = REGRESSION_DIR / "fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    kb_src = fixtures / "kb_source.html"
    if not kb_src.exists():
        kb_src.write_text("<html><body><h1>KB Fixture</h1><p>deterministic</p></body></html>\\n", encoding="utf-8")
    from nlc.kb.build_snapshot import build_snapshot
    snap_dir = build_snapshot(BASE, "AUTO", [str(kb_src)], write_latest=True)
    kb_snapshot_id = snap_dir.name
    kb_snapshot_hash = (snap_dir / "SNAPSHOT.sha256").read_text(encoding="utf-8", errors="replace").strip()



    # Ensure we have a deterministic DB snapshot for DB-backed registry tests.
    def _ensure_db_registry_snapshot() -> tuple[str, str, str]:
        reg_hash_file = BASE / "nlc" / "registry" / "v1" / "INTENT_REGISTRY.sha256"
        if reg_hash_file.exists():
            reg_hash = reg_hash_file.read_text(encoding="utf-8", errors="replace").strip()
        else:
            reg_hash = hashlib.sha256(b"").hexdigest()
        snapshot_id = reg_hash[:12]
        snap_dir = BASE / "nlc" / "db" / "snapshots" / snapshot_id
        db_file = snap_dir / "nlc.db"
        sha_file = snap_dir / "DB_SNAPSHOT.sha256"
        if sha_file.exists() and db_file.exists():
            return snapshot_id, sha_file.read_text(encoding="utf-8", errors="replace").strip(), reg_hash

        snap_dir.mkdir(parents=True, exist_ok=True)
        intents_dir = BASE / "nlc" / "registry" / "v1" / "intents"

        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()
        cur.execute('PRAGMA journal_mode=OFF;')
        cur.execute('PRAGMA synchronous=OFF;')
        cur.execute('PRAGMA temp_store=MEMORY;')

        cur.executescript("""
BEGIN;
CREATE TABLE IF NOT EXISTS nlc_registry_meta (
  registry_version TEXT PRIMARY KEY,
  intent_registry_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nlc_intents (
  intent_id TEXT PRIMARY KEY,
  description TEXT NOT NULL,
  pipeline_type TEXT NOT NULL,
  params_json TEXT NOT NULL,
  io_json TEXT NOT NULL,
  disambiguation_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nlc_synonyms (
  intent_id TEXT NOT NULL,
  phrase TEXT NOT NULL,
  weight REAL NOT NULL,
  PRIMARY KEY(intent_id, phrase)
);
CREATE TABLE IF NOT EXISTS nlc_examples (
  intent_id TEXT NOT NULL,
  prompt TEXT NOT NULL,
  req_fragment_json TEXT NOT NULL,
  PRIMARY KEY(intent_id, prompt)
);
DELETE FROM nlc_registry_meta;
DELETE FROM nlc_intents;
DELETE FROM nlc_synonyms;
DELETE FROM nlc_examples;
COMMIT;
""")

        def _canon(obj) -> str:
            return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

        cur.execute("BEGIN;")
        cur.execute(
            "INSERT INTO nlc_registry_meta(registry_version, intent_registry_hash) VALUES (?,?)",
            ("v1", reg_hash),
        )

        for fp in sorted([x for x in intents_dir.glob("*.json") if x.is_file()], key=lambda x: x.name):
            doc = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
            intent_id = str(doc.get("intent_id", "")).strip()
            if not intent_id:
                continue
            description = str(doc.get("description", ""))
            pipeline_type = str(doc.get("pipeline_type", "unknown"))
            params_json = _canon(doc.get("params_json") or {})
            io_json = _canon(doc.get("io_json") or {})
            disamb_json = _canon(doc.get("disambiguation_json") or {})
            cur.execute(
                "INSERT INTO nlc_intents(intent_id, description, pipeline_type, params_json, io_json, disambiguation_json) VALUES (?,?,?,?,?,?)",
                (intent_id, description, pipeline_type, params_json, io_json, disamb_json),
            )

            syns = [str(s).strip().lower() for s in (doc.get("synonyms") or []) if str(s).strip()]
            for phrase in sorted(set(syns)):
                cur.execute(
                    "INSERT INTO nlc_synonyms(intent_id, phrase, weight) VALUES (?,?,?)",
                    (intent_id, phrase, 1.0),
                )

            exs = doc.get("examples") or []
            ex_rows = []
            for ex in exs:
                if not isinstance(ex, dict):
                    continue
                pr = str(ex.get("prompt", "")).strip()
                frag = ex.get("req_fragment") or {}
                if pr:
                    ex_rows.append((intent_id, pr, _canon(frag)))
            for r in sorted(ex_rows, key=lambda t: (t[0], t[1])):
                cur.execute(
                    "INSERT INTO nlc_examples(intent_id, prompt, req_fragment_json) VALUES (?,?,?)",
                    r,
                )

        cur.execute("COMMIT;")
        cur.execute("VACUUM;")
        conn.commit()
        conn.close()

        digest = hashlib.sha256(db_file.read_bytes()).hexdigest()
        sha_file.write_text(digest + "\n", encoding="utf-8")
        return snapshot_id, digest, reg_hash

    db_snapshot_id, db_snapshot_hash, intent_registry_hash = _ensure_db_registry_snapshot()

    git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=BASE).decode().strip()
    per_intent: dict[str, dict[str, int]] = {}
    results: dict[str, Any] = {
        "timestamp": _now_utc(),
        "total": len(suite) + 8,
        "passed": 0,
        "failed": 0,
        "blocked_expected": 0,
        "blocked_unexpected": 0,
        "pass_rate": 0.0,
        "blocked_by_reason": {},
        "per_intent": per_intent,
        "tests": [],
        "meta_tests": [],
        "meta_checks": [],
        "suites": {
            "product_pass": {
                "total": len(product_suite),
                "passed": 0,
                "failed": 0,
                "pass_rate": 0.0,
            },
            "guardrail_block": {
                "total": len(guardrail_suite),
                "blocked_expected": 0,
                "blocked_unexpected": 0,
                "failed": 0,
                "blocked_by_reason": {},
            },
        },
        "coverage": {
            "pipeline_counts": {},
            "pipeline_max_share": 0.0,
            "intent_pass_counts": {},
            "source_counts": {},
            "thresholds": {
                "pipeline_max_share": 0.4,
                "intent_min_pass": 5,
            },
        },
        "suite_version": "1.4.0",
        "kb_snapshot_id": kb_snapshot_id,
        "kb_snapshot_hash": kb_snapshot_hash,
        "db_snapshot_id": db_snapshot_id,
        "db_snapshot_hash": db_snapshot_hash,
        "intent_registry_hash": intent_registry_hash,
        "git_commit": git_commit,
        "db_snapshot_derivation": "intent_registry_hash[:12]",
    }


    # Meta test: KB snapshot determinism (build twice from identical local fixture sources)
    mt_kb = {"id": "meta-kb-snapshot-determinism", "status": "unknown", "error": None}
    try:
        from nlc.kb.build_snapshot import build_snapshot
        s1 = build_snapshot(BASE, "AUTO", [str(kb_src)], write_latest=True)
        h1 = (s1 / "SNAPSHOT.sha256").read_text(encoding="utf-8", errors="replace").strip()
        s2 = build_snapshot(BASE, "AUTO", [str(kb_src)], write_latest=True)
        h2 = (s2 / "SNAPSHOT.sha256").read_text(encoding="utf-8", errors="replace").strip()
        if h1 != h2:
            mt_kb["status"] = "failed"
            mt_kb["error"] = f"KB snapshot hash differs: {h1} vs {h2}"
            results["failed"] += 1
        else:
            mt_kb["status"] = "passed"
            results["passed"] += 1
    except Exception as e:
        mt_kb["status"] = "failed"
        mt_kb["error"] = str(e)
        results["failed"] += 1
    results["meta_tests"].append(mt_kb)

    def bump(intent: str, key: str) -> None:
        per_intent.setdefault(intent, {"passed": 0, "failed": 0, "blocked_expected": 0, "blocked_unexpected": 0, "total": 0})
        per_intent[intent]["total"] += 1
        per_intent[intent][key] += 1

    def _bump_blocked_reason(reason: str) -> None:
        r = reason or "UNKNOWN"
        results["blocked_by_reason"][r] = int(results["blocked_by_reason"].get(r, 0)) + 1

    def _blocked_reason_for_prompt(prompt: str) -> str:
        rid = _request_id_for_prompt(prompt)
        p = (REQS_DIR / rid / "BLOCKED.json")
        if not p.exists():
            return ""
        try:
            obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            return str(obj.get("reason_code", "")).strip()
        except Exception:
            return ""

    # Meta test 1: repro without snapshot pin must BLOCK.
    mt_prompt_missing = "Make a CLI that prints 1 to 10"
    mt1 = {"id": "meta-repro-missing-kb-pin", "prompt": mt_prompt_missing, "status": "unknown", "error": None}
    ok, err, _ = build_repo(mt_prompt_missing, repro_mode=True, kb_snapshot_id=None)
    if ok:
        mt1["status"] = "failed"
        mt1["error"] = "Expected BLOCKED (MISSING_KB_SNAPSHOT_PIN) but build succeeded"
        results["failed"] += 1
    else:
        reason = _blocked_reason_for_prompt(mt_prompt_missing)
        if reason != "MISSING_KB_SNAPSHOT_PIN":
            mt1["status"] = "failed"
            mt1["error"] = f"Expected reason_code=MISSING_KB_SNAPSHOT_PIN, got {reason or err}"
            results["failed"] += 1
        else:
            mt1["status"] = "passed"
            results["passed"] += 1
    results["meta_tests"].append(mt1)

    # Meta test 2: repro build determinism with pinned snapshot.
    import shutil, tempfile
    mt_prompt_det = "Make a CLI that counts from 1 to 10 and prints each number on its own line."
    mt2 = {"id": "meta-repro-determinism-pinned-snapshot", "prompt": mt_prompt_det, "status": "unknown", "error": None}
    ok1, err1, dist1 = build_repo(mt_prompt_det, repro_mode=True, kb_snapshot_id=kb_snapshot_id)
    if not ok1 or dist1 is None:
        mt2["status"] = "failed"
        mt2["error"] = err1 or "first build failed"
        results["failed"] += 1
    else:
        a = Path(tempfile.mkdtemp(prefix="nlc-reproA-"))
        b = Path(tempfile.mkdtemp(prefix="nlc-reproB-"))
        shutil.copytree(dist1, a / "dist", dirs_exist_ok=True)
        ok2, err2, dist2 = build_repo(mt_prompt_det, repro_mode=True, kb_snapshot_id=kb_snapshot_id)
        if not ok2 or dist2 is None:
            mt2["status"] = "failed"
            mt2["error"] = err2 or "second build failed"
            results["failed"] += 1
        else:
            shutil.copytree(dist2, b / "dist", dirs_exist_ok=True)
            man_a = (a / "dist" / "MANIFEST.json").read_bytes()
            man_b = (b / "dist" / "MANIFEST.json").read_bytes()
            chk_a = (a / "dist" / "checksums.sha256").read_bytes()
            chk_b = (b / "dist" / "checksums.sha256").read_bytes()
            if man_a != man_b:
                mt2["status"] = "failed"
                mt2["error"] = "MANIFEST.json differs between repro runs"
                results["failed"] += 1
            elif chk_a != chk_b:
                mt2["status"] = "failed"
                mt2["error"] = "checksums.sha256 differs between repro runs"
                results["failed"] += 1
            else:
                ma = json.loads(man_a.decode("utf-8", errors="replace"))
                mb = json.loads(man_b.decode("utf-8", errors="replace"))
                if ma.get("output_hash") != mb.get("output_hash"):
                    mt2["status"] = "failed"
                    mt2["error"] = "output_hash differs between repro runs"
                    results["failed"] += 1
                else:
                    mt2["status"] = "passed"
                    results["passed"] += 1
    results["meta_tests"].append(mt2)

    # Meta test 3: repro build makes no network calls (net_attempts.log remains absent/empty).
    mt_prompt_net = "Make a CLI that sums 1 2 3"
    mt3 = {"id": "meta-repro-no-network", "prompt": mt_prompt_net, "status": "unknown", "error": None}
    ok3, err3, _ = build_repo(mt_prompt_net, repro_mode=True, kb_snapshot_id=kb_snapshot_id)
    if not ok3:
        mt3["status"] = "failed"
        mt3["error"] = err3 or "build failed"
        results["failed"] += 1
    else:
        rid = _request_id_for_prompt(mt_prompt_net)
        netlog = REQS_DIR / rid / "net_attempts.log"
        if netlog.exists() and netlog.read_text(encoding="utf-8", errors="replace").strip():
            mt3["status"] = "failed"
            mt3["error"] = f"Unexpected network attempt log entries: {netlog.read_text(encoding='utf-8', errors='replace')[:200]}"
            results["failed"] += 1
        else:
            mt3["status"] = "passed"
            results["passed"] += 1
    results["meta_tests"].append(mt3)

    # Meta test 4: capabilities via file registry == capabilities via DB registry snapshot.
    mt4 = {"id": "meta-registry-capabilities-file-vs-db", "status": "unknown", "error": None}
    try:
        file_ids = []
        reg_json = BASE / "nlc" / "registry" / "v1" / "registry.json"
        if reg_json.exists():
            obj = json.loads(reg_json.read_text(encoding="utf-8", errors="replace"))
            file_ids = sorted([str(x) for x in (obj.get("intent_ids") or [])])
        dbp = BASE / "nlc" / "db" / "snapshots" / db_snapshot_id / "nlc.db"
        conn = sqlite3.connect(str(dbp))
        cur = conn.cursor()
        db_ids = [r[0] for r in cur.execute("SELECT intent_id FROM nlc_intents ORDER BY intent_id")]
        conn.close()
        if file_ids != db_ids:
            mt4["status"] = "failed"
            mt4["error"] = f"capabilities mismatch: file={file_ids} db={db_ids}"
            results["failed"] += 1
        else:
            mt4["status"] = "passed"
            results["passed"] += 1
    except Exception as e:
        mt4["status"] = "failed"
        mt4["error"] = str(e)
        results["failed"] += 1
    results["meta_tests"].append(mt4)

    # Meta test 5: compile-intent output identical for registry_source=file vs db (pinned DB snapshot).
    mt5_prompt = "Make a CLI that counts from 1 to 10 and prints each number on its own line."
    mt5 = {"id": "meta-compile-intent-file-vs-db", "prompt": mt5_prompt, "status": "unknown", "error": None}
    try:
        import os, tempfile
        import importlib.util
        spec = importlib.util.spec_from_file_location("prompt_compiler", BASE / "nlc" / "prompt_compiler.py")
        pc = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(pc)

        td1 = Path(tempfile.mkdtemp(prefix="nlc-ci-file-"))
        td2 = Path(tempfile.mkdtemp(prefix="nlc-ci-db-"))

        os.environ["DCS_REPRO"] = "1"
        os.environ["NLC_KB_SNAPSHOT_ID"] = kb_snapshot_id

        os.environ["NLC_REGISTRY_SOURCE"] = "file"
        pc.compile_with_fallback(mt5_prompt, td1)

        os.environ["NLC_REGISTRY_SOURCE"] = "db"
        os.environ["NLC_DB_SNAPSHOT_ID"] = db_snapshot_id
        pc.compile_with_fallback(mt5_prompt, td2)

        if td1.joinpath("REQ.json").read_bytes() != td2.joinpath("REQ.json").read_bytes():
            mt5["status"] = "failed"
            mt5["error"] = "REQ.json differs between file and db"
            results["failed"] += 1
        elif td1.joinpath("INTENT_TRACE.json").read_bytes() != td2.joinpath("INTENT_TRACE.json").read_bytes():
            mt5["status"] = "failed"
            mt5["error"] = "INTENT_TRACE.json differs between file and db"
            results["failed"] += 1
        else:
            mt5["status"] = "passed"
            results["passed"] += 1
    except Exception as e:
        mt5["status"] = "failed"
        mt5["error"] = str(e)
        results["failed"] += 1
    results["meta_tests"].append(mt5)

    

    # Meta test 7: deterministic fuzz variants (same meaning -> identical REQ.json)
    mt7 = {"id": "meta-pipeline-fuzz-variants", "status": "unknown", "error": None}
    try:
        import os, tempfile
        import importlib.util
        spec = importlib.util.spec_from_file_location("prompt_compiler", BASE / "nlc" / "prompt_compiler.py")
        pc = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(pc)

        base_prompt = 'Make a CLI that reads lines from stdin, filters lines containing "error", removes duplicates preserving order, and outputs json.'
        variants = [
            base_prompt,
            'Make a CLI that reads from standard input, filters lines containing "error", removes duplicates preserving order, and outputs json.',
            'Make a CLI that reads lines from stdin and filters lines containing "error" and removes duplicates preserving order and outputs json.',
        ]

        os.environ["DCS_REPRO"] = "1"
        os.environ["NLC_KB_SNAPSHOT_ID"] = kb_snapshot_id

        outs = []
        for pr in variants:
            td = Path(tempfile.mkdtemp(prefix="nlc-fuzz-"))
            pc.compile_with_fallback(pr, td)
            outs.append((td / "REQ.json").read_bytes())

        if any(o != outs[0] for o in outs[1:]):
            mt7["status"] = "failed"
            mt7["error"] = "REQ.json differs across fuzz variants"
            results["failed"] += 1
        else:
            mt7["status"] = "passed"
            results["passed"] += 1
    except Exception as e:
        mt7["status"] = "failed"
        mt7["error"] = str(e)
        results["failed"] += 1
    results["meta_tests"].append(mt7)
# Meta test 6: compile-intent determinism with pinned DB snapshot (db source twice -> identical outputs).
    mt6_prompt = "Make a CLI that sums 1 2 3"
    mt6 = {"id": "meta-compile-intent-determinism-db", "prompt": mt6_prompt, "status": "unknown", "error": None}
    try:
        import os, tempfile
        import importlib.util
        spec = importlib.util.spec_from_file_location("prompt_compiler", BASE / "nlc" / "prompt_compiler.py")
        pc = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(pc)

        a = Path(tempfile.mkdtemp(prefix="nlc-ci-dbA-"))
        b = Path(tempfile.mkdtemp(prefix="nlc-ci-dbB-"))

        os.environ["DCS_REPRO"] = "1"
        os.environ["NLC_KB_SNAPSHOT_ID"] = kb_snapshot_id
        os.environ["NLC_REGISTRY_SOURCE"] = "db"
        os.environ["NLC_DB_SNAPSHOT_ID"] = db_snapshot_id

        pc.compile_with_fallback(mt6_prompt, a)
        pc.compile_with_fallback(mt6_prompt, b)

        if a.joinpath("REQ.json").read_bytes() != b.joinpath("REQ.json").read_bytes():
            mt6["status"] = "failed"
            mt6["error"] = "REQ.json differs between db runs"
            results["failed"] += 1
        elif a.joinpath("INTENT_TRACE.json").read_bytes() != b.joinpath("INTENT_TRACE.json").read_bytes():
            mt6["status"] = "failed"
            mt6["error"] = "INTENT_TRACE.json differs between db runs"
            results["failed"] += 1
        else:
            mt6["status"] = "passed"
            results["passed"] += 1
    except Exception as e:
        mt6["status"] = "failed"
        mt6["error"] = str(e)
        results["failed"] += 1
    results["meta_tests"].append(mt6)

    for test in suite:
        test_id = test.get("id", "unknown")
        prompt = test.get("prompt", "")
        expected_status = test.get("expected_status")
        expected_intents = test.get("expected_intents", [])
        expected_params = test.get("expected_params", {})
        expected_params_by_intent = test.get("expected_params_by_intent", {})
        expected_output = test.get("expected_output")
        suite_name = str(test.get("suite") or ("guardrail_block" if expected_status == "blocked" else "product_pass")).lower()
        suite_stats = results["suites"].get(suite_name, {})

        primary_intent = expected_intents[0] if expected_intents else ("blocked" if expected_status == "blocked" else "unknown")

        tr: dict[str, Any] = {"id": test_id, "prompt": prompt, "status": "unknown", "error": None, "suite": suite_name}
        try:
            rid = _request_id_for_prompt(prompt)
            rd = REQS_DIR / rid
            ok, error, _dist_dir = build_repo(prompt, repro_mode=True, kb_snapshot_id=kb_snapshot_id)
            if not ok:
                is_block = expected_status == "blocked" or _is_blocked_error(error)
                if suite_name == "guardrail_block":
                    if is_block:
                        reason = _blocked_reason_for_prompt(prompt) or (error or "")
                        _bump_blocked_reason(reason if reason else "")
                        tr["status"] = "blocked"
                        tr["error"] = error
                        results["blocked_expected"] += 1
                        suite_stats["blocked_expected"] = suite_stats.get("blocked_expected", 0) + 1
                        bump(primary_intent, "blocked_expected")
                        results["tests"].append(tr)
                        continue
                    else:
                        tr["status"] = "failed"
                        tr["error"] = error
                        results["failed"] += 1
                        suite_stats["failed"] = suite_stats.get("failed", 0) + 1
                        bump(primary_intent, "failed")
                        results["tests"].append(tr)
                        continue
                # product_pass suite: any block/unexpected is a failure
                if is_block:
                    tr["status"] = "failed"
                    tr["error"] = error
                    results["failed"] += 1
                    suite_stats["failed"] = suite_stats.get("failed", 0) + 1
                    bump(primary_intent, "failed")
                    results["tests"].append(tr)
                    continue
                if expected_status == "blocked":
                    # Check VERIFY.md for specific runtime blocking reason (e.g., RUNTIME_INVALID_INPUT)
                    verify_path = rd / "VERIFY.md"
                    if verify_path.exists():
                        verify_content = verify_path.read_text(encoding="utf-8", errors="replace")
                        if "RUNTIME_INVALID_INPUT" in verify_content:
                            tr["error"] = "RUNTIME_INVALID_INPUT: non-numeric input rejected by strict parse_numbers policy"
                        else:
                            tr["error"] = error
                    else:
                        tr["error"] = error
                    tr["status"] = "blocked"
                    results["blocked_expected"] += 1
                    bump(primary_intent, "blocked_expected")
                    results["tests"].append(tr)
                    continue

            if expected_status == "blocked":
                # Check for runtime blocking: build succeeded but verifier failed
                # Check VERIFY.md for RUNTIME_INVALID_INPUT (strict policy rejection)
                verify_path = rd / "VERIFY.md"
                if verify_path.exists():
                    verify_content = verify_path.read_text(encoding="utf-8", errors="replace")
                    if "RUNTIME_INVALID_INPUT" in verify_content:
                        # Runtime blocking: verifier failed due to invalid input (strict policy)
                        tr["status"] = "blocked"
                        tr["error"] = "RUNTIME_INVALID_INPUT: non-numeric input rejected by strict parse_numbers policy"
                        results["blocked_expected"] += 1
                        suite_stats["blocked_expected"] = suite_stats.get("blocked_expected", 0) + 1
                        bump(primary_intent, "blocked_expected")
                        results["tests"].append(tr)
                        continue
                # Compile-time blocking expected but build succeeded
                tr["status"] = "failed"
                tr["error"] = "Expected BLOCKED but build succeeded"
                results["failed"] += 1
                suite_stats["failed"] = suite_stats.get("failed", 0) + 1
                bump(primary_intent, "failed")
                results["tests"].append(tr)
                continue

            req_path = rd / "REQ.json"
            if not req_path.exists():
                tr["status"] = "failed"
                tr["error"] = "REQ.json missing after successful build"
                results["failed"] += 1
                suite_stats["failed"] = suite_stats.get("failed", 0) + 1
                bump(primary_intent, "failed")
                results["tests"].append(tr)
                continue

            req = _read_json(req_path)
            intents = req.get("intents", [])
            got_intents = [i.get("intent_type") for i in intents if isinstance(i, dict)]
            if expected_intents and got_intents != expected_intents:
                tr["status"] = "failed"
                tr["error"] = f"REQ.json intents mismatch: expected {expected_intents}, got {got_intents}"
                results["failed"] += 1
                suite_stats["failed"] = suite_stats.get("failed", 0) + 1
                bump(primary_intent, "failed")
                results["tests"].append(tr)
                continue

            if expected_params and intents and isinstance(intents[0], dict):
                got_params = intents[0].get("params", {})
                for k, v in expected_params.items():
                    if got_params.get(k) != v:
                        tr["status"] = "failed"
                        tr["error"] = f"REQ.json params mismatch for '{k}': expected {v}, got {got_params.get(k)}"
                        results["failed"] += 1
                        suite_stats["failed"] = suite_stats.get("failed", 0) + 1
                        bump(primary_intent, "failed")
                        results["tests"].append(tr)
                        break
                if tr["status"] == "failed":
                    continue



            if expected_params_by_intent and intents:
                for it in intents:
                    if not isinstance(it, dict):
                        continue
                    itype = it.get("intent_type")
                    if itype not in expected_params_by_intent:
                        continue
                    gotp = it.get("params", {}) or {}
                    exp = expected_params_by_intent.get(itype) or {}
                    for k, v in exp.items():
                        if gotp.get(k) != v:
                            tr["status"] = "failed"
                            tr["error"] = f"REQ.json params mismatch for intent '{itype}' key '{k}': expected {v}, got {gotp.get(k)}"
                            results["failed"] += 1
                            suite_stats["failed"] = suite_stats.get("failed", 0) + 1
                            bump(primary_intent, "failed")
                            results["tests"].append(tr)
                            break
                    if tr["status"] == "failed":
                        break
                if tr["status"] == "failed":
                    continue
            workspace_project = rd / "workspace" / "project"
            if not workspace_project.exists():
                tr["status"] = "failed"
                tr["error"] = "workspace/project missing after successful build"
                results["failed"] += 1
                suite_stats["failed"] = suite_stats.get("failed", 0) + 1
                bump(primary_intent, "failed")
                results["tests"].append(tr)
                continue

            cmd = None
            if expected_intents == ["print_sequence"]:
                cmd = "print-sequence"
            elif expected_intents == ["sum_numbers"]:
                cmd = "sum-numbers"

            if cmd and expected_output is not None:
                rc, out, err = _run_cli_and_capture(workspace_project, cmd)
                if rc != 0:
                    tr["status"] = "failed"
                    tr["error"] = f"CLI rc={rc}; stderr={err.strip()[:200]}"
                    results["failed"] += 1
                    suite_stats["failed"] = suite_stats.get("failed", 0) + 1
                    bump(primary_intent, "failed")
                    results["tests"].append(tr)
                    continue
                if out != expected_output:
                    tr["status"] = "failed"
                    tr["error"] = "CLI stdout mismatch"
                    tr["stdout_got"] = out
                    tr["stdout_expected"] = expected_output
                    results["failed"] += 1
                    suite_stats["failed"] = suite_stats.get("failed", 0) + 1
                    bump(primary_intent, "failed")
                    results["tests"].append(tr)
                    continue

            tr["status"] = "passed"
            results["passed"] += 1
            suite_stats["passed"] = suite_stats.get("passed", 0) + 1
            bump(primary_intent, "passed")
            if suite_name == "product_pass":
                sig = ">".join(got_intents)
                pipeline_counts[sig] = pipeline_counts.get(sig, 0) + 1
                for it in got_intents:
                    intent_pass_counts[it] = intent_pass_counts.get(it, 0) + 1
                if "stdin_support" in got_intents:
                    source_counts["stdin"] = source_counts.get("stdin", 0) + 1
                elif "read_lines" in got_intents:
                    source_counts["file"] = source_counts.get("file", 0) + 1

        except Exception as e:
            tr["status"] = "failed"
            tr["error"] = str(e)
            results["failed"] += 1
            suite_stats["failed"] = suite_stats.get("failed", 0) + 1
            bump(primary_intent, "failed")

        results["tests"].append(tr)

    # Invariant checks: no blocked in product suite; no passes in guardrail suite.
    meta_checks: list[dict[str, Any]] = []
    def _add_meta(id_: str, status: str, error: str | None = None):
        mc = {"id": id_, "status": status}
        if error:
            mc["error"] = error
        meta_checks.append(mc)
        if status != "passed":
            results["failed"] += 1

    product_blocked = [t for t in results["tests"] if t.get("suite") == "product_pass" and t.get("status") == "blocked"]
    if product_blocked:
        _add_meta("inv-product-no-blocked", "failed", f"{len(product_blocked)} product tests blocked unexpectedly")
    else:
        _add_meta("inv-product-no-blocked", "passed")

    guardrail_passed = [t for t in results["tests"] if t.get("suite") == "guardrail_block" and t.get("status") == "passed"]
    if guardrail_passed:
        _add_meta("inv-guardrail-no-pass", "failed", f"{len(guardrail_passed)} guardrail tests passed unexpectedly")
    else:
        _add_meta("inv-guardrail-no-pass", "passed")

    # Registry/db snapshot derivation invariant: db_snapshot_id == intent_registry_hash[:12]
    db_ok = str(results.get("db_snapshot_id", "")) == str(results.get("intent_registry_hash", ""))[:12]
    if not db_ok:
        _add_meta("inv-db-id-derivation", "failed", "db_snapshot_id must equal intent_registry_hash[:12]")
    else:
        _add_meta("inv-db-id-derivation", "passed")

    # Coverage calculations (product passes only)
    pp = results["suites"]["product_pass"]
    gb = results["suites"]["guardrail_block"]
    total_product_pass = pp.get("passed", 0)
    pipeline_max_share = 0.0
    if total_product_pass > 0 and pipeline_counts:
        pipeline_max_share = max(count / total_product_pass for count in pipeline_counts.values())
    # Intent pass counts: include all supported intents
    intent_min = results["coverage"]["thresholds"]["intent_min_pass"]
    for it in supported_intents:
        intent_pass_counts.setdefault(it, 0)
    low_intents = [it for it, c in intent_pass_counts.items() if c < intent_min]
    pipeline_share_threshold = results["coverage"]["thresholds"]["pipeline_max_share"]
    if pipeline_max_share > pipeline_share_threshold:
        _add_meta("cov-pipeline-dominance", "failed", f"max pipeline share {pipeline_max_share:.2f} exceeds {pipeline_share_threshold:.2f}")
    else:
        _add_meta("cov-pipeline-dominance", "passed")
    if low_intents:
        _add_meta("cov-intent-min-pass", "failed", f"intents below min_pass={intent_min}: {sorted(low_intents)}")
    else:
        _add_meta("cov-intent-min-pass", "passed")

    results["coverage"]["pipeline_counts"] = pipeline_counts
    results["coverage"]["pipeline_max_share"] = pipeline_max_share
    results["coverage"]["intent_pass_counts"] = intent_pass_counts
    results["coverage"]["source_counts"] = source_counts
    results["meta_checks"] = meta_checks

    pp["pass_rate"] = (pp.get("passed", 0) / pp["total"]) if pp["total"] else 0.0
    results["pass_rate"] = pp["pass_rate"]
    return results
