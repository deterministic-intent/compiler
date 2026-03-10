# BLOCKED reason codes (deterministic contract)

 This file is part of the public surface area: it defines what a BLOCKED outcome means and what fields MUST appear in BLOCKED.json for each reason_code.

 Rule: the compiler never guesses. If required information cannot be extracted deterministically, it MUST BLOCK with one of these reason codes.


## Runtime invalid input classification (frozen)

- Treat runtime-invalid inputs as BLOCKED, not as a separate FAILED_EXPECTED bucket.
- The compiler should reject and emit a deterministic reason_code rather than letting the runtime fail nondeterministically.
- We do not model a FAILED_EXPECTED outcome in the taxonomy.

## Common envelope (always)

`BLOCKED.json` MUST contain:

- `status`: `"BLOCKED"`
- `reason_code`: one of the codes below
- `prompt`: original prompt text

It MAY contain:

- `details`: an object with deterministic structured fields (required for some reasons)

## `UNSUPPORTED_INTENT`

Used when the requested behavior is out-of-scope for the current deterministic intent set,
or when a pipeline composition is not supported (including type mismatches).

`details` MAY include:

- `detail`: `"TYPE_MISMATCH"`
- `intent_type`: the intent/stage that could not be applied
- `expects`: list of supported input types
- `got`: the detected upstream type

## `MISSING_REQUIRED_PARAM`

Used when a required parameter exists in the intent schema but is not explicitly extractable.

`details` MUST include:

- `missing`: list of missing parameter keys (e.g. `["substring"]`, `["numbers"]`)

## `AMBIGUOUS_INTENT`

Used when multiple conflicting interpretations exist (e.g., multiple output formats requested,
or mutually incompatible numeric operations requested).

`details` MAY include:

- `detail`: free-form deterministic string describing the ambiguity

## `AMBIGUOUS_PARAM`

Used when multiple candidate values exist for a required parameter (especially file paths)
and the prompt does not disambiguate.

`details` MUST include:

- `param`: the parameter name (currently `"file_path"`)
- `role`: `"read"` or `"write"`
- `candidates`: list of candidate values in deterministic order

## `RUNTIME_INVALID_INPUT`

Used when runtime input is structurally invalid (e.g., invalid JSON for a pretty-print intent).
The system rejects deterministically rather than guessing.

`details` MAY include:

- `detail`: deterministic string describing the validation failure
- `context`: optional structured fields (e.g., `{"kind": "json", "error": "Expecting value"}`)


