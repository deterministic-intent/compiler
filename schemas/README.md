# DCS Public Schemas

Generated from live contract surfaces. **Do not hand-edit.** Regenerate with:

```bash
python3 scripts/build_public_schemas.py
```

## Files

| File | Source |
|------|--------|
| `req_schema_v1.json` | `schemas/req_v1.schema.json` |
| `artifact_class_registry_v1.json` | `contracts/v1_language_artifact_matrix.json` + module map |
| `artifact_classes/*.json` | Registry + `orchestrator/modules/*/project_v1.json` |
| `failure_id_registry_v1.json` | `workers/failure_canonicalizer.py` |

## Regeneration

Run after changing:
- REQ/IR schemas
- language/artifact matrix
- admitted modules
- failure taxonomy
