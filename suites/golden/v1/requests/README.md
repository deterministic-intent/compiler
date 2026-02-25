# Golden Suite v1 (committed)

This directory is the sealed Golden Suite for v1 proof. It must be populated with REQ directories before CI passes.

Each REQ directory must contain:

- `payload.json`, `state.json`, gate status files, etc. (orchestrator state)
- `dist/artifact.zip` or `dist/site.zip` (deliverable)
- `dist/proof_bundle.zip` (proof bundle; required when artifact exists)

The suite is **read-only** during proof runs. Populate via:

```bash
# One-time bootstrap (needs snapshot - use proof kit or provision first)
PROOF_KIT_TAR=/path/to/dcs-v1-proof-kit-20260208T190113Z-*.tar.gz bash scripts/populate_golden_suite.sh

# Then commit and run proof
git add suites/golden/v1/requests/
git commit -m 'chore: populate Golden Suite v1'
DCS_SKIP_TIER3_BUILD=1 bash proof/run_proof.sh
```
