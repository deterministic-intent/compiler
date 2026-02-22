#!/usr/bin/env python3
"""Prompt Compiler - Converts plain English prompts to REQ.json (structured IR)."""
import json
import re
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# Deterministic intent ranking (for UNKNOWN_INTENT clarification)
def rank_intents(prompt: str, intents_manifest: dict) -> list[dict]:
    pl = " ".join((prompt or "").lower().split())
    tokens = set([t for t in re.split(r"[^a-z0-9_]+", pl) if t])
    ranked = []
    for intent_id, intent_data in sorted(intents_manifest.items()):
        name = str(intent_data.get("name", intent_id))
        words = set([w for w in re.split(r"[^a-z0-9_]+", (intent_id + " " + name).lower()) if w])
        score = len(tokens.intersection(words))
        ranked.append({"intent_id": intent_id, "name": name, "score": score})
    ranked.sort(key=lambda r: (-r["score"], r["intent_id"]))
    return ranked
# Policy loader (optional - for future policy-aware compilation)
try:
    from policy import load_policy, get_default_policy_version
except ImportError:
    load_policy = None
    get_default_policy_version = None


def get_policy_for_compilation(policy_version: Optional[str] = None):
    """
    Get policy for prompt compilation. Step 1: wiring only - no enforcement yet.
    
    Helper only locates policy_version and calls load_policy().
    All enforcement logic lives elsewhere (not in helpers).
    
    Args:
        policy_version: Optional explicit version (if None, uses default)
    
    Returns:
        Policy object or None if policy module unavailable or load fails
    """
    if load_policy is None:
        return None
    
    if policy_version is None:
        if get_default_policy_version:
            policy_version = get_default_policy_version()
        else:
            return None
    
    try:
        return load_policy(policy_version)
    except Exception:
        return None



STOPWORDS = {
    'a','an','the','to','from','and','or','of','in','on','for','with','that','this','it','as','by','each','per','into','own',
}


def _extract_quoted_substrings(s: str) -> list[str]:
    # Return all quoted literals in deterministic order
    out: list[str] = []
    for m in re.finditer(r"\"([^\"]+)\"|'([^']+)'", s):
        g1 = m.group(1)
        g2 = m.group(2)
        val = g1 if g1 is not None else g2
        if val is not None:
            out.append(val)
    return out


def _extract_file_paths(s: str) -> list[str]:
    # Strict-ish path detector: tokens containing a dot extension
    toks = re.findall(r"(?:\./|/)?[A-Za-z0-9_\-./]+\.[A-Za-z0-9]{1,6}", s)
    # de-dupe preserve order
    seen=set()
    out=[]
    for t in toks:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _mentions_stdin(s: str) -> bool:
    sl = s.lower()
    return any(ph in sl for ph in [
        'stdin', 'standard input', 'from stdin', 'standard in', 'pipe', 'piped', 'piped in',
    ])


def _is_safe_relpath(p: str) -> bool:
    """Deterministic safety check: only allow safe relative paths."""
    if not p:
        return False
    if p.startswith("/"):
        return False
    parts = p.replace("\\", "/").split("/")
    if any(x == ".." for x in parts):
        return False
    return True


def _choose_path_by_context(prompt_lower: str, paths: list[str], role: str) -> tuple[str | None, dict | None]:
    """Deterministic file-path selection with strict ambiguity blocking.

    role:
      - "read": selects input path
      - "write": selects output path
    """
    if not paths:
        return None, None
    if len(paths) == 1:
        return paths[0], None

    # Prefer tight, local cue matching to avoid spanning across clauses.
    if role == "read":
        cue_pat = re.compile(r"\b(?:read|from|input|load)\b")
    else:
        cue_pat = re.compile(r"\b(?:write|to|save|into|output)\b")

    candidates: list[str] = []
    for fp in paths:
        try:
            for mm in re.finditer(re.escape(fp.lower()), prompt_lower):
                window = prompt_lower[max(0, mm.start() - 16):mm.start()]
                if cue_pat.search(window):
                    candidates.append(fp)
                    break
        except Exception:
            continue

    # De-dupe deterministically, preserve order from input list.
    seen: set[str] = set()
    ordered: list[str] = []
    for fp in paths:
        if fp in candidates and fp not in seen:
            seen.add(fp)
            ordered.append(fp)

    if len(ordered) == 1:
        return ordered[0], None

    return None, {
        "reason_code": "AMBIGUOUS_PARAM",
        "param": "file_path",
        "role": role,
        "candidates": paths,
    }

BASE = Path(__file__).resolve().parents[1]
EMITTERS_DIR = BASE / "orchestrator" / "intent_emitters"


def _registry_source() -> str:
    import os
    return str(os.environ.get("NLC_REGISTRY_SOURCE", "file")).strip().lower() or "file"


def _db_path_for_registry(repro_mode: bool) -> str:
    import os
    base = Path(__file__).resolve().parents[1]
    if repro_mode:
        sid = str(os.environ.get("NLC_DB_SNAPSHOT_ID", "")).strip()
        if sid:
            return str(base / "nlc" / "db" / "snapshots" / sid / "nlc.db")
    return str(base / "nlc" / "db" / "live" / "nlc.db")


def load_registry_intents(repro_mode: bool) -> Dict[str, Dict[str, Any]]:
    """Load intent registry from file v1 or DB (deterministic ordering)."""
    source = _registry_source()
    intents: Dict[str, Dict[str, Any]] = {}
    if source == "db":
        dbp = _db_path_for_registry(repro_mode)
        conn = sqlite3.connect(dbp)
        cur = conn.cursor()
        for intent_id, description, pipeline_type, params_json, io_json, disamb_json in cur.execute(
            "SELECT intent_id, description, pipeline_type, params_json, io_json, disambiguation_json FROM nlc_intents ORDER BY intent_id"
        ):
            intents[intent_id] = {
                "intent_type": intent_id,
                "description": description,
                "pipeline_type": pipeline_type,
                "params_schema": json.loads(params_json),
                "keywords": [],
                "synonyms": [],
            }
        for intent_id, phrase, weight in cur.execute(
            "SELECT intent_id, phrase, weight FROM nlc_synonyms ORDER BY intent_id, phrase"
        ):
            if intent_id in intents:
                intents[intent_id].setdefault("synonyms", []).append(phrase)
        conn.close()
        # use synonyms as keywords for matching
        for iid in list(intents.keys()):
            syns = intents[iid].get("synonyms") or []
            intents[iid]["keywords"] = list(syns)
        return intents

    # default: file registry v1
    base = Path(__file__).resolve().parents[1]
    v1 = base / "nlc" / "registry" / "v1" / "intents"
    if v1.exists():
        for fp in sorted([p for p in v1.glob("*.json") if p.is_file()], key=lambda p: p.name):
            doc = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
            iid = str(doc.get("intent_id", "")).strip()
            if not iid:
                continue
            intents[iid] = {
                "intent_type": iid,
                "description": str(doc.get("description", "")),
                "pipeline_type": str(doc.get("pipeline_type", "unknown")),
                "params_schema": doc.get("params_json") or {},
                "keywords": list(doc.get("synonyms") or []),
            }
        return intents

    # fallback to emitters
    return load_supported_intents()


