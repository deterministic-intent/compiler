#!/usr/bin/env python3
"""
Audit battery: static compile, import smoke, script help, E2E0 smoke, and closure gates.

Includes:
- Language Tiers: report + verify_exists/executable/build_verified (policy-driven)
- Closure E2E Replay: verify_language_closure_e2e (dist artifacts + byte-identical replay for exists_languages)

Stops on first failing required check. No audit path skips closure checks unless explicitly "quick mode".
"""

import argparse
import os
import sys
import subprocess
from pathlib import Path
import json
import shutil

BASE = Path(__file__).resolve().parents[2]

# Pinned snapshot for Language Closure section. In v1 scope: MUST be set by run_proof.sh; no implicit fallback.
AUDIT_CLOSURE_SNAPSHOT = ""  # Set in main() after scope check
AUDIT_STATE_ROOT = None  # Set in main(); for --state-root (e.g. out/proof)
AUDIT_REQUESTS_DIR = None  # state_root/state/requests; set in main()


def _audit_policy() -> str:
    p = os.environ.get("AUDIT_POLICY", "v1")
    if "--policy" in sys.argv:
        i = sys.argv.index("--policy")
        if i + 1 < len(sys.argv):
            p = sys.argv[i + 1]
    return p


def run(cmd, cwd=None, allow_fail=False, env=None):
    """Run a command, stream output, return exit code."""
    print(f"\n$ {' '.join(cmd)}")
    p = subprocess.run(cmd, cwd=cwd or BASE, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if p.returncode != 0 and not allow_fail:
        print(f"FAIL: exit {p.returncode}")
        if p.stdout:
            print("STDOUT:", p.stdout, end="" if p.stdout.endswith("\n") else "\n")
        if p.stderr:
            print("STDERR:", p.stderr, end="" if p.stderr.endswith("\n") else "\n")
        sys.exit(p.returncode)
    return p.returncode


def compile_check():
    # Targeted compile to avoid vendor dirs
    targets = [
        "scripts",
        "workers",
        "orchestrator",
        "nlc",
        "policy",
        "dcs_cli",
    ]
    cmd = [sys.executable, "-m", "compileall", "-q"] + targets
    run(cmd)
    print("compileall: PASS")
    # Regression guard: intent builders must compile
    run([sys.executable, "scripts/verify_no_stale_executable_builder.py"])
    # PR0: Scope lock - reject PRs touching frozen v1 scope
    run([sys.executable, "scripts/verify_scope_lock_v1.py"])


def import_smoke():
    modules = [
        "workers.run_verifier",
        "workers.run_repair",
        "workers.run_planner",
        "nlc.prompt_compiler",
        "orchestrator.orchestrator",
        "nlc.reproducibility",
        "dcs_core.reproducibility",
        "dcs_core.repro_env",
        "dcs_cli.main",
    ]
    for mod in modules:
        run([sys.executable, "-c", f"import {mod}"])
    print("import smoke: PASS")


def help_smoke():
    """Run --help on all audit scripts. Phase 4/5 milestones have argparse so --help exits without full tests."""
    scripts = [
        ["scripts/build_snapshot_manifests.py", "--help"],
        ["scripts/build_index_db.py", "--help"],
        ["scripts/verify_step2.py", "--help"],
        ["scripts/verify_step4.py", "--help"],
        ["scripts/verify_step6.py", "--help"],
        ["scripts/verify_step7.py", "--help"],
        ["scripts/verify_step9.py", "--help"],
        ["scripts/verify_step10.py", "--help"],
        ["scripts/verify_step11.py", "--help"],
        ["scripts/verify_step12.py", "--help"],
        ["scripts/verify_step13.py", "--help"],
        ["scripts/verify_step16.py", "--help"],
        ["scripts/verify_step17.py", "--help"],
        ["scripts/verify_step18.py", "--help"],
        ["scripts/e2e/run_e2e0.py", "--help"],
        ["scripts/verify_milestone_4_0.py", "--help"],
        ["scripts/verify_milestone_4_1.py", "--help"],
        ["scripts/verify_milestone_4_2.py", "--help"],
        ["scripts/verify_milestone_5_0.py", "--help"],
        ["scripts/verify_milestone_5_1.py", "--help"],
        ["scripts/verify_milestone_5_2.py", "--help"],
        ["scripts/verify_milestone_5_5.py", "--help"],
    ]
    for s in scripts:
        run([sys.executable] + s)
    # CLI help smoke (must not enter REPL)
    run([str(BASE / "scripts" / "bin" / "dcs"), "--help"])
    run([str(BASE / "scripts" / "bin" / "dcs"), "compile", "--help"])
    print("help/usage: PASS")


def e2e_smoke():
    # E2E smoke: must PASS because Step 7/9 proofs depend on E2E0 artifacts.
    # Use AUDIT_CLOSURE_SNAPSHOT (has intents_executable + intents_v1) for module_refs resolution.
    snapshot = os.environ.get("NLC_DB_SNAPSHOT_ID") or AUDIT_CLOSURE_SNAPSHOT
    req_root = AUDIT_REQUESTS_DIR
    # Ensure clean E2E request dirs
    if req_root.exists():
        for p in req_root.glob("E2E0-*-AUDIT"):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
    cmd = [
        sys.executable,
        "scripts/e2e/run_e2e0.py",
        "--snapshot",
        snapshot,
        "--policy",
        "v1",
        "--request-id",
        "AUDIT",
        "--state-root",
        str(AUDIT_STATE_ROOT),
        "--e2e0-report",
        str(BASE / "out" / "e2e0_report.json"),
    ]
    run(cmd)
    print("E2E0 smoke: PASS (exit 0)")


def gate0_proof():
    # Gate0 must remain verifier-free: after gate0_init, no verifier dir should exist.
    snapshot = os.environ.get("NLC_DB_SNAPSHOT_ID") or AUDIT_CLOSURE_SNAPSHOT

    def _run_gate0(proof_req: str, env: dict) -> Path:
        proof_dir = AUDIT_REQUESTS_DIR / proof_req
        if proof_dir.exists():
            shutil.rmtree(proof_dir, ignore_errors=True)
        cmd = [
            sys.executable,
            "orchestrator/orchestrator.py",
            "gate0_init",
            proof_req,
            json.dumps("Make a CLI that counts from 1 to 2 by 1"),
            json.dumps([]),
            json.dumps([]),
            json.dumps([]),
        ]
        # gate0 may BLOCK; we assert invariants via artifacts
        run(cmd, allow_fail=True, env=env)
        return proof_dir

    def _print_proof(proof_dir: Path):
        payload = proof_dir / "payload.json"
        gate0_status = proof_dir / "gate0.status"
        gate0_result = proof_dir / "gate0.result.json"
        verifier_dir = proof_dir / "verifier"
        print("\n$ python3 -m json.tool \"$REQ/payload.json\" | sed -n '1,120p'")
        run([sys.executable, "-m", "json.tool", str(payload)])
        print("\n$ python3 -c 'import json; p=json.load(open(\"'\"$REQ/payload.json\"'\")); print(\"policy_version=\",p.get(\"policy_version\")); print(\"knowledge_snapshot_id=\",p.get(\"knowledge_snapshot_id\")); print(\"manifest_bundle_hash=\",p.get(\"manifest_bundle_hash\"))'")
        run(
            [
                sys.executable,
                "-c",
                "import json; p=json.load(open(r'{}')); print('policy_version=',p.get('policy_version')); print('knowledge_snapshot_id=',p.get('knowledge_snapshot_id')); print('manifest_bundle_hash=',p.get('manifest_bundle_hash'))".format(
                    str(payload)
                ),
            ]
        )
        print("\n$ test -d \"$REQ/verifier\" && echo VERIFIER_DIR_PRESENT || echo NO_VERIFIER_DIR")
        print("VERIFIER_DIR_PRESENT" if verifier_dir.exists() else "NO_VERIFIER_DIR")
        print("\n$ cat \"$REQ/gate0.status\"")
        print(gate0_status.read_text(encoding="utf-8").strip() if gate0_status.exists() else "MISSING")
        print("\n$ python3 -m json.tool \"$REQ/gate0.result.json\"")
        run([sys.executable, "-m", "json.tool", str(gate0_result)])

    # BLOCKED case: no snapshot env vars -> should BLOCK deterministically, still verifier-free
    env_blocked = os.environ.copy()
    env_blocked["NLC_REQUESTS_ROOT"] = str(AUDIT_REQUESTS_DIR)
    env_blocked.pop("NLC_DB_SNAPSHOT_ID", None)
    env_blocked.pop("NLC_SNAPSHOT_ID", None)
    env_blocked.pop("NLC_KB_SNAPSHOT_ID", None)
    blocked_dir = _run_gate0("G0-PROOF-BLOCKED", env_blocked)
    print(f"\nREQ={blocked_dir}")
    _print_proof(blocked_dir)
    if (blocked_dir / "verifier").exists():
        print(f"FAIL: Gate0 proof failed: verifier dir exists: {blocked_dir / 'verifier'}")
        sys.exit(1)
    if (blocked_dir / "gate0.status").read_text(encoding="utf-8").strip() != "BLOCKED":
        print("FAIL: Gate0 BLOCKED proof failed: expected gate0.status == BLOCKED")
        sys.exit(1)

    # PASS case: snapshot env vars set -> should PASS if snapshot manifests exist, still verifier-free
    env_pass = os.environ.copy()
    env_pass["NLC_REQUESTS_ROOT"] = str(AUDIT_REQUESTS_DIR)
    env_pass["NLC_DB_SNAPSHOT_ID"] = snapshot
    env_pass["NLC_SNAPSHOT_ID"] = snapshot
    env_pass["NLC_KB_SNAPSHOT_ID"] = snapshot
    pass_dir = _run_gate0("G0-PROOF-PASS", env_pass)
    print(f"\nREQ={pass_dir}")
    _print_proof(pass_dir)
    if (pass_dir / "verifier").exists():
        print(f"FAIL: Gate0 proof failed: verifier dir exists: {pass_dir / 'verifier'}")
        sys.exit(1)
    if (pass_dir / "gate0.status").read_text(encoding="utf-8").strip() != "PASS":
        print("FAIL: Gate0 PASS proof failed: expected gate0.status == PASS")
        sys.exit(1)
    # Assert required payload fields are present (non-null)
    pobj = json.loads((pass_dir / "payload.json").read_text(encoding="utf-8"))
    if not pobj.get("knowledge_snapshot_id") or not pobj.get("manifest_bundle_hash"):
        print("FAIL: Gate0 PASS proof failed: payload missing knowledge_snapshot_id or manifest_bundle_hash")
        sys.exit(1)

    print("Gate0 proof: PASS (verifier-free in both BLOCKED and PASS cases)")


def main():
    global AUDIT_CLOSURE_SNAPSHOT, AUDIT_STATE_ROOT, AUDIT_REQUESTS_DIR
    # Parse --state-root and --snapshot-id (optional; env takes precedence)
    i = 0
    state_root_arg = None
    snapshot_arg = None
    while i < len(sys.argv):
        if sys.argv[i] == "--state-root" and i + 1 < len(sys.argv):
            state_root_arg = sys.argv[i + 1]
            sys.argv.pop(i)
            sys.argv.pop(i)
        elif sys.argv[i] == "--snapshot-id" and i + 1 < len(sys.argv):
            snapshot_arg = sys.argv[i + 1]
            sys.argv.pop(i)
            sys.argv.pop(i)
        else:
            i += 1
    state_root = (state_root_arg or os.environ.get("DCS_PROOF_STATE_ROOT") or "").strip()
    if state_root:
        # Guard: inside container (workspace at /workspace) must not receive host path /opt/dcs-public
        if str(BASE).startswith("/workspace") and state_root.startswith("/opt/dcs-public"):
            sys.stderr.write("CONTAINER_HOST_PATH_FORBIDDEN\n")
            sys.exit(2)
        AUDIT_STATE_ROOT = Path(state_root).resolve()
        AUDIT_REQUESTS_DIR = AUDIT_STATE_ROOT / "state" / "requests"
        os.environ["NLC_REQUESTS_ROOT"] = str(AUDIT_REQUESTS_DIR)
    else:
        AUDIT_STATE_ROOT = BASE
        AUDIT_REQUESTS_DIR = BASE / "state" / "requests"

    # AUDIT_ENV=container|host (default host). No auto-fallback to dev policy.
    audit_env = os.environ.get("AUDIT_ENV", "host")
    # AUDIT_SCOPE=v1: v1 structured path only; skip Phase 4/5 (LLM, API, auth) outside v1 scope.
    audit_policy_val = _audit_policy()
    audit_scope = os.environ.get("AUDIT_SCOPE", "").strip().lower() or ("v1" if audit_policy_val == "v1" else "")
    # v1: require AUDIT_CLOSURE_SNAPSHOT from run_proof.sh; no implicit fallback (masks misconfiguration/drift).
    _is_v1 = audit_policy_val == "v1" or audit_scope == "v1"
    snap = (snapshot_arg or os.environ.get("AUDIT_CLOSURE_SNAPSHOT") or os.environ.get("DCS_PROOF_SNAPSHOT_ID") or "").strip()
    if _is_v1 and not snap:
        sys.stderr.write("FAIL: AUDIT_CLOSURE_SNAPSHOT is required in v1. Set via run_proof.sh or -e AUDIT_CLOSURE_SNAPSHOT=...\n")
        sys.exit(1)
    # No hardcoded snapshot fallback
    AUDIT_CLOSURE_SNAPSHOT = snap if snap else ""
    if not AUDIT_CLOSURE_SNAPSHOT:
        sys.stderr.write("FAIL: Snapshot ID required. Set AUDIT_CLOSURE_SNAPSHOT or DCS_PROOF_SNAPSHOT_ID or pass --snapshot-id.\n")
        sys.exit(1)
    # PR7: Ban AUDIT_ALLOW_MISSING_TOOLCHAINS for v1. No constrained path; support set must be truthful.
    if (audit_policy_val == "v1" or audit_scope == "v1") and os.environ.get("AUDIT_ALLOW_MISSING_TOOLCHAINS", "").strip().lower() in ("1", "true", "yes"):
        sys.stderr.write("POLICY.AUDIT.INVALID_ENV: AUDIT_ALLOW_MISSING_TOOLCHAINS is disallowed for v1 scope. Reclassify unsupported languages or install toolchains.\n")
        sys.exit(1)
    # v1 claim: skip Phase 4/5 (LLM, API, auth) - outside structured intake scope.
    # AUDIT_SCOPE=proof: run through step18 only, create proof_bundles, skip language tiers.
    _scope_proof = os.environ.get("AUDIT_SCOPE") == "proof"
    _skip_phase45 = (
        audit_policy_val == "v1"
        or os.environ.get("AUDIT_SCOPE") == "v1"
        or _scope_proof
        or ("--policy" in sys.argv and len(sys.argv) > sys.argv.index("--policy") + 1 and sys.argv[sys.argv.index("--policy") + 1] == "v1")
    )
    if audit_env == "container":
        print("=== Tier3 Audit (container mode) ===")
        rc = subprocess.call(
            [sys.executable, str(BASE / "scripts" / "run_tier3_audit_in_container.py")],
            cwd=BASE,
        )
        sys.exit(rc)

    print("=== Audit Battery ===")
    compile_check()
    # Build freeze hashes (single source of truth) then enforce
    run([sys.executable, "scripts/build_freeze_hashes_v1.py"])
    run([sys.executable, "scripts/verify_freeze_governance_v1.py"])
    # Repro surface: capture toolchain manifest for validation hashing
    run([sys.executable, "scripts/build_toolchain_manifest_v1.py"])
    import_smoke()
    help_smoke()
    e2e_smoke()
    gate0_proof()

    def _req_root_args():
        return ["--requests-root", str(AUDIT_REQUESTS_DIR)] if AUDIT_STATE_ROOT != BASE else []

    # Step 7 replay proof (requires E2E0 to have produced E2E0-B-AUDIT)
    run([sys.executable, "scripts/verify_step7.py", "E2E0-B-AUDIT", "gate3_execution"] + _req_root_args())

    # Step 9 proof: external input snapshotting + offline replay (must be deterministic).
    run([sys.executable, "scripts/verify_step9.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT, "--request-id", "STEP9-AUDIT"] + _req_root_args())

    # Step 10 proof: deterministic snapshot resolution + replay pinning.
    run([sys.executable, "scripts/verify_step10.py", "--knowledge-snapshot-id", AUDIT_CLOSURE_SNAPSHOT, "--request-id", "STEP10-AUDIT", "--external-snapshot-id", "STEP10-EXT-AUDIT", "--policy", "v1"] + _req_root_args())

    # Gate1 contract: snapshot_resolution.json required when gate1 completes (hard FAIL if missing unless SNAPSHOT_RESOLUTION_FAILED).
    run([sys.executable, "scripts/verify_gate1_writes_snapshot_resolution.py", "--request-id", "E2E0-B-AUDIT"] + _req_root_args())

    # Step 11 proof: deterministic index DB build + replay.
    run([sys.executable, "scripts/verify_step11.py", "--knowledge-snapshot-id", AUDIT_CLOSURE_SNAPSHOT, "--request-id", "STEP11-AUDIT", "--policy", "v1"] + _req_root_args())

    # Step 12 proof: deterministic answering via index-only planner.
    run([sys.executable, "scripts/verify_step12.py", "--knowledge-snapshot-id", AUDIT_CLOSURE_SNAPSHOT, "--request-id", "STEP12-AUDIT", "--policy", "v1"] + _req_root_args())

    # Step 13 proof: deterministic answer artifact + evidence lock.
    run([sys.executable, "scripts/verify_step13.py", "--knowledge-snapshot-id", AUDIT_CLOSURE_SNAPSHOT, "--request-id", "STEP13-AUDIT", "--policy", "v1"] + _req_root_args())

    # Step 16 proof: first real PASS usage with a non-example .dcs request.
    run([sys.executable, "scripts/verify_step16.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT, "--spec", "demo/real_pass.dcs"] + _req_root_args())

    # Step 17 proof: deterministic NL -> pinned .dcs intake compile (no gates).
    run([sys.executable, "scripts/verify_step17.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT, "--text", "build a python cli that counts from 1 to 5", "--out-a", "/tmp/step17_audit_a.dcs", "--out-b", "/tmp/step17_audit_b.dcs"])

    # Step 18 proof: full pipeline E2E (fetch once, then replay pinned + byte-identical).
    run([sys.executable, "scripts/verify_step18.py", "--knowledge-snapshot-id", AUDIT_CLOSURE_SNAPSHOT, "--request-id", "STEP18-E2E", "--policy", "v1"] + _req_root_args())

    # AUDIT_SCOPE=proof: create proof_bundle for requests with artifact.zip, then skip to end.
    if _scope_proof:
        run([sys.executable, "scripts/create_proof_bundle_if_missing.py"] + (["--requests-root", str(AUDIT_REQUESTS_DIR)] if AUDIT_STATE_ROOT != BASE else []))
        print("\n=== Audit (proof scope) completed through step18 ===")
        print("Audit battery completed.")
        return 0

    # Phase 4/5 (LLM, API, auth): outside v1 structured scope. Skip when policy=v1 (v1 claim path).
    phase45_scripts = [
        "verify_milestone_4_0.py",
        "verify_milestone_4_1.py",
        "verify_milestone_4_2.py",
        "verify_milestone_5_0.py",
        "verify_milestone_5_1.py",
        "verify_milestone_5_2.py",
        "verify_milestone_5_5.py",
    ]
    if _skip_phase45:
        sys.stderr.write("(Skipping Phase 4/5 milestones: v1 scope)\n")
        sys.stderr.flush()
    else:
        # Milestone 4.0 proof: LLM patch suggester (diff-only, replay-safe).
        run([sys.executable, "scripts/verify_milestone_4_0.py"])
        # Milestone 4.1 proof: Optional LLM intent proposals (deterministic acceptance).
        run([sys.executable, "scripts/verify_milestone_4_1.py"])
        # Milestone 4.2 proof: Runtime smoke validation + single-user acceptance pack.
        run([sys.executable, "scripts/verify_milestone_4_2.py"])
        # Milestone 5.0 proof: Job queue + isolation.
        run([sys.executable, "scripts/verify_milestone_5_0.py"])
        # Milestone 5.1 proof: API v1.
        run([sys.executable, "scripts/verify_milestone_5_1.py"])
        # Milestone 5.2 proof: Auth + permissions.
        run([sys.executable, "scripts/verify_milestone_5_2.py"])
        # Milestone 5.5 proof: One-command UX + proof bundle.
        run([sys.executable, "scripts/verify_milestone_5_5.py"])

    # Language tiers: report + tier gates (policy-driven).
    # Policy: AUDIT_POLICY=v1|dev (default v1). v1 = strict PASS-only; dev = allow SKIP.
    audit_policy = audit_policy_val
    if audit_policy not in ("v1", "dev"):
        print(f"WARN: AUDIT_POLICY={audit_policy} unknown, using v1")
        audit_policy = "v1"
    print(f"\n--- Language Tiers (policy={audit_policy}) ---")
    run([sys.executable, "scripts/toolchain/ensure_toolchains.py"])
    run([sys.executable, "scripts/report_language_closure.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT, "--policy", audit_policy])
    run([sys.executable, "scripts/verify_language_exists_closure.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT])
    run([sys.executable, "scripts/verify_language_executable_closure.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT])
    run([sys.executable, "scripts/verify_toolchains_ready.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT, "--policy", audit_policy])
    run([sys.executable, "scripts/verify_project_buildable.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT, "--policy", audit_policy])
    run([sys.executable, "scripts/verify_project_buildable_report_determinism.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT, "--policy", audit_policy])
    # PR14: validation hash stability across all 19 languages (hard fail on drift)
    run([sys.executable, "scripts/verify_validation_hash_stability_v1.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT])
    run([sys.executable, "scripts/verify_lockfile_policy.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT])
    run([sys.executable, "scripts/report_language_closure.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT, "--policy", audit_policy])
    run([sys.executable, "scripts/verify_language_build_verified.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT, "--policy", audit_policy])
    # PR11: Support set must be 19 languages. No runtime filtering. Hard-coded until governance changes.
    EXPECTED_SUPPORT_SET_SIZE = 19
    if audit_policy == "v1":
        closure_path = BASE / "nlc" / "db" / "snapshots" / AUDIT_CLOSURE_SNAPSHOT / "reports" / "language_closure.json"
        if closure_path.exists():
            clo = json.loads(closure_path.read_text(encoding="utf-8", errors="replace"))
            tier2 = clo.get("tier2_executable_languages", []) or []
            if len(tier2) != EXPECTED_SUPPORT_SET_SIZE:
                sys.stderr.write(
                    f"FAIL: Support set size must be {EXPECTED_SUPPORT_SET_SIZE}, got {len(tier2)}. "
                    "No runtime filtering allowed.\n"
                )
                sys.exit(1)
    run([sys.executable, "scripts/verify_language_emit_artifact_minimums.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT])
    run([sys.executable, "scripts/verify_factory_project_minimums.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT])
    run([sys.executable, "scripts/verify_capability_to_intent_conversion.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT])
    run([sys.executable, "scripts/verify_cross_machine_hash.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT])

    # Closure E2E Replay: dist artifacts + byte-identical replay for exists_languages.
    print("\n--- Closure E2E Replay ---")
    run([sys.executable, "scripts/verify_language_closure_e2e.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT])

    # Golden exec factory: 1 generate + 1 repair + 1 failure per language.
    print("\n--- Golden Exec Factory ---")
    run([sys.executable, "scripts/build_golden_exec_factory.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT])
    run([sys.executable, "scripts/verify_exec_factory.py", "--policy", audit_policy])

    # Patch determinism: PATCH.diff valid (lang_patch artifact class).
    run([sys.executable, "scripts/verify_patch_determinism.py", "--request-dir", str(BASE / "scripts" / "e2e" / "fixtures" / "lang_patch_request")])

    # v1 intake + IR + replay pin enforcement
    if audit_policy == "v1":
        print("\n--- v1 Pipeline Truth Report (PR1) ---")
        run([sys.executable, "scripts/report_pipeline_truth_v1.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT])
        print("\n--- v1 REQ Fixtures (19 languages from pipeline) ---")
        run([sys.executable, "scripts/build_intents_v1.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT, "--golden", str(BASE / "scripts" / "e2e" / "fixtures" / "golden_exec_factory.v1.json"), "--merge", str(BASE / "policy" / "intents_v1_baseline.json")])
        run([sys.executable, "scripts/build_req_fixtures_v1.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT, "--golden", str(BASE / "scripts" / "e2e" / "fixtures" / "golden_exec_factory.v1.json")])
        print("\n--- v1 Intake + IR + Replay Pins ---")
        run([sys.executable, "scripts/verify_cli_no_snapshot_fallback.py"])
        run([sys.executable, "scripts/verify_req_schema_strict.py", "--request-dir", str(BASE / "suites" / "v1" / "req_cases")])
        run([sys.executable, "scripts/verify_cli_structured_intake_failures.py"])
        run([sys.executable, "scripts/verify_network_guard_v1.py"])
        # Update validation_hashes.json to include all evidence artifacts
        ng_report = BASE / "out" / "network_guard_report.json"
        tc_manifest = BASE / "out" / "toolchain_manifest.json"
        repro_versions = BASE / "versions" / "repro_versions.json"
        freeze_manifest = BASE / "governance" / "freeze_manifest_v1.json"
        e2e0_report = BASE / "out" / "e2e0_report.json"
        vh_out = str(BASE / "nlc" / "db" / "snapshots" / AUDIT_CLOSURE_SNAPSHOT / "reports" / "validation_hashes.json")
        vh_cmd = [sys.executable, "scripts/run_validation_hashes_v1.py", "--snapshot-id", AUDIT_CLOSURE_SNAPSHOT, "--out", vh_out]
        if ng_report.exists():
            vh_cmd.extend(["--network-guard-report", str(ng_report)])
        if tc_manifest.exists():
            vh_cmd.extend(["--toolchain-manifest", str(tc_manifest)])
        if repro_versions.exists():
            vh_cmd.extend(["--repro-versions", str(repro_versions)])
        if freeze_manifest.exists():
            vh_cmd.extend(["--freeze-manifest", str(freeze_manifest)])
        if e2e0_report.exists():
            vh_cmd.extend(["--e2e0-report", str(e2e0_report)])
        run(vh_cmd)
        run([sys.executable, "scripts/fill_v1_signoff_attestation.py"])
        run([sys.executable, "scripts/verify_negative_intent_not_executable.py"])
        run([sys.executable, "scripts/verify_no_module_refs_injection.py"])
        run([sys.executable, "scripts/verify_manifest_has_repro_inputs.py", "--request-dir", str(AUDIT_REQUESTS_DIR), "--v1-only"])
        run([sys.executable, "scripts/verify_replay_enforces_req_byte_equality.py"])
        run([sys.executable, "scripts/smoke/test_v1_intent_req_equivalence.py"])
        run([sys.executable, "scripts/backfill_ir_schema_version.py", "--request-dir", str(AUDIT_REQUESTS_DIR)])
        run([sys.executable, "scripts/verify_ir_schema_strict.py", "--request-dir", str(AUDIT_REQUESTS_DIR)])
        run([sys.executable, "scripts/verify_clarify_contract.py"])
        run([sys.executable, "scripts/smoke/test_cli_intake_v1.py"])

    # Create proof_bundles for run_proof.sh hashing (v1 and proof scopes).
    run([sys.executable, "scripts/create_proof_bundle_if_missing.py"] + (["--requests-root", str(AUDIT_REQUESTS_DIR)] if AUDIT_STATE_ROOT != BASE else []))

    # Final v1 gate: evidence-derived signoff readiness (no boolean attestation bypass)
    if audit_policy == "v1":
        print("\n--- v1 Signoff Readiness (evidence-derived) ---")
        os.environ["AUDIT_CLOSURE_SNAPSHOT"] = AUDIT_CLOSURE_SNAPSHOT
        run([sys.executable, "scripts/verify_v1_signoff_ready.py"])

    # PR9: v1-only audit summary
    if _skip_phase45:
        closure_path = BASE / "nlc" / "db" / "snapshots" / AUDIT_CLOSURE_SNAPSHOT / "reports" / "language_closure.json"
        support_count = 0
        tier2_count = 0
        if closure_path.exists():
            try:
                clo = json.loads(closure_path.read_text(encoding="utf-8", errors="replace"))
                tier2_count = len(clo.get("tier2_executable_languages", []) or [])
                support_count = len(clo.get("tier3_build_verified_languages", []) or clo.get("tier2_executable_languages", []) or [])
            except Exception:
                pass
        print("\n=== v1 Audit Summary ===")
        print(f"  Snapshot ID: {os.environ.get('NLC_DB_SNAPSHOT_ID', '') or AUDIT_CLOSURE_SNAPSHOT}")
        print(f"  Closure snapshot: {AUDIT_CLOSURE_SNAPSHOT}")
        print(f"  Support set: {support_count} languages (tier2_executable: {tier2_count}, required: 19)")
        print("  Skipped (v1 scope): " + ", ".join(phase45_scripts))
        print("  Reason: Phase 4/5 (LLM, API, auth) outside v1 structured intake scope.")

    print("\nAudit battery completed.")


if __name__ == "__main__":
    main()

