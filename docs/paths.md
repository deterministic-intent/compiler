# DCS Paths and Directory Layout

Canonical paths and directory conventions for v1.

---

## Repository Structure

```
dcs-public/
├── contracts/        # Contract rules
├── dcs/              # Expected proof hashes
├── dcs_cli/          # CLI implementation
├── dcs_core/         # Core utilities
├── docs/             # Documentation
├── examples/         # Example requests
├── governance/       # Freeze manifests, attestations
├── infra/            # Infrastructure configs
├── nlc/              # Normalized Logic Corpus (see below)
├── orchestrator/     # Gate orchestration
├── policy/           # Policy spine
├── proof/            # Proof execution scripts
├── schemas/          # JSON schemas
├── scripts/          # Utilities, verification proofs
├── suites/           # Test fixtures
├── tests/            # Unit tests
├── verifier/         # Verification logic
├── versions/         # Reproducibility pins
└── workers/          # Single-writer runners
```

---

## NLC — Normalized Logic Corpus

The `nlc/` directory contains the **Normalized Logic Corpus**: immutable snapshots, intent registries, capability definitions, and compiler logic that the deterministic pipeline consumes.

| Path | Purpose |
|------|---------|
| `nlc/db/snapshots/` | Versioned knowledge snapshots (immutable) |
| `nlc/registry/v1/intents/` | Intent definitions (print_sequence, count_lines, etc.) |
| `nlc/prompt_compiler.py` | REQ compilation logic |
| `nlc/capability_classifier.py` | Artifact class classification |
| `nlc/snapshot_resolver.py` | Snapshot resolution and precedence |
| `nlc/clarification.py` | CLARIFY artifact generation |
| `nlc/index/` | Request-local index builder and query |

The corpus is **read-only at runtime**. All writes go to `state/` (request artifacts) or `out/` (proof outputs).

---

## Root Files

| File | Purpose |
|------|---------|
| `.gitignore` | Git ignore rules |
| `.env.example` | Environment variable template |
| `pyproject.toml` | Python project configuration |
| `Dockerfile.tier3` | Deterministic build environment |
| `LICENSE` | License file |
| `README.md` | Project overview |

---

## Runtime Directories

These directories are created at runtime and are not tracked in git.

### Request State

```
state/requests/<request_id>/
├── payload.json              # Request metadata, pinned snapshots
├── REQ.json                  # Compiled request
├── CLARIFY.json              # (if ambiguous)
├── workspace/project/        # Generated project files
├── dist/
│   ├── artifact.zip          # Packaged deliverable
│   ├── proof_bundle.zip      # Verification evidence
│   └── checksums.sha256      # Artifact checksums
├── verifier/
│   ├── verifier.result.json  # Structured verdict
│   └── failures.json         # Canonical failures
├── repair/
│   ├── status.json           # Repair loop status
│   └── iter_<n>/             # Per-iteration artifacts
├── planner/                  # Planning artifacts
├── answer/                   # Answer artifact
└── index/                    # Request-local index DB
```

### Intake

```
state/intake/
└── prompt_<sha256>.dcs       # Compiled .dcs files from natural language
```

---

## Knowledge Snapshots

Immutable, versioned snapshots under `nlc/db/snapshots/`:

```
nlc/db/snapshots/<snapshot_id>/
├── DB_SNAPSHOT.sha256        # Snapshot hash
├── capabilities.json         # Supported languages/artifact classes
├── manifest/
│   ├── intents.json          # Intent registry
│   ├── templates.json        # DB-derived templates
│   ├── modules.json          # Generator modules
│   ├── practices.json        # Practices
│   └── toolchain_pins.json   # Toolchain version pins
└── reports/
    └── validation_hashes.json
```

---

## Core Module Paths

| Path | Purpose |
|------|---------|
| `scripts/bin/dcs` | CLI entrypoint |
| `scripts/run_replay.py` | Replay runner |
| `workers/run_generator.py` | Generator runner |
| `workers/run_verifier.py` | Verifier runner |
| `workers/run_repair.py` | Repair runner |
| `workers/contract_checker.py` | Contract enforcement |
| `nlc/paths.py` | Path constants |
| `nlc/prompt_compiler.py` | Prompt → REQ compiler |
| `nlc/snapshot_resolver.py` | Snapshot resolution |
| `orchestrator/orchestrator.py` | Gate orchestration |

---

## Proof and Governance

| Path | Purpose |
|------|---------|
| `proof/run_proof.sh` | CI proof script |
| `scripts/proof/run_clean_proof_v1.sh` | Local clean proof |
| `dcs/expected_proof_hashes_v1.json` | Expected proof hashes |
| `governance/` | Freeze manifests, signoff attestations |
| `versions/repro_versions.json` | Reproducibility version pins |
