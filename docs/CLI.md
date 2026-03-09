# DCS CLI — Build Interface

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
