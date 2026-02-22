"""Repro/replay mode: DCS_REPRO or NLC_REPRO env controls deterministic behavior."""

import os


def is_repro_mode() -> bool:
    """True when DCS_REPRO=1 or NLC_REPRO=1 (replay/deterministic mode)."""
    return (
        os.environ.get("DCS_REPRO", "").strip() == "1"
        or os.environ.get("NLC_REPRO", "").strip() == "1"
    )
