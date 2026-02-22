# DCS CLI BRANDING & ASCII IDENTITY — IMPLEMENTATION INSTRUCTIONS
# Revision: r1
# Phase: 1 — CLI Productization
# Milestone: 1.0 (Branding hardening)
# Status: LOCKED

## PURPOSE
Implement and tighten the DCS CLI branding and loading UX exactly as specified.
This includes REQUIRED per-gate loading spinners.
This is UX-only work. Deterministic behavior, artifacts, hashes, and replay
must remain unchanged.

If any branding behavior conflicts with determinism or replay, branding is disabled.

---

## BRANDING & UX INVARIANTS (NON-NEGOTIABLE)

- ASCII only (as shown below)
- Terminal-safe (SSH, tmux, low DPI)
- UX-only (never written to artifacts, manifests, repro, JSON, or files)
- Replay-safe (replay forcibly disables all branding and effects)

Any branding leakage during replay is a hard failure.

---

## CANONICAL NAMING (FROZEN)

System name:
Deterministic Compiler System

Short name:
DCS

CLI command:
dcs

No aliases. No alternates.

---

## PRIMARY ASCII BANNER (AUTHORITATIVE — EXACT)

Render **exactly** as shown.  
Spacing, characters, and alignment are frozen.

    __                  _____     _____    _____                       ____   
   / /                 |  __ \   / ____|  / ____|                     / /\ \  
  / /   ______ ______  | |  | | | |      | (___    ______ ______     / /  \ \ 
 < <   |______|______| | |  | | | |       \___ \  |______|______|   / /    > >
  \ \                  | |__| | | |____   ____) |                  / /    / / 
   \_\                 |_____/   \_____| |_____/                  /_/    /_/  

Deterministic Compiler System

Rules:
- ASCII only
- No reflow
- No compression
- No regeneration via fonts or tools
- Copy verbatim

---

## COMPACT FALLBACK BANNER

Used only when:
- terminal width < 80 columns, OR
- explicit compact banner mode

DCS - Deterministic Compiler System

ASCII hyphen only.

---

## BANNER PLACEMENT RULES

Banner MUST appear:
- At the start of every CLI run (TTY only)
- At interactive REPL startup
- In `dcs --help`
- In `dcs --version`

Banner MUST NOT appear:
- In replay mode
- With `--json`
- In non-TTY output
- In files, artifacts, logs, or repro data

Replay mode always overrides user intent.

---

## LOADING SPINNERS (REQUIRED)

Spinners are REQUIRED for normal CLI execution.

### Spinner behavior
- One spinner PER GATE
- Spinner runs while the gate is executing
- Spinner updates in-place (single line)
- Spinner is replaced by the final stable gate line

Spinner examples (choose ONE, keep consistent):
- | / - \
- . .. ...

### Spinner enable conditions (default ON)
Spinner is ENABLED when:
- stdout is a TTY
- NOT replay mode
- NOT `--json`
- `--spinner auto|on`
- `DCS_EFFECTS=1` (default)

Spinner is DISABLED only when:
- replay mode
- `--json`
- non-TTY output
- `--spinner off`
- `DCS_EFFECTS=0`

Fallback when disabled:
[loading] <gate name>

---

## GATE UX (STABLE FINAL LINES)

Final gate lines must be deterministic and replace spinner output:

[gate 0] wiring + context .......... OK
[gate 1] snapshot + manifests ...... OK
[gate 2] deterministic selection ... OK
[gate 3] verifier .................. PASS
[gate 7] deliver ................... OK

No timestamps. No randomness.

---

## DETERMINISM & REPLAY CLAMP (HARD)

In replay mode, the CLI MUST force:
- no banner
- no color
- no spinner
- no animation
- stable text only

Any branding or spinner output during replay is a replay failure.

---

## IMPLEMENTATION RULES

- Spinners are REQUIRED UX
- Do NOT remove spinners except under clamp conditions
- Do NOT invent additional animations
- Do NOT alter ASCII art
- If UX conflicts with determinism, determinism wins
- If behavior is not defined here, do not implement it

---

## SCOPE CLASSIFICATION

Phase: 1 — CLI Productization
Milestone: 1.0 — DCS CLI shell
Work type: Branding hardening only (no new features)

---

## CHANGE CONTROL

Any modification requires:
- new revision (r2, r3, …)
- explicit approval
- audit note

---

## LOCK STATEMENT

This document is the single source of truth for DCS CLI branding and loading UX.
If behavior is not defined here, it must not be implemented.


