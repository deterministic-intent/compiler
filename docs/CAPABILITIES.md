# CAPABILITIES (deterministic “supported intent language”)

 This document is authoritative: if a prompt falls outside these patterns, the compiler MUST deterministically BLOCK (it will not guess).

## General rules

- **No guessing**: required params must be explicitly present (e.g. quoted substrings).
- **Deterministic ambiguity handling**: if multiple candidates exist, the compiler blocks.
- **Pipeline intent**: if the prompt describes a multi-step transform, the compiler emits
  a multi-intent `REQ.json` and codegen emits a single `run` command.

## `stdin_support`

**Meaning**: input comes from standard input.

**Supported phrases** (examples):
- “stdin”, “standard input”, “from stdin”, “pipe”, “piped”

**Emitted params**:
- `read_mode="lines"` (only mode currently supported in pipelines)

## `read_lines`

**Meaning**: read lines from a text file.

**Required params**:
- `file_path` (must be unambiguous)

**Supported phrases**:
- “read lines from input.txt”

**Blocking**:
- If multiple candidate file paths exist and input path is not disambiguated → `AMBIGUOUS_PARAM`.

## `write_lines`

**Meaning**: write lines to a text file.

**Required params**:
- `file_path` (must be unambiguous)

**Supported phrases**:
- “write to output.txt”, “save to output.txt”, “output to output.txt”

**Blocking**:
- If multiple candidate file paths exist and output path is not disambiguated → `AMBIGUOUS_PARAM`.

## `filter_contains`

**Meaning**: keep items whose text contains a substring.

**Required params**:
- `substring` **must be quoted** (e.g. `"error"` or `'WA'`)

**Supported pipeline input types**:
- `lines`: substring match against the line
- `csv_rows`: substring match against “any field” in the row (fields joined with spaces)

**Blocking**:
- If substring not explicitly quoted → `MISSING_REQUIRED_PARAM` with `details.missing=["substring"]`
- If upstream type is not supported → `UNSUPPORTED_INTENT` with `details.detail="TYPE_MISMATCH"`

## `unique`

**Meaning**: remove duplicates.

**Supported pipeline input types**:
- `lines` (preserves first occurrence order)
- `csv_rows` (dedupe by row tuple, preserves first occurrence order)

**Supported phrases**:
- “remove duplicates”, “dedupe”, “unique”, “preserving order”

**Blocking**:
- “sorted unique” on line pipelines → `AMBIGUOUS_INTENT` (explicitly not supported)

## `count_lines`

**Meaning**: count the number of lines from a text source.

**Supported phrases**: “count lines”, “line count”, “number of lines”.

**Consumes**: `lines`

**Produces**: `numbers`

**Blocking**:
- Missing source → `MISSING_REQUIRED_PARAM`
- Conflicting outputs (json + csv) → `AMBIGUOUS_INTENT`

## `json_pretty_print`

**Meaning**: pretty print JSON with fixed indentation.

**Supported phrases**: “pretty print json”, “format json”, “prettify json”.

**Consumes**: `lines` (raw JSON text)

**Produces**: `lines` (pretty JSON text)

**Blocking**:
- Missing source → `MISSING_REQUIRED_PARAM`
- Invalid JSON → `RUNTIME_INVALID_INPUT`
- Conflicting outputs → `AMBIGUOUS_INTENT`

## `grep_regex`

**Meaning**: filter lines by a regex pattern.

**Requirements**:
- Explicit regex delimiters `/pattern/` (single pattern only).
- Explicit source: stdin or file (`read_lines`).

**Flags**:
- `/.../i` or “case-insensitive” → `ignore_case=true`

**Consumes**: `lines`

**Produces**: `lines` (matching lines, order preserved)

**Blocking**:
- Missing/ambiguous pattern → `MISSING_REQUIRED_PARAM` or `AMBIGUOUS_PARAM`
- Missing source → `MISSING_REQUIRED_PARAM`
- Type mismatch → `UNSUPPORTED_INTENT`
- Invalid regex at runtime → `RUNTIME_INVALID_INPUT` (exit code 2)

## `csv_select_columns`

**Meaning**: select explicit columns from CSV rows.

**Requirements**:
- Explicit column list and explicit CSV source (`csv_read`).
- Explicit output (csv_write or output_format=csv).
- `has_header=true` → columns must be names (exact match).
- `has_header=false` → columns must be 0-based indices.

**Consumes**: `csv_rows`

**Produces**: `csv_rows`

**Blocking**:
- Missing/ambiguous columns or source → `MISSING_REQUIRED_PARAM` / `AMBIGUOUS_INTENT`
- Header/name/index mismatch → `MISSING_REQUIRED_PARAM`
- Unknown column name or index out of range → `RUNTIME_INVALID_INPUT`

## `output_format`

**Meaning**: format output to stdout.

**Supported formats**:
- `json`, `csv`, `text`

**Output format is only recognized in an output context**:
- “outputs json”, “output as json”, “format json”, “in json”, etc.

**Blocking**:
- If multiple output formats are requested → `AMBIGUOUS_INTENT`

## `csv_read`

**Meaning**: read rows from a CSV file.

**Required params**:
- `file_path` (must be unambiguous)

**Produces**:
- `csv_rows` (header is skipped if present)

## `csv_write`

**Meaning**: write CSV rows to a CSV file.

**Required params**:
- `file_path` (must be unambiguous)

**Consumes**:
- `csv_rows`

## `parse_numbers`

**Meaning**: parse lines (strings) to numbers (int/float). Used in pipelines when numeric operations are requested on stdin/file input.

**Consumes**:
- `lines` (from `stdin_support` or `read_lines`)

**Produces**:
- `numbers` (list of int/float)

**Strict policy**: Any non-empty, non-numeric line causes the CLI to exit with code 2 and an error message. Empty lines are skipped. This enforces deterministic behavior: bad input is explicitly rejected rather than silently ignored.

**Blocking**:
- If input type is not `lines` → `UNSUPPORTED_INTENT` with `TYPE_MISMATCH`
- If any non-empty line cannot be parsed as a number → CLI exits with code 2 (runtime blocking)

**Supported phrases**:
- Automatically inserted in pipelines: "reads numbers from stdin/file, sorts/stats, outputs json"

## `sort_numbers` (inline numbers)

**Meaning**: sort explicitly provided numbers.

**Supported phrases**:
- “sort numbers 3 1 2”, optional “descending/reverse”

**Blocking**:
- If no explicit numbers are present → `MISSING_REQUIRED_PARAM` with `details.missing=["numbers"]`

## `parse_numbers` (lines → numbers)

**Meaning**: extract integers from textual input (stdin/read_lines) for numeric pipelines.

**Supported phrases**:
- “parse numbers from stdin”, “extract numbers”, “numbers to json”

**Consumes / Produces**:
- Consumes: `lines`
- Produces: `numbers`

**Blocking**:
- If no upstream source is present → `MISSING_REQUIRED_PARAM` with `details.missing=["numbers_source"]`
- If upstream type is not `lines` → `UNSUPPORTED_INTENT` with `details.detail="TYPE_MISMATCH"`

## `stats_basic` (inline numbers)

**Meaning**: compute basic stats over explicitly provided numbers.

**Supported phrases**:
- “stats for numbers 3 1 2”, “statistics for numbers …”

**Blocking**:
- If no explicit numbers are present → `MISSING_REQUIRED_PARAM` with `details.missing=["numbers"]`


