# Deterministic Compiler System (DCS) — Current State (nlc-v1.13.0)

## 1) What DCS Is (now)

DCS is a deterministic compiler system that converts natural language requests into verified, runnable software artifacts. The system enforces strict reproducibility, treats external model interactions as untrusted adapters, and provides automated repair with monotonic improvement guarantees.

The term "compiler" in DCS means: prompt parsing, knowledge-based planning, code generation, compilation validation, runtime smoke testing, verification, and optional automated repair. The output is a packaged artifact (e.g., `artifact.zip`) with checksums and entrypoint documentation.

Guarantees enforced today:
- Deterministic compilation: identical inputs produce identical intermediate artifacts
- Snapshot immutability: knowledge snapshots are read-only during request execution
- Knowledge-based planning: all planning decisions derive from snapshot-pinned knowledge database, not live lookups
- Single-writer artifacts: verifier, repair, and replay runners are the sole writers of their respective outputs
- Replay determinism: replay mode produces byte-identical outputs without external model calls or network access
- Runtime truth: produced artifacts are validated via runtime smoke tests (for supported artifact classes)
- Repair determinism: repair accept/reject decisions are deterministic and monotonic

## 2) Current Architecture

### CLI Entrypoints

Primary entrypoint: `scripts/bin/dcs`

Commands:
- `dcs compile "<text>"` - Compile natural language to `.dcs` request file
- `dcs run <file.dcs>` - Execute full pipeline (compile → plan → gen → verify → repair if needed)
- `dcs verify <request_id>` - Run verifier on existing request
- `dcs repair <request_id>` - Run repair loop (if verifier FAIL)
- `dcs replay <request_id> <gate>` - Replay deterministically (no external model, no network)
- `dcs inspect <request_id> [cat|list|last]` - Inspect request artifacts
- `dcs debug --request-id <request_id>` - Generate debug report

### Job Queue + Isolation Model

Job system location: `orchestrator/job_queue.py`, `orchestrator/job_runner.py`

Job submission: `submit_job(dcs_file, snapshot_id, policy_version)` returns deterministic `job_id`

Job execution: `run_job(job_id)` executes pipeline in isolated workspace under `state/jobs/<job_id>/workspace/`

Isolation guarantees:
- Per-job workspace: `state/jobs/<job_id>/workspace/requests/<request_id>/`
- No cross-job writes: isolation verification prevents writes outside job root
- Gate-mirrored state: job states mirror orchestrator gates (GATE0...GATEN, DONE, FAILED, CLARIFY, BLOCKED)
- Deterministic provenance: commands, exit codes, stdout/stderr hashes recorded per gate

### API v1 Surface

API server: `orchestrator/api_server.py`

Endpoints:
- `POST /v1/jobs` - Submit job (body: `request_text` or `dcs_content`, returns `job_id`)
- `POST /v1/jobs/{job_id}/run` - Run job (returns current state)
- `GET /v1/jobs/{job_id}` - Get job status (returns state, gate, artifact_paths)
- `GET /v1/jobs/{job_id}/download` - Download artifact zip (streams existing artifact, no recomputation)

Security:
- Path traversal prevention: `_safe_job_id()` validates job_id format
- Deterministic logging: all requests/responses logged to `state/api_logs/` with hashes
- No secrets in logs: default HTTP logging suppressed

### Verifier, Validation, Repair, Replay Roles

Verifier (`workers/run_verifier.py`):
- Single writer of `state/requests/<id>/verifier/verifier.result.json` and `failures.json`
- Structured outputs: canonical failure IDs, deterministic ordering, stable taxonomy
- Validation hooks: compile/test validation for artifact classes (Python: `py_compile`, `unittest`)
- Runtime smoke validation: for `python_cli`, runs `--help` and optional smoke args, records artifacts under `validation/runtime/`

Repair (`workers/run_repair.py`):
- Single writer of `state/requests/<id>/repair/` trace
- Triggers on verifier FAIL + policy enabled
- Bounded loop: policy-defined max iterations, budgets, scope allowlists
- Monotonic improvement: patch accepted only if failure score strictly decreases
- Atomic apply + rollback: workspace hashes recorded before/after, rollback on rejection
- model patch adapter: optional, diff-only, untrusted (recorded under `repair/iter_<n>/llm/`)

Replay (`scripts/run_replay.py`):
- Reads cached artifacts only (no external model calls, no network)
- Enforces snapshot/toolchain pin verification
- Produces byte-identical outputs to original run
- Replay clamp: no banner, spinner, color, or animation