def load_supported_intents() -> Dict[str, Dict[str, Any]]:
    """Load all supported intent types and their patterns."""
    intents = {}
    
    if not EMITTERS_DIR.exists():
        return intents
    
    for emitter_file in sorted(EMITTERS_DIR.glob("*.json"), key=lambda p: p.name):
        if emitter_file.name == "index.json":
            continue
        
        try:
            emitter = json.loads(emitter_file.read_text())
            intent_type = emitter.get("intent_type")
            if intent_type:
                intents[intent_type] = {
                    "intent_type": intent_type,
                    "description": emitter.get("description", ""),
                    "params_schema": emitter.get("params_schema", {}),
                    "keywords": extract_keywords(emitter)
                }
        except:
            pass
    
    return intents


def extract_keywords(emitter: Dict[str, Any]) -> List[str]:
    """Extract keywords from emitter description and code."""
    keywords = []
    
    desc = emitter.get("description", "").lower()
    keywords.extend(desc.split())
    
    intent_type = emitter.get("intent_type", "")
    keywords.append(intent_type.replace("_", " "))
    
    return sorted(set(keywords))


def _load_intents_v1_for_enrichment(snapshot_id: str) -> List[Dict[str, Any]]:
    """Load intents_v1 from snapshot manifest or policy for module_refs enrichment."""
    base = Path(__file__).resolve().parents[1]
    for path in [
        base / "nlc" / "db" / "snapshots" / str(snapshot_id).strip() / "manifest" / "intents_v1.json",
        base / "policy" / "intents_v1.json",
    ]:
        if path.exists():
            try:
                obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                intents = obj.get("intents", []) if isinstance(obj, dict) else []
                return [e for e in intents if isinstance(e, dict)] if isinstance(intents, list) else []
            except Exception:
                pass
    return []


def _load_executable_intents(snapshot_id: str) -> List[Dict[str, Any]]:
    """Load executable intents from snapshot manifest (for execution)."""
    if not snapshot_id:
        return []
    base = Path(__file__).resolve().parents[1]
    p = base / "nlc" / "db" / "snapshots" / snapshot_id / "manifest" / "intents_executable.json"
    if not p.exists():
        return []
    try:
        obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []
    intents = obj.get("intents", []) if isinstance(obj, dict) else []
    if not isinstance(intents, list):
        return []
    return [it for it in intents if isinstance(it, dict)]


def _match_executable_intents(prompt: str, executable_intents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pl = " " + " ".join((prompt or "").lower().split()) + " "
    matches: List[Dict[str, Any]] = []
    for it in executable_intents:
        # Match by source intent name (from mined intent)
        source_id = str(it.get("source_intent_id", "")).strip()
        if not source_id:
            continue
        # Extract name from source_id or use artifact_class for matching
        artifact_class = str(it.get("artifact_class", "")).strip().lower()
        name_tokens = set([t for t in re.split(r"[^a-z0-9]+", artifact_class) if t])
        prompt_tokens = set([t for t in re.split(r"[^a-z0-9]+", pl) if t])
        hits = len(name_tokens & prompt_tokens)
        if hits > 0:
                hits += 1
        min_hits = int(it.get("match_min_hits", 1) or 1)
        if hits >= min_hits:
            matches.append({**it, "_match_hits": hits})
    matches.sort(key=lambda x: (-int(x.get("_match_hits", 0)), str(x.get("intent_id", ""))))
    return matches


def match_intent(prompt: str, intent_info: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, Any]], List[str]]:
    """Match prompt to intent type and extract parameters."""
    prompt_lower = prompt.lower()
    intent_type = intent_info["intent_type"]
    keywords = intent_info.get("keywords", [])
    
    matched_keywords = [kw for kw in keywords if kw and kw not in STOPWORDS and kw in prompt_lower]

    params = {}

    # Explicit matchers run even without keyword hits (synonyms may be sparse).

    if intent_type == "print_sequence":
        from_match = re.search(r'(?:from|count from)\s+(\d+)', prompt_lower)
        to_match = re.search(r'(?:to|up to)\s+(\d+)', prompt_lower)
        step_match = re.search(r'(?:by|step|increment)\s+(\d+)', prompt_lower)
        
        if from_match:
            params["from"] = int(from_match.group(1))
        else:
            params["from"] = 1
        
        if to_match:
            params["to"] = int(to_match.group(1))
        else:
            num_match = re.search(r'(?:count|print|show)\s+(\d+)', prompt_lower)
            if num_match:
                params["to"] = int(num_match.group(1))
            else:
                return False, None, sorted(matched_keywords)
        
        if step_match:
            params["step"] = int(step_match.group(1))
        else:
            params["step"] = 1
        
        return True, params, sorted(matched_keywords)
    
    elif intent_type == "sum_numbers":
        if "sum" in prompt_lower or "add" in prompt_lower:
            numbers = re.findall(r'\d+', prompt)
            if numbers:
                params["numbers"] = [int(n) for n in numbers]
                params["display_result"] = True
                return True, params, sorted(matched_keywords)
        
        return False, None, sorted(matched_keywords)
    
    # For other intents, require at least one keyword hit to even consider matching.
    if not matched_keywords:
        return False, None, sorted(matched_keywords)

    # If we don't have an explicit matcher for this intent, do not guess.
    return False, None, sorted(matched_keywords)





