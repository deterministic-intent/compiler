#!/usr/bin/env python3
"""
DB miner for intent discovery.

Reads the latest (or env-pinned) DB snapshot and mines existing content to
propose new deterministic capabilities. It does NOT rely on user prompts.

Outputs (read-only analysis):
  - coverage_report.json (summary of counts)
  - intent_candidates.json (ranked op/format signals with evidence + risk)
  - coverage_gaps.json (decision-grade intent shortlist with evidence)
  - ngrams.csv (top n-grams from titles/content)
  - formats.csv (file/format mentions)
  - operations.csv (operation keyword counts)
  - stacks.csv (stack/language/resource counts)
"""

from __future__ import annotations

import collections
import csv
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Counter, Iterable

BASE = Path(__file__).resolve().parents[1]
DB_ROOT = BASE / "nlc" / "db"


def get_db_snapshot_id() -> str:
    sid = os.environ.get("NLC_DB_SNAPSHOT_ID", "").strip()
    if sid:
        return sid
    latest = DB_ROOT / "latest"
    if latest.exists():
        return latest.read_text(encoding="utf-8", errors="replace").strip()
    return ""


def tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z]{3,}", (text or "").lower())


def ngrams(tokens: Iterable[str], n: int = 2) -> Iterable[str]:
    toks = list(tokens)
    for i in range(len(toks) - n + 1):
        yield " ".join(toks[i : i + n])


def extract_formats(text: str) -> list[str]:
    out = []
    t = text.lower()
    for ext in ["csv", "json", "xml", "yaml", "yml", "pdf", "md", "txt", "html", "sql", "parquet", "zip", "log"]:
        if re.search(rf"\b{ext}\b", t):
            out.append(ext)
    # file extensions
    for m in re.findall(r"\.[a-z0-9]{2,5}", t):
        out.append(m.lstrip("."))
    return out


def extract_operations(text: str) -> list[str]:
    t = text.lower()
    ops = []
    for kw in [
        "sort",
        "filter",
        "count",
        "unique",
        "dedupe",
        "select",
        "head",
        "tail",
        "stats",
        "sum",
        "grep",
        "regex",
        "split",
        "join",
        "convert",
        "format",
        "pretty",
        "encode",
        "decode",
        "parse",
        "extract",
        "validate",
        "diff",
    ]:
        if re.search(rf"\b{kw}\b", t):
            ops.append(kw)
    return ops


def extract_domain(url: str | None) -> str:
    if not url:
        return ""
    m = re.match(r"https?://([^/]+)/?", url)
    return m.group(1).lower() if m else ""


def extract_resources(text: str) -> list[str]:
    t = text.lower()
    out = []
    if re.search(r"\bstdin\b|\bstandard input\b", t):
        out.append("stdin")
    if re.search(r"\bfile\b|\bpath\b", t):
        out.append("file")
    if re.search(r"http://|https://|\burl\b", t):
        out.append("url")
    if re.search(r"\bdb\b|\bdatabase\b|\bsql\b", t):
        out.append("db")
    if re.search(r"\bdocker\b", t):
        out.append("docker")
    if re.search(r"\bk8s\b|\bkubernetes\b", t):
        out.append("k8s")
    if re.search(r"\bgit\b", t):
        out.append("git")
    if re.search(r"\bstderr\b|\bstdout\b", t):
        out.append("stdio")
    return out


