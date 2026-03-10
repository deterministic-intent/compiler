# DCS v1 Canonical Description Freeze

## Frozen Version

**Version:** `nlc-v1.13.0`  
**Date:** 2026-02-04  
**Document:** `docs/CURRENT_STATE.md`  
**Frozen Copy:** `docs/CURRENT_STATE_v1.13.0.md`

## Freeze Declaration

The document `docs/CURRENT_STATE.md` as it exists at tag `nlc-v1.13.0` is the **canonical description** of the Deterministic Compiler System (DCS) v1.

This document:
- Describes the system exactly as implemented at `nlc-v1.13.0`
- Is factual and deterministic (no speculation, no roadmap)
- Documents all proven guarantees with evidence
- Explicitly lists what is NOT implemented
- Is the authoritative reference for v1 system behavior

## Usage

- For v1 system understanding: read `docs/CURRENT_STATE.md` (or `docs/CURRENT_STATE_v1.13.0.md` for the exact frozen version)
- For future versions: new freeze documents will be created (e.g., `CURRENT_STATE_v2.0.0.md`)
- The frozen copy (`CURRENT_STATE_v1.13.0.md`) is immutable and will not be updated

## Freeze Rules

- The frozen copy (`CURRENT_STATE_v1.13.0.md`) must not be modified
- `CURRENT_STATE.md` may be updated for future versions, but v1 description remains frozen
- Any changes to v1 behavior require a new version tag and new freeze document