def compile_pipeline(prompt: str, overrides: dict | None = None) -> tuple[bool, list[dict], dict, str | None]:
    """Attempt to compile a deterministic multi-intent pipeline.

    Supports (in order):
      - Input: stdin_support | read_lines | csv_read | (inline numeric)
      - Transforms: filter_contains | unique
      - Output: output_format
      - Sink: write_lines | csv_write

    Returns (ok, intents, trace, blocked_reason_code_or_None).
    """
    pl = prompt.lower()
    trace: dict[str, object] = {
        'pipeline_detected': False,
        'stages': [],
        'blocked': None,
    }

    intents: list[dict] = []
    var: str | None = None
    current_type: str | None = None  # lines | csv_rows | numbers | json_obj | pretty_json
    last_input_path: str | None = None

    def _block(reason: str, details: dict) -> tuple[bool, list[dict], dict, str | None]:
        trace['blocked'] = details
        return False, [], trace, reason

    # Input stage
    if _mentions_stdin(prompt):
        trace['pipeline_detected'] = True
        intents.append({'intent_type': 'stdin_support', 'params': {'read_mode': 'lines'}})
        trace['stages'].append({'intent_type': 'stdin_support'})
        var = 'stage0'
        current_type = 'lines'
    else:
        paths = _extract_file_paths(prompt)

        # CSV read
        if ('csv' in pl) and (('read' in pl) or ('load' in pl)) and any(pp.lower().endswith('.csv') for pp in paths):
            trace['pipeline_detected'] = True
            csv_paths = [pp for pp in paths if pp.lower().endswith('.csv')]
            fp, amb = _choose_path_by_context(pl, csv_paths, 'read')
            if amb:
                return _block('AMBIGUOUS_PARAM', amb)
            fp = fp or (csv_paths[0] if csv_paths else '')
            if not _is_safe_relpath(fp):
                return _block('UNSUPPORTED_INTENT', {
                    'reason_code': 'UNSUPPORTED_INTENT',
                    'detail': 'UNSAFE_PATH',
                    'intent_type': 'csv_read',
                    'param': 'file_path',
                    'value': fp,
                })
            has_header = not (('no header' in pl) or ('without header' in pl))
            intents.append({'intent_type': 'csv_read', 'params': {'file_path': fp, 'has_header': bool(has_header)}})
            trace['stages'].append({'intent_type': 'csv_read', 'file_path': fp, 'has_header': bool(has_header)})
            var = 'stage0'
            current_type = 'csv_rows'
            last_input_path = fp

        # Lines read
        elif (('read' in pl) or ('load' in pl)) and ('line' in pl or 'lines' in pl) and paths:
            trace['pipeline_detected'] = True
            fp, amb = _choose_path_by_context(pl, paths, 'read')
            if amb:
                return _block('AMBIGUOUS_PARAM', amb)
            fp = fp or paths[0]
            if not _is_safe_relpath(fp):
                return _block('UNSUPPORTED_INTENT', {
                    'reason_code': 'UNSUPPORTED_INTENT',
                    'detail': 'UNSAFE_PATH',
                    'intent_type': 'read_lines',
                    'param': 'file_path',
                    'value': fp,
                })
            intents.append({'intent_type': 'read_lines', 'params': {'file_path': fp, 'encoding': 'utf-8'}})
            trace['stages'].append({'intent_type': 'read_lines', 'file_path': fp})
            var = 'stage0'
            current_type = 'lines'
            last_input_path = fp

    # Precompute line counting intent to avoid numeric parse conflicts.
    count_lines_requested = any(phrase in pl for phrase in ["count lines", "line count", "number of lines"])

    overrides = overrides or {}

    # Regex grep intent (strict: requires /.../ and explicit source)
    grep_cue = any(w in pl for w in ["grep", "regex", "regular expression"])
    pattern_matches = re.findall(r"/([^/]+)/([iI])?", prompt)
    if grep_cue or pattern_matches:
        if not pattern_matches:
            if overrides.get("regex_pattern"):
                pattern_matches = [(str(overrides.get("regex_pattern")), "")]
            else:
                return _block('MISSING_REQUIRED_PARAM', {
                    'reason_code': 'MISSING_REQUIRED_PARAM',
                    'missing': ['regex_pattern'],
                })
        if len(pattern_matches) != 1:
            return _block('AMBIGUOUS_PARAM', {
                'reason_code': 'AMBIGUOUS_PARAM',
                'param': 'pattern',
                'candidates': [m[0] for m in pattern_matches],
            })
        pattern, flag = pattern_matches[0]
        if pattern.strip() == "":
            return _block('MISSING_REQUIRED_PARAM', {
                'reason_code': 'MISSING_REQUIRED_PARAM',
                'missing': ['regex_pattern'],
            })
        if var is None:
            return _block('MISSING_REQUIRED_PARAM', {
                'reason_code': 'MISSING_REQUIRED_PARAM',
                'missing': ['items_source'],
            })
        if current_type not in ('lines',):
            return _block('UNSUPPORTED_INTENT', {
                'reason_code': 'UNSUPPORTED_INTENT',
                'detail': 'TYPE_MISMATCH',
                'intent_type': 'grep_regex',
                'expects': ['lines'],
                'got': current_type,
            })
        ignore_case = bool(flag) or ('case-insensitive' in pl)
        trace['pipeline_detected'] = True
        intents.append({
            'intent_type': 'grep_regex',
            'params': {
                'items': var,
                'pattern': pattern,
                'ignore_case': bool(ignore_case),
            }
        })
        trace['stages'].append({'intent_type': 'grep_regex', 'pattern': pattern, 'ignore_case': bool(ignore_case)})
        var = f'stage{len(intents)-1}'
        current_type = 'lines'

    # Numeric parsing pipeline: convert textual lines to numbers then JSON
    parse_numbers_requested = (('parse numbers' in pl) or ('extract numbers' in pl) or ('numbers to json' in pl)) and not count_lines_requested
    if not parse_numbers_requested and current_type == 'lines' and not count_lines_requested:
        # Broader detection: explicit parse/extract + numbers + json context,
        # or numeric operations requested over line input.
        if ('number' in pl) and (('parse' in pl) or ('parses' in pl) or ('extract' in pl) or ('convert' in pl)) and ('json' in pl):
            parse_numbers_requested = True
        elif ('number' in pl or 'numbers' in pl) and (('sort' in pl) or ('stats' in pl) or ('statistics' in pl) or ('json' in pl)):
            parse_numbers_requested = True
        # Require filename cue when the source is a file (avoid mixed.txt auto-parse).
        if parse_numbers_requested and last_input_path:
            lp = last_input_path.lower()
            if not re.search(r"number", lp):
                parse_numbers_requested = False
    if parse_numbers_requested:
        if var is None:
            return _block('MISSING_REQUIRED_PARAM', {
                'reason_code': 'MISSING_REQUIRED_PARAM',
                'missing': ['numbers_source'],
            })
        if current_type not in ('lines',):
            return _block('UNSUPPORTED_INTENT', {
                'reason_code': 'UNSUPPORTED_INTENT',
                'detail': 'TYPE_MISMATCH',
                'intent_type': 'parse_numbers',
                'expects': ['lines'],
                'got': current_type,
            })
        trace['pipeline_detected'] = True
        intents.append({'intent_type': 'parse_numbers', 'params': {'items': var}})
        trace['stages'].append({'intent_type': 'parse_numbers'})
        var = f'stage{len(intents)-1}'
        current_type = 'numbers'

    # Numeric pipeline: numbers sourced from inline or prior parse_numbers
    nums_inline = [int(x) for x in re.findall(r"\d+", prompt)] if var is None else []
    wants_sort = ('sort' in pl) and ('number' in pl or 'numbers' in pl or bool(nums_inline) or current_type == 'numbers')
    wants_stats = (('stats' in pl) or ('statistics' in pl)) and ('number' in pl or 'numbers' in pl or bool(nums_inline) or current_type == 'numbers')
    wants_sum = (('sum' in pl) or ('add' in pl)) and ('number' in pl or 'numbers' in pl)

    if sum([bool(wants_sort), bool(wants_stats), bool(wants_sum)]) > 1:
        return _block('AMBIGUOUS_INTENT', {
            'reason_code': 'AMBIGUOUS_INTENT',
            'detail': 'multiple numeric operations requested',
        })

    if wants_sort:
        source_var = var
        nums: list[int] = []
        if source_var is None:
            nums = nums_inline
            if not nums:
                if overrides.get("numbers"):
                    nums = overrides.get("numbers")
                else:
                    return _block('MISSING_REQUIRED_PARAM', {
                        'reason_code': 'MISSING_REQUIRED_PARAM',
                        'missing': ['numbers'],
                    })
            source_var = 'stage0'
        elif current_type != 'numbers':
            return _block('UNSUPPORTED_INTENT', {
                'reason_code': 'UNSUPPORTED_INTENT',
                'detail': 'TYPE_MISMATCH',
                'intent_type': 'sort_numbers',
                'expects': ['numbers'],
                'got': current_type,
            })
        trace['pipeline_detected'] = True
        rev = ('desc' in pl) or ('descending' in pl) or ('reverse' in pl)
        if source_var == 'stage0' and not var:
            intents.append({'intent_type': 'sort_numbers', 'params': {'numbers': nums, 'reverse': bool(rev)}})
        else:
            intents.append({'intent_type': 'sort_numbers', 'params': {'numbers': source_var, 'reverse': bool(rev)}})
        trace['stages'].append({'intent_type': 'sort_numbers', 'reverse': bool(rev)})
        var = f'stage{len(intents)-1}'
        current_type = 'numbers'

    elif wants_stats:
        source_var = var
        nums: list[int] = []
        if source_var is None:
            nums = nums_inline
            if not nums:
                if overrides.get("numbers"):
                    nums = overrides.get("numbers")
                else:
                    return _block('MISSING_REQUIRED_PARAM', {
                        'reason_code': 'MISSING_REQUIRED_PARAM',
                        'missing': ['numbers'],
                    })
            source_var = 'stage0'
        elif current_type != 'numbers':
            return _block('UNSUPPORTED_INTENT', {
                'reason_code': 'UNSUPPORTED_INTENT',
                'detail': 'TYPE_MISMATCH',
                'intent_type': 'stats_basic',
                'expects': ['numbers'],
                'got': current_type,
            })
        trace['pipeline_detected'] = True
        wanted: list[str] = []
        for key in ['min', 'max', 'avg', 'count']:
            if key in pl:
                wanted.append(key)
        params = {'numbers': nums if source_var == 'stage0' and not var else source_var}
        if wanted:
            params['stats'] = wanted
        intents.append({'intent_type': 'stats_basic', 'params': params})
        trace['stages'].append({'intent_type': 'stats_basic', 'stats': wanted or ['min', 'max', 'avg', 'count']})
        var = f'stage{len(intents)-1}'
        current_type = 'json_obj'

    elif wants_sum:
        # sum_numbers is a non-pipeline intent today (prints by itself)
        pass

    # Line counting pipeline
    count_lines_requested = any(phrase in pl for phrase in ["count lines", "line count", "number of lines"])
    if count_lines_requested:
        if var is None:
            return _block('MISSING_REQUIRED_PARAM', {
                'reason_code': 'MISSING_REQUIRED_PARAM',
                'missing': ['items_source'],
            })
        if current_type not in ('lines',):
            return _block('UNSUPPORTED_INTENT', {
                'reason_code': 'UNSUPPORTED_INTENT',
                'detail': 'TYPE_MISMATCH',
                'intent_type': 'count_lines',
                'expects': ['lines'],
                'got': current_type,
            })
        trace['pipeline_detected'] = True
        intents.append({'intent_type': 'count_lines', 'params': {'items': var}})
        trace['stages'].append({'intent_type': 'count_lines'})
        var = f'stage{len(intents)-1}'
        current_type = 'numbers'

    # JSON pretty print pipeline
    pretty_phrases = ["pretty print json", "prettify json", "format json"]
    json_pretty_requested = any(ph in pl for ph in pretty_phrases) and ("json" in pl)
    if json_pretty_requested:
        if var is None:
            return _block('MISSING_REQUIRED_PARAM', {
                'reason_code': 'MISSING_REQUIRED_PARAM',
                'missing': ['items_source'],
            })
        if current_type not in ('lines',):
            return _block('UNSUPPORTED_INTENT', {
                'reason_code': 'UNSUPPORTED_INTENT',
                'detail': 'TYPE_MISMATCH',
                'intent_type': 'json_pretty_print',
                'expects': ['lines'],
                'got': current_type,
            })
        trace['pipeline_detected'] = True
        intents.append({'intent_type': 'json_pretty_print', 'params': {'items': var}})
        trace['stages'].append({'intent_type': 'json_pretty_print'})
        var = f'stage{len(intents)-1}'
        current_type = 'lines'

    # CSV select columns (requires csv context, explicit columns, explicit source)
    if ('csv' in pl) and re.search(r'\b(select|choose|extract)\s+columns?\b', pl):
        # Ensure source is csv_read-derived
        if var is None or current_type != 'csv_rows':
            return _block('MISSING_REQUIRED_PARAM', {
                'reason_code': 'MISSING_REQUIRED_PARAM',
                'missing': ['csv_source'],
            })
        # derive header flag from last csv_read
        has_header = True
        if 'no header' in pl or 'without header' in pl:
            has_header = False
        # parse columns: prefer quoted substrings for names; otherwise numeric list
        qcols = [c.strip() for c in _extract_quoted_substrings(prompt) if c.strip()]
        num_cols = re.findall(r"\b\d+\b", pl)
        if not qcols and not num_cols:
            m = re.search(r"\bcolumns?\s+([^,]+(?:\s*,\s*[^,]+)+)", prompt, flags=re.IGNORECASE)
            if m:
                raw = m.group(1)
                parts = [p.strip() for p in raw.split(",") if p.strip()]
                parts = [p for p in parts if not p.lower().startswith('and ')]
                if parts and all(p.isdigit() for p in parts):
                    num_cols = parts
                elif parts and all(not p.isdigit() for p in parts):
                    qcols = parts
                else:
                    return _block('AMBIGUOUS_INTENT', {
                        'reason_code': 'AMBIGUOUS_INTENT',
                        'detail': 'mixed numeric/name columns',
                    })
        if qcols and num_cols:
            return _block('AMBIGUOUS_INTENT', {
                'reason_code': 'AMBIGUOUS_INTENT',
                'detail': 'both named and numeric columns provided',
            })
        cols = []
        is_names = False
        if qcols:
            cols = [c for c in qcols if c.lower() != 'and']
            is_names = True
        elif num_cols:
            cols = [int(x) for x in num_cols]
            is_names = False
        else:
            return _block('MISSING_REQUIRED_PARAM', {
                'reason_code': 'MISSING_REQUIRED_PARAM',
                'missing': ['columns'],
            })
        # enforce header rules
        if has_header and not is_names:
            return _block('MISSING_REQUIRED_PARAM', {
                'reason_code': 'MISSING_REQUIRED_PARAM',
                'missing': ['column_names'],
            })
        if (not has_header) and is_names:
            return _block('MISSING_REQUIRED_PARAM', {
                'reason_code': 'MISSING_REQUIRED_PARAM',
                'missing': ['column_indices'],
            })
        trace['pipeline_detected'] = True
        params = {
            'items': var,
            'columns': cols,
            'has_header': bool(has_header),
        }
        if last_input_path:
            params['source_path'] = last_input_path
        intents.append({'intent_type': 'csv_select_columns', 'params': params})
        trace['stages'].append({'intent_type': 'csv_select_columns', 'columns': cols, 'has_header': bool(has_header)})
        var = f'stage{len(intents)-1}'
        current_type = 'csv_rows'

    # Filter stage (word-boundary; avoid matching filenames like filtered.txt)
    if re.search(r'\b(filter|contains|containing)\b', pl):
        q = _extract_quoted_substrings(prompt)
        substring = q[0] if q else ''

        if not substring:
            # Strict fallback: allow exactly one unquoted token after 'contains/containing'.
            cands = re.findall(r"(?:containing|contains)\s+([A-Za-z0-9_\-]+)\b", pl)
            cands = [c for c in cands if c and c not in STOPWORDS and c not in ('json', 'csv', 'text')]
            uniq: list[str] = []
            for c in cands:
                if c not in uniq:
                    uniq.append(c)
            if len(uniq) == 1:
                substring = uniq[0]
            elif len(uniq) > 1:
                return _block('AMBIGUOUS_PARAM', {
                    'reason_code': 'AMBIGUOUS_PARAM',
                    'param': 'substring',
                    'candidates': uniq,
                })

        if not substring:
            return _block('MISSING_REQUIRED_PARAM', {
                'reason_code': 'MISSING_REQUIRED_PARAM',
                'missing': ['substring'],
            })

        if var is None:
            return _block('MISSING_REQUIRED_PARAM', {
                'reason_code': 'MISSING_REQUIRED_PARAM',
                'missing': ['items_source'],
            })

        if current_type not in ('lines', 'csv_rows'):
            return _block('UNSUPPORTED_INTENT', {
                'reason_code': 'UNSUPPORTED_INTENT',
                'detail': 'TYPE_MISMATCH',
                'intent_type': 'filter_contains',
                'expects': ['lines', 'csv_rows'],
                'got': current_type,
            })

        trace['pipeline_detected'] = True
        intents.append({'intent_type': 'filter_contains', 'params': {'items': var, 'substring': substring, 'case_sensitive': False}})
        trace['stages'].append({'intent_type': 'filter_contains', 'substring': substring})
        var = f'stage{len(intents)-1}'

    # Unique stage
    if ('unique' in pl) or ('dedupe' in pl) or ('duplicate' in pl):
        if ('sorted unique' in pl) or (('sorted' in pl) and ('unique' in pl)):
            return _block('AMBIGUOUS_INTENT', {
                'reason_code': 'AMBIGUOUS_INTENT',
                'detail': 'sorted unique not supported',
            })

        if var is None:
            return _block('MISSING_REQUIRED_PARAM', {
                'reason_code': 'MISSING_REQUIRED_PARAM',
                'missing': ['items_source'],
            })

        if current_type not in ('lines', 'csv_rows'):
            return _block('UNSUPPORTED_INTENT', {
                'reason_code': 'UNSUPPORTED_INTENT',
                'detail': 'TYPE_MISMATCH',
                'intent_type': 'unique',
                'expects': ['lines', 'csv_rows'],
                'got': current_type,
            })

        trace['pipeline_detected'] = True
        intents.append({'intent_type': 'unique', 'params': {'items': var, 'preserve_order': True}})
        trace['stages'].append({'intent_type': 'unique', 'preserve_order': True})
        var = f'stage{len(intents)-1}'

    # Output format stage (explicit)
    fmt_mentions = re.findall(r'(?:output|outputs|as|in|format)\s+(json|csv|text)\b', pl)
    fmt_mentions = sorted(set(fmt_mentions))
    if len(fmt_mentions) > 1:
        return _block('AMBIGUOUS_INTENT', {
            'reason_code': 'AMBIGUOUS_INTENT',
            'detail': f'multiple output formats mentioned: {fmt_mentions}',
        })

    if fmt_mentions:
        if var is None:
            return _block('MISSING_REQUIRED_PARAM', {
                'reason_code': 'MISSING_REQUIRED_PARAM',
                'missing': ['data_source'],
            })
        trace['pipeline_detected'] = True
        intents.append({'intent_type': 'output_format', 'params': {'data': var, 'format': fmt_mentions[0]}})
        trace['stages'].append({'intent_type': 'output_format', 'format': fmt_mentions[0]})
        var = f'stage{len(intents)-1}'

    # Sink stage (write)
    if ('write' in pl) or ('output to' in pl) or ('save to' in pl):
        paths = _extract_file_paths(prompt)
        if paths:
            dest, amb = _choose_path_by_context(pl, paths, 'write')
            if amb:
                return _block('AMBIGUOUS_PARAM', amb)
            dest = dest or paths[-1]
            if not _is_safe_relpath(dest):
                return _block('UNSUPPORTED_INTENT', {
                    'reason_code': 'UNSUPPORTED_INTENT',
                    'detail': 'UNSAFE_PATH',
                    'intent_type': 'csv_write' if dest.lower().endswith('.csv') else 'write_lines',
                    'param': 'file_path',
                    'value': dest,
                })

            if dest.lower().endswith('.csv'):
                if var is None:
                    return _block('MISSING_REQUIRED_PARAM', {
                        'reason_code': 'MISSING_REQUIRED_PARAM',
                        'missing': ['data_source'],
                    })
                if current_type != 'csv_rows':
                    return _block('UNSUPPORTED_INTENT', {
                        'reason_code': 'UNSUPPORTED_INTENT',
                        'detail': 'TYPE_MISMATCH',
                        'intent_type': 'csv_write',
                        'expects': ['csv_rows'],
                        'got': current_type,
                    })
                intents.append({'intent_type': 'csv_write', 'params': {'file_path': dest, 'data': var, 'header': None}})
                trace['stages'].append({'intent_type': 'csv_write', 'file_path': dest})
                var = f'stage{len(intents)-1}'

            else:
                if var is None:
                    return _block('MISSING_REQUIRED_PARAM', {
                        'reason_code': 'MISSING_REQUIRED_PARAM',
                        'missing': ['lines_source'],
                    })
                if current_type != 'lines':
                    return _block('UNSUPPORTED_INTENT', {
                        'reason_code': 'UNSUPPORTED_INTENT',
                        'detail': 'TYPE_MISMATCH',
                        'intent_type': 'write_lines',
                        'expects': ['lines'],
                        'got': current_type,
                    })
                intents.append({'intent_type': 'write_lines', 'params': {'file_path': dest, 'encoding': 'utf-8', 'lines': var}})
                trace['stages'].append({'intent_type': 'write_lines', 'file_path': dest})
                var = f'stage{len(intents)-1}'

    if not trace['pipeline_detected']:
        return False, [], trace, None

    return True, intents, trace, None