def main() -> None:
    snapshot_id = get_db_snapshot_id()
    if not snapshot_id:
        raise SystemExit("No DB snapshot id found (set NLC_DB_SNAPSHOT_ID or nlc/db/latest).")

    db_path = DB_ROOT / "snapshots" / snapshot_id / "nlc.db"
    live_path = DB_ROOT / "live" / "nlc.db"
    if not db_path.exists() and live_path.exists():
        db_path = live_path
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    def load_rows(path: Path):
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        try:
            nodes = cur.execute(
                "SELECT title, content, language, stack, tags, source_url FROM nodes"
            ).fetchall()
        except Exception:
            nodes = []
        try:
            docs = cur.execute("SELECT heading, content FROM doc_units").fetchall()
        except Exception:
            docs = []
        try:
            frontier = cur.execute("SELECT url, source, status FROM frontier").fetchall()
        except Exception:
            frontier = []
        return nodes, docs, frontier
        conn.close()

    nodes, docs, frontier = load_rows(db_path)
    if not nodes and live_path.exists() and live_path != db_path:
        nodes, docs, frontier = load_rows(live_path)

    c_tokens: Counter[str] = collections.Counter()
    c_ngrams: Counter[str] = collections.Counter()
    c_formats: Counter[str] = collections.Counter()
    c_ops: Counter[str] = collections.Counter()
    c_stacks: Counter[str] = collections.Counter()
    c_langs: Counter[str] = collections.Counter()
    c_domains: Counter[str] = collections.Counter()
    c_resources: Counter[str] = collections.Counter()
    c_tags: Counter[str] = collections.Counter()
    op_fmt_pairs: Counter[tuple[str, str]] = collections.Counter()
    text_tokens: Counter[str] = collections.Counter()

    for title, content, language, stack, tags_json, source_url in nodes:
        text = " ".join([title or "", content or ""])
        toks = tokenize(text)
        c_tokens.update(toks)
        c_ngrams.update(ngrams(toks, 2))
        formats = extract_formats(text)
        ops = extract_operations(text)
        resources = extract_resources(text)
        c_formats.update(formats)
        c_ops.update(ops)
        c_resources.update(resources)
        for op in set(ops):
            for fmt in set(formats):
                op_fmt_pairs[(op, fmt)] += 1
        if stack:
            c_stacks.update([stack.lower()])
        if language:
            c_langs.update([language.lower()])
        if tags_json:
            tags_tok = tokenize(tags_json)
            c_tags.update(tags_tok)
        text_tokens.update([tok for tok in toks if tok in ("line", "lines", "text", "log", "logs", "column", "columns")])
        dom = extract_domain(source_url)
        if dom:
            c_domains.update([dom])

    for heading, content in docs:
        text = " ".join([heading or "", content or ""])
        toks = tokenize(text)
        c_tokens.update(toks)
        c_ngrams.update(ngrams(toks, 2))
        formats = extract_formats(text)
        ops = extract_operations(text)
        resources = extract_resources(text)
        c_formats.update(formats)
        c_ops.update(ops)
        c_resources.update(resources)
        for op in set(ops):
            for fmt in set(formats):
                op_fmt_pairs[(op, fmt)] += 1
        text_tokens.update([tok for tok in toks if tok in ("line", "lines", "text", "log", "logs", "column", "columns")])

    for url, source, status in frontier:
        text = " ".join([url or "", source or "", status or ""])
        toks = tokenize(text)
        c_tokens.update(toks)
        c_ngrams.update(ngrams(toks, 2))
        formats = extract_formats(text)
        ops = extract_operations(text)
        resources = extract_resources(text)
        c_formats.update(formats)
        c_ops.update(ops)
        c_resources.update(resources)
        for op in set(ops):
            for fmt in set(formats):
                op_fmt_pairs[(op, fmt)] += 1
        text_tokens.update([tok for tok in toks if tok in ("line", "lines", "text", "log", "logs", "column", "columns")])

    # Derive candidate ops+formats combos
    intent_candidates: list[dict[str, object]] = []
    for op, op_cnt in c_ops.most_common(50):
        for fmt, fmt_cnt in c_formats.most_common(20):
            pair_cnt = op_fmt_pairs.get((op, fmt), 0)
            intent_candidates.append(
                {
                    "operation": op,
                    "format": fmt,
                    "score": op_cnt + fmt_cnt + pair_cnt,
                    "op_count": op_cnt,
                    "format_count": fmt_cnt,
                    "op_format_count": pair_cnt,
                }
            )

    # Suggest deterministic gaps (hard-coded shortlist informed by counts)
    suggested = []
    def add_suggestion(
        name: str,
        rationale: str,
        ops: list[str] = None,
        formats: list[str] = None,
        pairs: list[tuple[str, str]] = None,
        resources: list[str] = None,
        extra_tokens: list[str] = None,
        risk: str = "low",
    ):
        ops = ops or []
        formats = formats or []
        pairs = pairs or []
        resources = resources or []
        extra_tokens = extra_tokens or []
        suggested.append(
            {
                "intent": name,
                "rationale": rationale,
                "risk": risk,
                "evidence": {
                    "ops": {op: c_ops.get(op, 0) for op in ops},
                    "formats": {fmt: c_formats.get(fmt, 0) for fmt in formats},
                    "op_format_pairs": {f"{op}×{fmt}": op_fmt_pairs.get((op, fmt), 0) for op, fmt in pairs},
                    "resources": {res: c_resources.get(res, 0) for res in resources},
                    "tokens": {tok: text_tokens.get(tok, 0) for tok in extra_tokens},
                },
            }
        )

    # Signals
    add_suggestion(
        "count_lines",
        "text files + count/head/tail cues imply line-level ops",
        ops=["count", "head", "tail"],
        formats=["txt", "md", "log"],
        resources=["file", "stdin"],
        extra_tokens=["line", "lines"],
        risk="low",
    )
    add_suggestion(
        "count_words",
        "text/log corpus with count cues",
        ops=["count"],
        formats=["txt", "md", "log"],
        resources=["file", "stdin"],
        extra_tokens=["text", "log", "logs"],
        risk="low",
    )
    add_suggestion(
        "head_lines",
        "preview/inspect cues (head) over text files",
        ops=["head"],
        formats=["txt", "md", "log"],
        resources=["file", "stdin"],
        extra_tokens=["line", "lines"],
        risk="low",
    )
    add_suggestion(
        "tail_lines",
        "log-style tail cues",
        ops=["tail"],
        formats=["txt", "md", "log"],
        resources=["file", "stdin"],
        extra_tokens=["log", "logs"],
        risk="low",
    )
    add_suggestion(
        "grep_regex",
        "regex/grep mentions over text sources",
        ops=["grep", "regex"],
        formats=["txt", "md", "log"],
        pairs=[("grep", "txt"), ("regex", "txt")],
        resources=["stdin", "file"],
        extra_tokens=["line", "text"],
        risk="medium",
    )
    add_suggestion(
        "csv_select_columns",
        "csv + select/column patterns",
        ops=["select"],
        formats=["csv"],
        pairs=[("select", "csv")],
        resources=["file"],
        extra_tokens=["column", "columns"],
        risk="medium",
    )
    add_suggestion(
        "csv_sort_by_column",
        "csv + sort patterns",
        ops=["sort"],
        formats=["csv"],
        pairs=[("sort", "csv")],
        resources=["file"],
        extra_tokens=["column", "columns"],
        risk="medium",
    )
    add_suggestion(
        "json_pretty_print",
        "json + format/pretty mentions",
        ops=["format", "pretty"],
        formats=["json"],
        pairs=[("format", "json"), ("pretty", "json")],
        resources=["file", "stdin"],
        risk="low",
    )

    out_dir = BASE / "nlc"
    out_dir.mkdir(parents=True, exist_ok=True)

    coverage = {
        "snapshot_id": snapshot_id,
        "total_rows": len(nodes),
        "top_tokens": c_tokens.most_common(100),
        "top_ngrams": c_ngrams.most_common(100),
        "top_formats": c_formats.most_common(50),
        "top_operations": c_ops.most_common(50),
        "top_stacks": c_stacks.most_common(50),
        "top_languages": c_langs.most_common(50),
        "top_domains": c_domains.most_common(50),
        "top_resources": c_resources.most_common(50),
        "top_tags": c_tags.most_common(50),
        "snapshot_source": str(db_path),
    }
    (out_dir / "coverage_report.json").write_text(json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with (out_dir / "ngrams.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ngram", "count"])
        for ngram, cnt in c_ngrams.most_common(200):
            w.writerow([ngram, cnt])

    with (out_dir / "formats.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["format", "count"])
        for fmt, cnt in c_formats.most_common(100):
            w.writerow([fmt, cnt])

    with (out_dir / "operations.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["operation", "count"])
        for op, cnt in c_ops.most_common(100):
            w.writerow([op, cnt])

    with (out_dir / "stacks.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["stack_or_language", "count"])
        for s, cnt in c_stacks.most_common(50):
            w.writerow([s, cnt])
        for l, cnt in c_langs.most_common(50):
            w.writerow([l, cnt])
        for r, cnt in c_resources.most_common(50):
            w.writerow([r, cnt])

    (out_dir / "intent_candidates.json").write_text(
        json.dumps({"snapshot_id": snapshot_id, "candidates": intent_candidates}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    (out_dir / "coverage_gaps.json").write_text(
        json.dumps({"snapshot_id": snapshot_id, "suggested": suggested}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

