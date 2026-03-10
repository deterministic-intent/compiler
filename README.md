# Deterministic Compiler System (DCS)

A deterministic compiler that transforms structured requests into verified artifacts.

## What is DCS

DCS is a compiler system where:

- **Inputs are deterministic**: Requests (REQ) specify intent, language, and parameters
- **Outputs are reproducible**: The same REQ always produces the same artifact
- **Verification is built-in**: Every artifact passes machine-checkable verification
- **LLMs are untrusted adapters**: Generation is isolated; verification is authoritative

## Pipeline

```
REQ.json  →  IR (Internal Representation)  →  Artifact
   ↓              ↓                              ↓
intent        snapshot-pinned              verified output
params        manifest-bound               proof bundle
language      deterministic selection      checksums
```

## Usage

Build an artifact from a request specification:

```bash
dcs build --req request.json
```

The request file specifies intent, language, and parameters. On success, DCS produces:

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