def compile_prompt(prompt: str, repro_mode: bool = False, overrides: dict | None = None) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """Compile plain English prompt to REQ.json."""
    intents_map = load_registry_intents(repro_mode)
    
    if not intents_map:
        return False, None, "No intent emitters found. Cannot compile prompt."
    
    # Try deterministic pipeline compilation first
    ok_pipe, pipe_intents, pipe_trace, pipe_block = compile_pipeline(prompt, overrides=overrides)
    if ok_pipe:
        req_json = {"schema_version": "req_v1", "intents": pipe_intents}
        req_json["_intent_trace"] = {"prompt": prompt, "pipeline": pipe_trace}
        return True, req_json, None
    if pipe_block:
        # blocked pipeline (missing param / ambiguous)
        return False, {"_intent_trace": {"prompt": prompt, "pipeline": pipe_trace}}, f"BLOCKED::{pipe_block}"

    matched_intents = []
    trace = {
        "prompt": prompt,
        "prompt_lower": prompt.lower(),
        "candidates": [],
        "selected_intents": [],
    }
    
    for intent_type in sorted(intents_map.keys()):
        intent_info = intents_map[intent_type]
        matched, params, matched_keywords = match_intent(prompt, intent_info)
        trace["candidates"].append({
            "intent_type": intent_type,
            "matched": bool(matched),
            "matched_keywords": matched_keywords,
        })
        if matched:
            trace["selected_intents"].append(intent_type)
            matched_intents.append({
                "intent_type": intent_type,
                "params": params or {},
                "io": {"stdout": True},
                "description": intent_info.get("description", "")
            })
    
    if not matched_intents:
        supported = ", ".join(sorted(intents_map.keys()))
        return False, None, f"No supported intents matched. Supported: {supported}"
    
    req_json = {
        "schema_version": "req_v1",
        "intents": matched_intents
    }
    req_json["_intent_trace"] = trace
    
    return True, req_json, None


