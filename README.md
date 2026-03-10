# Deterministic Compiler System (DCS)

A deterministic compiler that transforms structured requests into verified artifacts.

## What is DCS

DCS is a compiler system where:

- **Inputs are deterministic**: Requests (REQ) specify intent, language, and parameters
- **Outputs are reproducible**: The same REQ always produces the same artifact
- **Verification is built-in**: Every artifact passes machine-checkable verification
- **External generators are untrusted**: Only validated REQ specifications enter the deterministic pipeline

## Pipeline

```
REQ  →  IR  →  Artifact
```

A request (REQ) specifies intent, language, and parameters. The compiler transforms this into an internal representation (IR) bound to a snapshot-pinned manifest, then produces a verified artifact with a proof bundle.

## Usage

Build an artifact from a request specification:

```bash
dcs build --req request.json
```

Example request specifications are available in the `examples/` directory.

On success, DCS produces:

- `dist/artifact.zip` — the generated artifact
- `dist/proof_bundle.zip` — verification evidence

## Verification

DCS artifacts are reproducible. Given the same inputs and snapshot, any machine running the proof produces identical hashes.

To verify:

```bash
./scripts/proof/run_clean_proof_v1.sh
```

Expected hashes are in `dcs/expected_proof_hashes_v1.json`.

For independent verification instructions, see [docs/EXTERNAL_VERIFICATION.md](docs/EXTERNAL_VERIFICATION.md).

## Documentation

- [Whitepaper](docs/DCS_WHITEPAPER.md) — architecture and design principles
- [External Verification](docs/EXTERNAL_VERIFICATION.md) — independent proof reproduction
- [CLI Reference](docs/CLI.md) — command interface
- [Paths](docs/paths.md) — directory layout and conventions

## Implementation Status

This is the v1 implementation. The system supports:

- Structured intake via REQ.json
- Snapshot-pinned knowledge manifests
- Deterministic artifact generation
- Machine-checkable verification
- Reproducible proof bundles

See `governance/` for freeze manifests and version attestations.

## License

See [LICENSE](LICENSE).
