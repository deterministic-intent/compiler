#!/usr/bin/env python3
"""
Generate public schema surface from live contract sources.
Run from repo root. Outputs to schemas/ and docs/.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SCHEMAS = BASE / "schemas"
DOCS = BASE / "docs"


def _load_json(p: Path) -> dict:
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def _write_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def build_req_schema() -> None:
    """REQ schema: canonical copy of req_v1.schema.json."""
    src = BASE / "schemas" / "req_v1.schema.json"
    dst = SCHEMAS / "req_schema_v1.json"
    data = _load_json(src)
    data["$id"] = "req_schema_v1"
    data["description"] = "DCS REQ v1 schema. Canonical public copy of req_v1.schema.json."
    _write_json(dst, data)
    print(f"  {dst.relative_to(BASE)}")


def build_artifact_class_registry() -> None:
    """Artifact class registry from matrix + module_ref map."""
    matrix = _load_json(BASE / "contracts" / "v1_language_artifact_matrix.json")
    mapping: dict[str, list[str]] = matrix.get("mapping", {})

    # Invert: artifact_class -> [languages]
    ac_to_langs: dict[str, list[str]] = {}
    for lang, classes in mapping.items():
        for ac in classes:
            ac_to_langs.setdefault(ac, []).append(lang)

    # Module ref from generate_golden_suite_v1.py _MAP
    MODULE_REF: dict[str, str] = {
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

    registry = {
        "schema_version": "v1",
        "description": "Generated from contracts/v1_language_artifact_matrix.json and admitted modules.",
        "artifact_classes": []

    }
    for ac in sorted(ac_to_langs.keys()):
        langs = sorted(ac_to_langs[ac])
        registry["artifact_classes"].append({
            "artifact_class": ac,
            "supported_languages": langs,
            "status": "admitted",
            "module_ref": MODULE_REF.get(ac, f"{ac}/project_v1.json"),
            "spec_path": f"schemas/artifact_classes/{ac}.json",
        })
    _write_json(SCHEMAS / "artifact_class_registry_v1.json", registry)
    print(f"  {SCHEMAS / 'artifact_class_registry_v1.json'}")


def build_artifact_class_specs() -> None:
    """Per-artifact-class parameter specs."""
    registry = _load_json(SCHEMAS / "artifact_class_registry_v1.json")
    classes_dir = SCHEMAS / "artifact_classes"
    classes_dir.mkdir(parents=True, exist_ok=True)

    # Load docker_image if present (only module with project_v1.json)
    docker_spec = BASE / "orchestrator" / "modules" / "docker_image" / "project_v1.json"
    docker_extra = _load_json(docker_spec) if docker_spec.exists() else {}

    for entry in registry["artifact_classes"]:
        ac = entry["artifact_class"]
        langs = entry["supported_languages"]
        module_ref = entry["module_ref"]

        spec = {
            "artifact_class": ac,
            "schema_version": "v1",
            "required_parameters": ["artifact_class", "language", "module_refs"],
            "optional_parameters": ["goal", "constraints", "non_goals", "inputs"],
            "parameter_types": {
                "artifact_class": "string",
                "language": "string",
                "module_refs": "array of strings",
                "goal": "string",
                "constraints": "array of strings",
                "non_goals": "array of strings",
                "inputs": "object",
            },
            "allowed_values": {
                "artifact_class": [ac],
                "language": langs,
            },
            "validation_rules": [
                "artifact_class must match this spec",
                "language must be in supported_languages",
                "module_refs must include the module_ref for this class",
            ],
            "module_ref": module_ref,
            "supported_languages": langs,
            "example": {
                "schema_version": "req_v1",
                "intents": [{
                    "intent_type": "generate",
                    "params": {
                        "artifact_class": ac,
                        "language": langs[0] if langs else "python",
                        "module_refs": [module_ref],
                    },
                }],
            },
        }
        if ac == "docker_image" and docker_extra:
            spec["deliverables"] = docker_extra.get("deliverables", [])
            spec["description"] = docker_extra.get("description", "")
        _write_json(classes_dir / f"{ac}.json", spec)
    print(f"  {classes_dir}/")


def build_failure_id_registry() -> None:
    """Failure ID registry from failure_canonicalizer."""
    sys.path.insert(0, str(BASE))
    from workers.failure_canonicalizer import FailureKind, FailureSeverity, compute_failure_id

    kinds = [
        {"id": k.value, "meaning": k.name.replace("_", " ").lower(), "typical_trigger": _trigger(k.value)}
        for k in FailureKind
    ]
    severities = [{"id": s.value} for s in FailureSeverity]

    # Known stable IDs (not computed)
    stable_ids = [
        {"id": "UNDECLARED_ARTIFACT_CLASS", "kind": "policy_violation", "meaning": "artifact_class not in snapshot supported_artifact_classes", "typical_trigger": "Request uses unsupported artifact_class"},
        {"id": "TOOLCHAIN_VERIFY_FAILED", "kind": "verifier_error", "meaning": "Toolchain verification failed", "typical_trigger": "verify_toolchains_ready.py"},
        {"id": "TOOLCHAIN_POLICY_INVALID", "kind": "policy_violation", "meaning": "Invalid toolchains policy", "typical_trigger": "Invalid policy/toolchains_v1.json"},
        {"id": "TOOLCHAIN_POLICY_MISSING", "kind": "policy_violation", "meaning": "Toolchain policy files missing", "typical_trigger": "policy/toolchains_v1.json not found"},
        {"id": "TOOLCHAIN_POLICY_EMPTY", "kind": "policy_violation", "meaning": "No tools defined in policy", "typical_trigger": "Empty toolchains config"},
        {"id": "FAILURE_SIGNATURE: MISSING_DOM_MANIPULATION", "kind": "contract_violation", "meaning": "DOM manipulation missing in web artifact", "typical_trigger": "javascript_web artifact"},
        {"id": "FAILURE_SIGNATURE: MISSING_CLI_PARSER", "kind": "contract_violation", "meaning": "CLI argument parser missing", "typical_trigger": "CLI artifact"},
        {"id": "FAILURE_SIGNATURE: MISSING_API_FRAMEWORK", "kind": "contract_violation", "meaning": "API framework missing", "typical_trigger": "python_api artifact"},
        {"id": "FAILURE_SIGNATURE: MISSING_ROUTES", "kind": "contract_violation", "meaning": "API routes missing", "typical_trigger": "API artifact"},
        {"id": "FAILURE_SIGNATURE: MISSING_GUI_FRAMEWORK", "kind": "contract_violation", "meaning": "GUI framework missing", "typical_trigger": "python_gui artifact"},
    ]
    for lang in ["python", "typescript", "php", "ruby", "c", "cpp", "csharp", "kotlin", "solidity", "docker", "sql", "mongodb", "html", "yaml"]:
        stable_ids.append({
            "id": f"TOOLCHAIN_{lang.upper()}_MISSING",
            "kind": "verifier_error",
            "meaning": f"{lang} toolchain binary not found",
            "typical_trigger": "verify_toolchains_ready.py",
        })

    registry = {
        "schema_version": "v1",
        "description": "Generated from workers/failure_canonicalizer.py. Dynamic IDs use compute_failure_id.",
        "failure_kinds": kinds,
        "severities": severities,
        "stable_ids": stable_ids,
        "computation_rule": {
            "formula": "sha256(kind:artifact:locator:repro:expected_hash:actual_hash:message_norm)[:32]",
            "inputs": ["kind", "artifact", "locator", "repro", "message", "expected", "actual"],
            "source": "workers.failure_canonicalizer.compute_failure_id",
        },
    }
    _write_json(SCHEMAS / "failure_id_registry_v1.json", registry)
    print(f"  {SCHEMAS / 'failure_id_registry_v1.json'}")


def _trigger(k: str) -> str:
    triggers = {
        "compile_error": "Build/compile step failed",
        "test_failure": "Test execution failed",
        "snapshot_diff": "Output differs from expected snapshot",
        "contract_mismatch": "Contract mismatch",
        "contract_violation": "Contract rule violated",
        "policy_violation": "Policy rule violated",
        "type_error": "Type check failed",
        "lint_error": "Linter reported error",
        "runtime_exception": "Runtime exception",
        "verifier_error": "Verifier internal error",
        "external_input_violation": "External input validation failed",
        "snapshot_violation": "Snapshot integrity violated",
        "index_violation": "Index violation",
        "planner_violation": "Planner violation",
        "answer_violation": "Answer validation failed",
    }
    return triggers.get(k, "See failure message")


def build_cli_docs() -> None:
    """Minimal CLI docs."""
    content = """# DCS CLI — Build Interface

