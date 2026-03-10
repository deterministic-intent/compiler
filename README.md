# Deterministic Compiler System (DCS)

A deterministic, reproducible pipeline for prompt compilation, knowledge management, code generation, verification, and automated repair.

## Overview

DCS is a deterministic compiler system that treats LLM interactions as untrusted adapters. The system enforces strict reproducibility, snapshot-based knowledge management, and automated repair loops with monotonic improvement guarantees.

## Repo Root Policy

The repository root contains only configuration files:

- `.gitignore` - Git ignore rules
- `.env.example` - Environment variable template
- `pyproject.toml` - Python project configuration
- `Dockerfile.tier3` - Deterministic build environment
- `README.md` - This file

All other code, scripts, and modules are organized under canonical directories (see Project Structure below).

## Quick Start

### One-Command Interface (Primary UX)

The simplest way to use DCS is the one-command interface:

```bash
# Enter your prompt and press Ctrl-D
$ dcs
Enter prompt:Make a CLI that counts from 1 to 5
request_id: COMPILED_ABC123...
status: PASS
artifact: state/requests/COMPILED_ABC123.../dist/artifact.zip
proof_bundle: state/requests/COMPILED_ABC123.../dist/proof_bundle.zip
```

Or pipe your prompt:

```bash
$ printf "Make a CLI that counts from 1 to 5\n" | dcs
```

Or run a `.dcs` file directly:

```bash
$ dcs my_request.dcs
```

The one-command interface automatically:
- Compiles your prompt to a `.dcs` file
- Runs the full pipeline (gates 0-6)
- Creates a proof bundle zip with all artifacts
- Prints exactly 4 lines: `request_id`, `status`, `artifact`, `proof_bundle`

### Advanced Usage

Install the canonical `dcs` command (user-local, no sudo):

```bash
scripts/install_dcs.sh
```

This installs `dcs` to `~/.local/bin/` (ensure it is on your `PATH`).

For more control, use the CLI subcommands. The repo shim is located at `scripts/bin/dcs`:

```bash
# Initialize a new request
./scripts/bin/dcs init <request_id> <objective> [constraints] [non-goals] [dod]

# Build snapshot manifests
./scripts/bin/dcs build <snapshot_id>

# Run full pipeline
./scripts/bin/dcs run <request_file.dcs>

# Verify artifacts
./scripts/bin/dcs verify <request_id>

# Repair on failure
./scripts/bin/dcs repair <request_id>

# Replay deterministically (no LLM, no network)
./scripts/bin/dcs replay <request_id> <gate_name>

# Inspect request artifacts
./scripts/bin/dcs inspect <request_id> [cat|list|last]

# Compile natural language to .dcs file
./scripts/bin/dcs compile "<natural language request>" --out <file.dcs>

# Debug report (read-only)
./scripts/bin/dcs debug --request-id <request_id>

# System diagnostics
./scripts/bin/dcs doctor
```

### Replay Mode (Deterministic)

Replay mode (`dcs replay`) enforces strict determinism:
- **No LLM calls** - Uses cached artifacts only
- **No network access** - All inputs must be pinned in snapshots
- **No UX effects** - Banner, spinner, and color are forcibly disabled
- **Byte-identical outputs** - Replay must produce identical verifier outputs

For independent replay instructions, see [docs/EXTERNAL_VERIFICATION.md](docs/EXTERNAL_VERIFICATION.md).

## Project Structure

### State Directories (Request-Scoped, Runtime)

These directories are created at runtime (not tracked in git):

- **`state/requests/<request_id>/`** - Request root (all deliverables live here)
  - `payload.json` - Request metadata and pinned snapshots
  - `REQ.json` - Compiled request (or `CLARIFY.json` if ambiguous)
  - `workspace/project/` - Generated project files
  - `dist/` - Packaged deliverables (`artifact.zip`, `checksums.sha256`, etc.)
  - `verifier/` - Verifier outputs (single-writer: `workers/run_verifier.py`)
    - `verifier.result.json` - Structured verdict
    - `failures.json` - Canonical failures
  - `repair/` - Repair trace (single-writer: `workers/run_repair.py`)
    - `status.json` - Repair loop status
    - `iter_<n>/` - Per-iteration artifacts
  - `planner/` - Planning artifacts (`SPEC.md`, `TASKS.json`, `PLAN.md`, `NEEDS.json`)
  - `answer/` - Deterministic answer artifact (`answer.json`)
  - `index/` - Request-local SQLite index DB (`index.db`, `index.sha256`)

### Knowledge Snapshots (Immutable)

- **`nlc/db/snapshots/<snapshot_id>/`** - Knowledge snapshot root
  - `nlc.db` - Snapshot database
  - `manifest/` - Snapshot manifests
    - `intents.json` - Intent registry
    - `templates.json` - DB-derived templates (empty if not in DB)
    - `modules.json` - Generator modules from `orchestrator/modules/`
    - `practices.json` - Practices (empty but valid)
    - `toolchain_pins.json` - Toolchain version pins
  - `capabilities.json` - Supported languages/artifact classes (if present)

### External Snapshots (Immutable Raw Inputs)

- **`snapshots/external/<snapshot_id>/`** - External data snapshot root
  - `sources/` - Raw source files (URLs, fetched content)
  - `sources.manifest.json` - Source manifest
  - `snapshot.meta.json` - Snapshot metadata

### Core Modules

- **`policy/`** - Policy spine (`policy.py`, `policy_v1.json`)
- **`nlc/`** - Core compiler logic
  - `nlc/prompt_compiler.py` - Prompt → REQ/CLARIFY
  - `nlc/paths.py` - Canonical path constants
  - `nlc/external_snapshot.py` - External snapshot writer
  - `nlc/snapshot_resolver.py` - Snapshot resolution & precedence
  - `nlc/reproducibility.py` - Manifest hashing & reproducibility metadata
- **`orchestrator/`** - Gate orchestration (`orchestrator.py`, `modules/`, `intent_emitters/`)
- **`workers/`** - Single-writer runners
  - `workers/run_planner.py` - Planning runner
  - `workers/run_generator.py` - Generator runner
  - `workers/run_verifier.py` - Verifier runner (sole writer of `verifier/`)
  - `workers/run_repair.py` - Repair runner (sole writer of `repair/`)
  - `workers/contract_checker.py` - Contract enforcement engine
- **`contracts/`** - Contract rules (`contract_rules.json`)
- **`scripts/`** - Proof harnesses & utilities
  - `scripts/bin/dcs` - CLI entrypoint
  - `scripts/run_replay.py` - Replay runner
  - `scripts/audit/` - Audit battery
  - `scripts/e2e/` - E2E test suite
  - `scripts/verify_*.py` - Step verification proofs

### Proof & Verification

- **`proof/`** - Proof execution scripts (`run_proof.sh`)
- **`dcs/`** - Expected proof hashes (`expected_proof_hashes_v1.json`)
- **`governance/`** - Freeze manifests and signoff attestations
- **`versions/`** - Reproducibility version pins (`repro_versions.json`)

## Features

- **Deterministic compilation** - Prompt → REQ with clarification artifacts
- **Snapshot-based knowledge** - Immutable, versioned knowledge snapshots
- **Structured verification** - Machine-consumable verifier outputs with canonical failures
- **Automated repair** - Bounded repair loop with monotonic improvement
- **Replay mode** - Byte-identical deterministic reproduction (no LLM, no network)
- **Contract enforcement** - Machine-checkable contract rules prevent drift
- **External snapshotting** - Deterministic raw input capture for offline replay

## Contributing

See the Project Structure section above for the canonical directory layout and entrypoints.