def compile_with_fallback(
    prompt: str,
    request_dir: Path,
    request_id: Optional[str] = None,
    policy_version: Optional[str] = None,
    knowledge_snapshot_id: Optional[str] = None,
    manifest_bundle_hash: Optional[str] = None,
    manifest_hashes: Optional[Dict[str, str]] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Compile prompt and write REQ.json + INTENT_TRACE.json deterministically.
    Step 3: Emits CLARIFY.json on ambiguity instead of guessing.

    Intent override lane removed. Use dcs build --intent or dcs build --req.
    """
    request_dir.mkdir(parents=True, exist_ok=True)
    overrides = overrides or {}

    # Intent override lane removed. Use dcs build --intent or dcs build --req only.

    # Get policy version if not provided
    if policy_version is None:
        try:
            from policy import get_default_policy_version
            policy_version = get_default_policy_version()
        except ImportError:
            policy_version = "v1"
    
    # Get request_id from directory name if not provided
    if request_id is None:
        request_id = request_dir.name
    
    # Load snapshot manifest for validation (if available)
    intents_manifest = None
    intents_manifest_data = None
    if knowledge_snapshot_id:
        try:
            from nlc.db.manifest_builder import build_intents_manifest
            BASE = Path(__file__).resolve().parents[1]
            intents_manifest_data = build_intents_manifest(BASE, knowledge_snapshot_id)
            intents_manifest = {intent["intent_id"]: intent for intent in intents_manifest_data.get("intents", [])}
        except Exception:
            pass  # If manifest unavailable, continue without validation
    
    # No interactive intent/field resolution in compiler; CLARIFY is terminal.
    resolved_req_json = None
    resolved_trace = None
    
    # Milestone 4.1: Optional LLM intent proposal (before deterministic parse)
    llm_candidates = None
    from dcs_core.repro_env import is_repro_mode
    repro_mode = is_repro_mode()
    
    # Check if LLM parse is enabled
    llm_parse_enabled = False
    if load_policy and policy_version:
        try:
            policy = load_policy(policy_version)
            llm_policy = policy.get_llm_policy()
            llm_parse_enabled = "parse" in llm_policy.get("allowed_call_sites", [])
        except Exception:
            pass
    
    if llm_parse_enabled and intents_manifest and not repro_mode:
        try:
            from nlc.llm_parse_adapter import parse_with_llm
            
            # Load capabilities if available
            capabilities = None
            if knowledge_snapshot_id:
                try:
                    BASE = Path(__file__).resolve().parents[1]
                    caps_path = BASE / "nlc" / "db" / "snapshots" / knowledge_snapshot_id / "capabilities.json"
                    if caps_path.exists():
                        capabilities = json.loads(caps_path.read_text(encoding="utf-8", errors="replace"))
                except Exception:
                    pass
            
            # Milestone 4.1: LLM I/O persistence directory
            llm_parse_dir = request_dir / "llm_parse"
            cache_dir = request_dir / "llm_parse_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            
            llm_result = parse_with_llm(
                prompt=prompt,
                knowledge_snapshot_id=knowledge_snapshot_id or "",
                manifest_bundle_hash=manifest_bundle_hash or "",
                policy_version=policy_version or "v1",
                intents_manifest=intents_manifest,
                capabilities=capabilities,
                cache_dir=cache_dir,
                repro_mode=repro_mode,
                llm_dir=llm_parse_dir,  # Milestone 4.1: persist LLM I/O
            )
            
            llm_candidates = llm_result.get("candidate_intent_set", {}).get("candidates", [])
            
            # Validate LLM candidates deterministically against manifest
            if llm_candidates:
                validated_candidates = []
                for candidate in llm_candidates:
                    intent_id = candidate.get("intent_id")
                    if intent_id and intent_id in intents_manifest:
                        validated_candidates.append(candidate)
                llm_candidates = validated_candidates
        except Exception as e:
            # LLM parse failed - fall back to deterministic parse
            llm_candidates = None
    
    # Deterministic compile (may use LLM candidates as hints, but validates deterministically)
    success, req_json, error = compile_prompt(prompt, repro_mode=repro_mode, overrides=overrides)

    # KD-executable intent matching (intent-driven execution with module bindings).
    if not success and error and "No supported intents matched" in error and knowledge_snapshot_id:
        executable = _load_executable_intents(knowledge_snapshot_id)
        matches = _match_executable_intents(prompt, executable)
        if matches:
            top = matches[0]
            if len(matches) > 1 and int(matches[1].get("_match_hits", 0)) == int(top.get("_match_hits", 0)):
                from nlc.clarification import create_clarify_artifact, ClarificationReason
                candidate_intents = [
                    {"intent_id": m.get("intent_id"), "name": m.get("name", "")}
                    for m in matches
                ]
                create_clarify_artifact(
                    request_id=request_id,
                    policy_version=policy_version,
                    knowledge_snapshot_id=knowledge_snapshot_id,
                    manifest_bundle_hash=manifest_bundle_hash,
                    manifest_hashes=manifest_hashes,
                    reason=ClarificationReason.AMBIGUOUS_INTENT,
                    questions=["Multiple mined intents match. Please clarify."],
                    candidate_intents=candidate_intents,
                    required_fields=[],
                    request_dir=request_dir,
                )
                return False, None, "CLARIFICATION_NEEDED::AMBIGUOUS_INTENT"

            status = str(top.get("status", "")).strip()
            if status == "ACTIVE":
                required_fields = top.get("required_fields", [])
                if isinstance(required_fields, list) and required_fields:
                    from nlc.clarification import create_clarify_artifact, ClarificationReason
                    create_clarify_artifact(
                        request_id=request_id,
                        policy_version=policy_version,
                        knowledge_snapshot_id=knowledge_snapshot_id,
                        manifest_bundle_hash=manifest_bundle_hash,
                        manifest_hashes=manifest_hashes,
                        reason=ClarificationReason.MISSING_REQUIRED_ARG,
                        questions=["Please provide the missing required parameters."],
                        candidate_intents=[{"intent_id": top.get("intent_id"), "name": top.get("name", "")}],
                        required_fields=required_fields,
                        request_dir=request_dir,
                    )
                    return False, None, "CLARIFICATION_NEEDED::MISSING_REQUIRED_ARG"

                req_json = {
                    "schema_version": "req_v1",
                    "intents": [
                        {
                            "intent_type": top.get("intent_id"),
                            "params": {},
                            "io": {"stdout": True},
                            "description": top.get("name", ""),
                        }
                    ],
                    "_intent_trace": {
                        "prompt": prompt,
                        "mined_match": {
                            "intent_id": top.get("intent_id"),
                            "match_hits": top.get("_match_hits", 0),
                            "artifact_class": top.get("artifact_class"),
                            "evidence_ids": top.get("evidence_ids", []),
                        },
                    },
                }
                success = True
                error = None
            else:
                blocked = {
                    "status": "BLOCKED",
                    "reason_code": "BLOCKED_MISSING_MODULE",
                    "prompt": prompt,
                    "intent_id": top.get("intent_id"),
                    "missing_modules": top.get("missing_modules", []),
                    "evidence_ids": top.get("evidence_ids", []),
                }
                (request_dir / "BLOCKED.json").write_text(
                    json.dumps(blocked, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
                return False, None, "BLOCKED::BLOCKED_MISSING_MODULE"

    trace = {}
    if isinstance(req_json, dict) and "_intent_trace" in req_json:
        trace = req_json.get("_intent_trace") or {}
        # never include trace inside REQ.json on disk
        req_json = {k: v for k, v in req_json.items() if k != "_intent_trace"}

    # Always emit INTENT_TRACE.json (even on failure) for auditability
    (request_dir / "INTENT_TRACE.json").write_text(json.dumps(trace, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Step 3: Handle ambiguity with CLARIFY.json instead of guessing
    if not success:
        # Check if this is an ambiguity case that should emit CLARIFY.json
        needs_clarification = False
        clarify_reason = None
        questions = []
        candidate_intents = []
        required_fields = []
        
        if error and "No supported intents matched" in error:
            # UNKNOWN_INTENT case
            needs_clarification = True
            clarify_reason = "UNKNOWN_INTENT"
            questions = ["What intent did you want to use? Please specify from the available intents."]
            # Extract candidate intents from manifest if available
            if intents_manifest:
                ranked = rank_intents(prompt, intents_manifest)
                candidate_intents = [{"intent_id": r["intent_id"], "name": r["name"]} for r in ranked]
        elif error and error.startswith("BLOCKED::"):
            reason = error.split("::", 1)[1].strip()
            if reason == "MISSING_REQUIRED_PARAM":
                needs_clarification = True
                clarify_reason = "MISSING_REQUIRED_ARG"
                questions = ["Please provide the missing required parameters."]
                # Extract missing fields from trace
                if isinstance(trace, dict):
                    pipe = trace.get("pipeline")
                    if isinstance(pipe, dict) and isinstance(pipe.get("blocked"), dict):
                        missing = pipe["blocked"].get("missing", [])
                        required_fields = missing
            elif reason == "AMBIGUOUS_INTENT":
                needs_clarification = True
                clarify_reason = "AMBIGUOUS_INTENT"
                questions = ["Multiple intents match. Which one did you want?"]
                # Extract candidates from trace if available
                if isinstance(trace, dict):
                    candidates = trace.get("candidates", [])
                    candidate_intents = [
                        {"intent_id": c.get("intent_type"), "matched": c.get("matched")}
                        for c in candidates if c.get("matched")
                    ]
        
        if needs_clarification and clarify_reason:
            # Emit CLARIFY.json
            from nlc.clarification import create_clarify_artifact, ClarificationReason
            
            reason_enum = {
                "AMBIGUOUS_INTENT": ClarificationReason.AMBIGUOUS_INTENT,
                "MISSING_REQUIRED_ARG": ClarificationReason.MISSING_REQUIRED_ARG,
                "UNKNOWN_INTENT": ClarificationReason.UNKNOWN_INTENT,
            }.get(clarify_reason, ClarificationReason.AMBIGUOUS_INTENT)
            
            create_clarify_artifact(
                request_id=request_id,
                policy_version=policy_version,
                knowledge_snapshot_id=knowledge_snapshot_id,
                manifest_bundle_hash=manifest_bundle_hash,
                manifest_hashes=manifest_hashes,
                reason=reason_enum,
                questions=questions,
                candidate_intents=candidate_intents,
                required_fields=required_fields,
                request_dir=request_dir,
            )
            return False, None, f"CLARIFICATION_NEEDED::{clarify_reason}"
        
        # Legacy BLOCKED.json for non-clarification blocks
        if error and error.startswith("BLOCKED::"):
            reason = (error or "").split("::", 1)[1].strip()
            blocked_path = request_dir / "BLOCKED.json"
            if not blocked_path.exists():
                blocked = {"status": "BLOCKED", "reason_code": reason, "prompt": prompt}
                if isinstance(trace, dict):
                    pipe = trace.get("pipeline") if isinstance(trace.get("pipeline"), dict) else None
                    if pipe and isinstance(pipe.get("blocked"), dict):
                        blocked["details"] = pipe.get("blocked")
                blocked_path.write_text(
                    json.dumps(blocked, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )

    # Validate intents against manifest if available
    if success and req_json and intents_manifest:
        intents_list = req_json.get("intents", [])
        mined_ids = set()
        if knowledge_snapshot_id:
            # Do not use classified intents for execution - legacy intents only
            executable_ids = set()
        for intent in intents_list:
            intent_id = intent.get("intent_type") or intent.get("intent_id")
            if intent_id and intent_id not in intents_manifest:
                # Intent not in snapshot manifest - emit clarification
                from nlc.clarification import create_clarify_artifact, ClarificationReason
                
                create_clarify_artifact(
                    request_id=request_id,
                    policy_version=policy_version,
                    knowledge_snapshot_id=knowledge_snapshot_id,
                    manifest_bundle_hash=manifest_bundle_hash,
                    manifest_hashes=manifest_hashes,
                    reason=ClarificationReason.UNKNOWN_INTENT,
                    questions=[f"Intent '{intent_id}' is not in the snapshot manifest. Please use a valid intent."],
                    candidate_intents=[
                        {"intent_id": iid, "name": data.get("name", iid)}
                        for iid, data in sorted(intents_manifest.items())
                    ],
                    required_fields=[],
                    request_dir=request_dir,
                )
                return False, None, f"CLARIFICATION_NEEDED::UNKNOWN_INTENT"

    # Enrich intents with module_refs from intents_v1 (snapshot or policy) when missing
    if success and req_json and knowledge_snapshot_id:
        intents_list = req_json.get("intents", [])
        v1_intents = _load_intents_v1_for_enrichment(knowledge_snapshot_id)
        if v1_intents:
            for intent in intents_list:
                if intent.get("module_refs"):
                    continue
                intent_id = intent.get("intent_type") or intent.get("intent_id")
                if not intent_id:
                    continue
                match = next((e for e in v1_intents if str(e.get("intent_id", "")) == str(intent_id)), None)
                if match and match.get("module_refs"):
                    intent["module_refs"] = list(match["module_refs"])

    if success and req_json:
        if "schema_version" not in req_json:
            req_json = dict(req_json)
            req_json["schema_version"] = "req_v1"
        (request_dir / "REQ.json").write_text(json.dumps(req_json, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return True, req_json, None

    return False, None, error or "Failed to compile prompt to REQ.json"


def compile_prompt_to_req(
    prompt: str,
    request_id: Optional[str] = None,
    request_dir: Optional[Path] = None,
    policy_version: Optional[str] = None,
    knowledge_snapshot_id: Optional[str] = None,
    manifest_bundle_hash: Optional[str] = None,
    manifest_hashes: Optional[Dict[str, str]] = None,
    repro_mode: bool = False,
    overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Thin wrapper around compile_with_fallback for Exec20 and other callers.
    Accepts repro_mode and overrides for API compatibility; they are not used.
    """
    if request_dir is None and request_id:
        request_dir = Path("state") / "requests" / request_id
    elif request_dir is None:
        raise ValueError("request_dir or request_id required")
    if isinstance(request_dir, str):
        request_dir = Path(request_dir)
    return compile_with_fallback(
        prompt,
        request_dir,
        request_id=request_id,
        policy_version=policy_version,
        knowledge_snapshot_id=knowledge_snapshot_id,
        manifest_bundle_hash=manifest_bundle_hash,
        manifest_hashes=manifest_hashes,
        overrides=overrides,
    )
