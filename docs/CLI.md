# DCS CLI Reference

Command-line interface for the Deterministic Compiler System.

## Installation

Install the `dcs` command (user-local, no sudo):

```bash
scripts/install_dcs.sh
```

This installs to `~/.local/bin/`. Ensure it is on your `PATH`.

Alternatively, use the repo shim directly: `./scripts/bin/dcs`

---

## Primary Interface

### `dcs build --req <REQ.json>`

Build from explicit REQ JSON file.

**Required:**
- `--req`: Path to `REQ.json` (valid req_v1 schema)

**Optional:**
- `--snapshot-id`: Snapshot ID (required if policy has no default)

**Outputs:**
- `dist/artifact.zip` or `dist/site.zip` on success
- `dist/proof_bundle.zip` on success

**Example:**
```bash
dcs build --req my_request.json --snapshot-id 20260215T120000Z
```

---

### `dcs build --intent <intent_id>`

Build from structured intent.

**Required:**
- `--intent`: Intent ID (e.g. `print_sequence`)
- `--lang`: Language (e.g. `python`)
- `--snapshot-id`: Snapshot ID

**Optional (intent-specific):**
- `--from`, `--to`, `--step` (for `print_sequence`)

**Example:**
```bash
dcs build --intent print_sequence --lang python --snapshot-id 20260215T120000Z --from 1 --to 5
```

---

## One-Command Interface

For interactive use, DCS supports a one-command flow:

```bash
$ dcs
Enter prompt: Make a CLI that counts from 1 to 5
request_id: COMPILED_ABC123...
status: PASS
artifact: ...
proof_bundle: ...
```

Or pipe input:

```bash
printf "Make a CLI that counts from 1 to 5\n" | dcs
```

Or run a `.dcs` spec file:

```bash
dcs my_request.dcs
```

The one-command interface:
- Compiles natural language to a `.dcs` file
- Runs the full pipeline (gates 0-6)
- Creates a proof bundle
- Prints: `request_id`, `status`, `artifact`, `proof_bundle`

---

## Subcommands

### `dcs run <spec.dcs>`

Run a `.dcs` spec file through the full pipeline.

```bash
dcs run examples/hello_world.dcs
```

### `dcs verify`

Verify a specific gate for a request.

```bash
dcs verify --request-id <id> --gate-name gate3
```

### `dcs replay`

Replay deterministically (no LLM, no network).

```bash
dcs replay --request-id <id> --gate-name gate3
```

Replay mode enforces:
- No LLM calls (cached artifacts only)
- No network access (all inputs pinned)
- No UX effects (banner, spinner disabled)
- Byte-identical outputs

### `dcs inspect`

Inspect request artifacts.

```bash
# Get last request ID
dcs inspect last

# Read file contents
dcs inspect cat --path <file>
```

### `dcs compile`

Compile natural language to a `.dcs` file without running the pipeline.

```bash
dcs compile "Make a Python CLI" --out request.dcs
```

### `dcs debug`

Generate a read-only debug report for a request.

```bash
dcs debug --request-id <id>
```

### `dcs capabilities`

Show supported capabilities for the current snapshot.

```bash
dcs capabilities
```

### `dcs doctor`

Run system diagnostics.

```bash
dcs doctor
```

---

## Error Codes

| Code | Meaning |
|------|---------|
| `DCS-E0001` | Bad arguments |
| `DCS-E1001` | Missing request |
| `DCS-E2001` | Gate failed |
| `DCS-E3001` | Clarification required (exit 12) |
| `DCS-E4001` | File not found |

---

## Schema Validation

REQ files must match `schemas/req_schema_v1.json`.

See `schemas/artifact_class_registry_v1.json` for admitted artifact classes.