### Knowledge Ingestion and Database Layer

Knowledge Database (KD):
- Location: `nlc/db/snapshots/<snapshot_id>/nlc.db` (SQLite)
- Contents: intents, templates, modules, practices, toolchain pins
- Properties: read-only during request execution, single-writer during snapshot build, hashed and manifest-locked
- Manifests: `nlc/db/snapshots/<snapshot_id>/manifest/` contains deterministic manifests derived from KD contents

Scraper and Ingestion Pipeline:
- Scrapers populate KD from language ecosystems, tooling documentation, and internal sources
- Scraper execution: `scraper/run_scrapers.py` (or equivalent entrypoints)
- External snapshots: scraper outputs captured as immutable external snapshots under `snapshots/external/<snapshot_id>/`
- Snapshot resolution: deterministic process (`nlc/snapshot_resolver.py`) that selects and orders multiple snapshot sources (external → knowledge → db)
- KD build: snapshot builder (`scripts/build_snapshot_manifests.py` or equivalent) creates KD snapshots from resolved sources
- Execution order: scrape → external snapshot → snapshot resolution → KD build → index → capabilities.json
- Scraper properties: offline-replayable, snapshot-pinned, never executed during request runs

Index DB (request-local):
- Each request builds a request-local SQLite index DB from the snapshot KD
- Location: `state/requests/<request_id>/index/index.db`
- Build process: `nlc/index/index_builder.py` reads only from snapshot KD and external snapshots
- Usage: planner and answerer read only from this index, no live DB access during planning or answering
- Schema: deterministic tables (`sources`, `documents`, `kv`, `fts_docs`) with stable IDs and hashes
- This enables "index-backed reasoning" where all planning decisions derive from snapshot-pinned knowledge

### State Locations

Request state: `state/requests/<request_id>/`
- `payload.json` - Request metadata, pinned snapshots, policy_version
- `REQ.json` - Compiled request (or `CLARIFY.json` if ambiguous)
- `workspace/project/` - Generated project files
- `dist/` - Packaged deliverables (`artifact.zip`, `checksums.sha256`, `ENTRYPOINT.md`)
- `verifier/` - Verifier outputs (single-writer)
- `repair/` - Repair trace (single-writer)
- `planner/` - Planning artifacts (`SPEC.md`, `TASKS.json`, `PLAN.md`, `NEEDS.json`)
- `answer/` - Deterministic answer artifact (`answer.json`)
- `index/` - Request-local SQLite index DB
- `validation/` - Validation artifacts (compile/test, runtime smoke)
- `llm_parse/` - external model parse adapter I/O (if used)
- `llm_parse_cache/` - external model parse cache

Job state: `state/jobs/<job_id>/`
- `job.json` - Job metadata, state transitions
- `request.dcs` - Submitted request file
- `workspace/requests/<request_id>/` - Isolated request execution
- `provenance/` - Per-gate provenance (commands, exit codes, hashes)

Knowledge snapshots: `nlc/db/snapshots/<snapshot_id>/`
- `nlc.db` - Snapshot database
- `manifest/` - Manifests (`intents.json`, `templates.json`, `modules.json`, `practices.json`, `toolchain_pins.json`)
- `capabilities.json` - Supported languages/artifact classes (if present)

External snapshots: `snapshots/external/<snapshot_id>/`
- `sources/` - Raw source files
- `sources.manifest.json` - Source manifest
- `snapshot.meta.json` - Snapshot metadata

API logs: `state/api_logs/` - Deterministic request/response logs with hashes

## 3) Proven Guarantees (with evidence types)

Deterministic replay:
- Evidence: `scripts/verify_step7.py`, `scripts/verify_step18.py`
- Enforcement: Replay runner refuses external model calls and network access, verifies snapshot/toolchain pins, produces byte-identical outputs

Artifact compilation validity:
- Evidence: `scripts/e2e/run_e2e0.py` (E2E0-A: PASS path)
- Enforcement: Verifier checks artifact presence, structure, compilation, tests

Runtime smoke execution:
- Evidence: `scripts/verify_milestone_4_2.py`
- Enforcement: Runtime validation artifacts under `validation/runtime/` (commands.json, stdout.txt, stderr.txt, exit_code.json, result.json)

Repair accept/reject determinism:
- Evidence: `scripts/verify_milestone_2_1.py`, `scripts/verify_step5a.py`
- Enforcement: Monotonic improvement gate, atomic apply/rollback, deterministic stop reasons