Minimal public surface for external tools invoking DCS.

## Required

- `dcs` CLI installed (e.g. `scripts/install_dcs.sh`)
- Snapshot provisioned (see repo docs)

---

## `dcs build --req <REQ.json>`

Build from explicit REQ JSON file.

**Required:**
- `--req`: Path to `REQ.json` (valid req_v1 schema)

**Optional:**
- `--snapshot-id`: Snapshot ID (required if policy has no default)

**Expected outputs:**
- Request directory under `state/requests/<request_id>/`
- `dist/artifact.zip` or `dist/site.zip` on success
- `dist/proof_bundle.zip` on success

**Failure behavior:**
- Exit non-zero on validation failure, gate failure, or verifier failure
- Emits to stderr: `DCS-E0001` (bad args), `DCS-E4001` (file not found)

**Example:**
```bash
dcs build --req my_request.json --snapshot-id 20260215T120000Z
```

---

## `dcs build --intent <intent_id>`

Build from structured intent.

**Required:**
- `--intent`: Intent ID (e.g. `print_sequence`, `count_lines`)
- `--snapshot-id`: Snapshot ID (mandatory for --intent)

**Optional:**
- `--lang`: Language (e.g. `python`, `go`)
- Intent-specific params: `--from`, `--to`, `--step` (for print_sequence)

**Expected outputs:**
- Same as `--req` path

**Failure behavior:**
- Exit non-zero if snapshot not found or intent not routable
- Emits `DCS-E0001` for invalid args

**Example:**
```bash
dcs build --intent print_sequence --lang python --snapshot-id 20260215T120000Z --from 1 --to 5
```

---

## Schema validation

REQ files must match `schemas/req_schema_v1.json`. See `schemas/artifact_class_registry_v1.json` for admitted artifact classes.
"""
    (DOCS / "CLI.md").write_text(content, encoding="utf-8")
    print(f"  {DOCS / 'CLI.md'}")


def main() -> int:
    print("Building public schemas...")
    build_req_schema()
    build_artifact_class_registry()
    build_artifact_class_specs()
    build_failure_id_registry()
    build_cli_docs()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
