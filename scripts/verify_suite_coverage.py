#!/usr/bin/env python3
"""
Golden suite coverage verifier.

Deterministic inputs only:
- pinned snapshot capabilities.json
- suite JSON file content
- deterministic classifier (capabilities-bound)

Locked failure tokens (exact):
  FAIL suite:coverage_insufficient
  FAIL suite:missing_capabilities
  FAIL suite:invalid_suite_format
  FAIL suite:ambiguous_request_in_suite
  FAIL suite:coverage_config_missing
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def _fail(token: str) -> None:
    sys.stdout.write(token.rstrip("\n") + "\n")
    sys.stdout.flush()
    raise SystemExit(1)


def _load_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8", errors="replace"))


def _read_caps(snapshot_id: str) -> Dict[str, Any]:
    caps_path = BASE / "nlc" / "db" / "snapshots" / snapshot_id / "capabilities.json"
    if not caps_path.exists():
        _fail("FAIL suite:missing_capabilities")
    obj = _load_json(caps_path)
    if not isinstance(obj, dict):
        _fail("FAIL suite:missing_capabilities")
    return obj


def _get_coverage_config(policy_version: str, key: str = "golden_coverage") -> Dict[str, int]:
    # Deterministic: read raw policy JSON from disk (avoid import-path variability).
    pv = str(policy_version or "").strip().lower()
    if pv and not pv.startswith("v"):
        pv = "v" + pv
    policy_path = BASE / "policy" / f"policy_{pv}.json"
    if not policy_path.exists():
        _fail("FAIL suite:coverage_config_missing")
    raw = _load_json(policy_path)
    suites = raw.get("suites", {}) if isinstance(raw, dict) else {}
    cfg = suites.get(key, {}) or suites.get("golden_coverage", {}) if isinstance(suites, dict) else {}
    if not isinstance(cfg, dict):
        _fail("FAIL suite:coverage_config_missing")

    def _get_int(k: str) -> int:
        v = cfg.get(k, None)
        if isinstance(v, int) and v >= 0:
            return v
        _fail("FAIL suite:coverage_config_missing")
        raise SystemExit(1)

    return {
        "min_languages": _get_int("min_languages"),
        "min_artifact_classes": _get_int("min_artifact_classes"),
        "min_per_language": _get_int("min_per_language"),
        "min_per_class": _get_int("min_per_class"),
    }


def _artifact_class_to_language(ac: str) -> str:
    if ac.startswith("python_"):
        return "python"
    if ac == "webview":
        return "web"
    return ac


def _classify_case_text(
    request_text: str,
    *,
    capabilities: Dict[str, Any],
) -> Tuple[str, str]:
    from nlc.capability_classifier import classify_request

    dec = classify_request(request_text, capabilities=capabilities)
    if dec.status == "PASS" and dec.artifact_class and dec.language:
        return dec.language, dec.artifact_class
    if dec.status == "UNSUPPORTED":
        # Unsupported is still a *classified hit*; it is deterministic and should be counted
        # only if the suite explicitly expects it. Otherwise the suite is invalid.
        _fail("FAIL suite:ambiguous_request_in_suite")
    _fail("FAIL suite:ambiguous_request_in_suite")
    raise SystemExit(1)


def verify_suite_coverage(snapshot_id: str, suite_path: Path) -> None:
    suite = _load_json(suite_path)
    if not isinstance(suite, dict):
        _fail("FAIL suite:invalid_suite_format")

    cases = suite.get("cases", None)
    policy_version = str(suite.get("policy_version", "")).strip() or "v1"
    if not isinstance(cases, list):
        _fail("FAIL suite:invalid_suite_format")

    caps = _read_caps(snapshot_id)
    suite_id = str(suite.get("suite_id", "")).strip()
    if suite_id == "golden_pack_v1":
        cfg = _get_coverage_config(policy_version, key="golden_pack_coverage")
    else:
        cfg = _get_coverage_config(policy_version, key="golden_coverage")

    supported_langs = caps.get("languages", [])
    supported_acs = caps.get("supported_artifact_classes", [])
    supported_langs_set = {str(x).strip() for x in supported_langs} if isinstance(supported_langs, list) else set()
    supported_acs_set = {str(x).strip() for x in supported_acs} if isinstance(supported_acs, list) else set()

    lang_counts: Dict[str, int] = {}
    ac_counts: Dict[str, int] = {}

    # Deterministic counting: ignore CLARIFY-expected cases (they may be intentionally ambiguous).
    for c in cases:
        if not isinstance(c, dict):
            _fail("FAIL suite:invalid_suite_format")
        expected = str(c.get("expected_final_status", "")).strip().upper()
        if expected in ("CLARIFY", "FAIL"):
            continue

        req_text = str(c.get("request_text", "")).strip()
        if not req_text:
            _fail("FAIL suite:invalid_suite_format")

        # Prefer explicit expected_* fields if present; otherwise classify deterministically.
        exp_ac = str(c.get("expected_artifact_class", "")).strip()
        exp_lang = str(c.get("expected_language", "")).strip()
        if exp_ac and exp_lang:
            ac = exp_ac
            lang = exp_lang
        elif exp_ac and not exp_lang:
            ac = exp_ac
            lang = _artifact_class_to_language(ac)
        else:
            lang, ac = _classify_case_text(req_text, capabilities=caps)

        if supported_acs_set and ac not in supported_acs_set:
            _fail("FAIL suite:ambiguous_request_in_suite")
        if supported_langs_set and lang not in supported_langs_set:
            _fail("FAIL suite:ambiguous_request_in_suite")

        lang_counts[lang] = lang_counts.get(lang, 0) + 1
        ac_counts[ac] = ac_counts.get(ac, 0) + 1

    langs_hit = sorted(lang_counts.keys())
    acs_hit = sorted(ac_counts.keys())

    if len(langs_hit) < int(cfg["min_languages"]) or len(acs_hit) < int(cfg["min_artifact_classes"]):
        _fail("FAIL suite:coverage_insufficient")

    if int(cfg["min_per_language"]) > 0:
        for lang in langs_hit:
            if lang_counts.get(lang, 0) < int(cfg["min_per_language"]):
                _fail("FAIL suite:coverage_insufficient")
    if int(cfg["min_per_class"]) > 0:
        for ac in acs_hit:
            if ac_counts.get(ac, 0) < int(cfg["min_per_class"]):
                _fail("FAIL suite:coverage_insufficient")

    # Stable, sorted summary (no timestamps).
    sys.stdout.write("COVERAGE_OK\n")
    sys.stdout.write("languages_hit: " + json.dumps(langs_hit, sort_keys=True) + "\n")
    sys.stdout.write("artifact_classes_hit: " + json.dumps(acs_hit, sort_keys=True) + "\n")
    sys.stdout.flush()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-id", required=True)
    ap.add_argument("--suite", required=True)
    args = ap.parse_args()

    snapshot_id = str(args.snapshot_id).strip()
    suite_path = Path(str(args.suite)).resolve()
    if not snapshot_id or not suite_path.exists():
        _fail("FAIL suite:invalid_suite_format")
    verify_suite_coverage(snapshot_id, suite_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