external model non-oracle behavior:
- Evidence: `scripts/verify_milestone_4_0.py`, `scripts/verify_milestone_4_1.py`
- Enforcement: external model adapters are diff-only (patch) or proposal-only (parse), verifier remains sole authority, model I/O recorded deterministically

Job isolation:
- Evidence: `scripts/verify_milestone_5_0.py`
- Enforcement: Isolation verification prevents cross-job writes, per-job workspace isolation

API determinism:
- Evidence: `scripts/verify_milestone_5_1.py`
- Enforcement: Deterministic job_id generation, request/response logging with hashes, artifact hash verification

Contract enforcement:
- Evidence: `scripts/verify_step6.py`
- Enforcement: Contract checker validates artifact presence, schemas, single-writer ownership, path policy

Snapshot resolution determinism:
- Evidence: `scripts/verify_step10.py`
- Enforcement: Deterministic ordering (external → knowledge → db), conflict handling, frozen snapshot set

Index-backed answering:
- Evidence: `scripts/verify_step12.py`, `scripts/verify_step13.py`
- Enforcement: Planner reads only from index DB, answer artifact built deterministically from evidence

Knowledge database determinism:
- Evidence: `scripts/verify_step9.py`, `scripts/verify_step10.py`, `scripts/verify_step11.py`
- Enforcement: Scrapers produce external snapshots deterministically, snapshot resolution is deterministic, index DB build is byte-identical from same inputs

## 4) What a User Can Do Today

Single-user CLI flow:
1. `dcs compile "Make a CLI that counts from 1 to 5"` → produces `request.dcs`
2. `dcs run request.dcs` → executes full pipeline, produces artifact in `state/requests/<id>/dist/`
3. `dcs inspect <request_id>` → view artifacts, status, gate results
4. `dcs debug --request-id <request_id>` → get debug report with failure classification

Multi-job flow:
1. Submit job via API: `POST /v1/jobs` with `request_text` or `dcs_content`
2. Run job: `POST /v1/jobs/{job_id}/run`
3. Check status: `GET /v1/jobs/{job_id}`
4. Download artifact: `GET /v1/jobs/{job_id}/download`

API usage:
- Submit jobs programmatically via REST API
- Query job status and artifact paths
- Download completed artifacts
- All API actions logged deterministically

Inspect, debug, replay:
- `dcs inspect <request_id> cat <file>` - View artifact contents
- `dcs inspect <request_id> list` - List all artifacts
- `dcs inspect <request_id> last` - Show last gate result
- `dcs debug --request-id <request_id>` - Generate debug report
- `dcs replay <request_id> <gate>` - Replay deterministically (no external model, no network)

Download artifacts:
- CLI: artifacts in `state/requests/<id>/dist/artifact.zip`
- API: `GET /v1/jobs/{job_id}/download` streams artifact zip
- Artifacts include: code, checksums, entrypoint documentation

## 5) What Is Explicitly NOT Implemented Yet

Authentication and authorization:
- No user authentication system
- No role-based access control
- No multi-tenant permissions
- API has no auth tokens (beyond basic validation)

Web UI:
- No web interface
- No dashboard
- No visual job monitoring
- CLI and API only

Distributed workers:
- No worker pool management
- No job scheduling/queuing beyond basic submission
- No load balancing
- Jobs run in-process

SLA and quotas:
- No enforced time limits (beyond policy-defined repair budgets)
- No disk quota enforcement (beyond basic isolation)
- No rate limiting on API
- No priority queues

Advanced features:
- No multi-artifact builds
- No artifact dependencies
- No incremental compilation
- No cross-request caching beyond external model adapters

## 6) Current Version Line

Latest tag: `nlc-v1.13.0`

Completed phases:
- Phase 1: Policy spine, snapshot manifests, deterministic selection, structured verifier, repair loop, contract enforcement, replay, external snapshots, snapshot resolution, index DB, index-backed answering, answer artifact
- Phase 2: DCS CLI productization, human interface validation, first real PASS usage, natural-language compiler, full pipeline E2E harness
- Phase 3: Compile/test validation, debug report UX, contract cleanup
- Phase 4: external model as patch suggester (diff-only), optional external model intent proposals, runtime smoke validation, single-user acceptance pack
- Phase 5: Job queue + isolation, API v1

System stops at:
- Multi-user backend with job queue and API v1
- Runtime smoke validation for python_cli
- Deterministic repair loop with model patch adapter
- Replay mode with byte-identical guarantees
- Single-user and multi-job workflows via CLI and API

