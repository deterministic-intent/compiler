#!/usr/bin/env python3
"""Deterministic KB snapshot builder (offline in repro)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from typing import Optional

from nlc.net_guard import assert_network_allowed, repro_mode_enabled
from nlc.kb.canonicalize import canonicalize_url, html_to_text

# Policy loader (optional - for future policy-aware snapshot building)
try:
    from policy import load_policy, get_default_policy_version
except ImportError:
    load_policy = None
    get_default_policy_version = None


def get_policy_for_snapshot(policy_version: Optional[str] = None):
    """
    Get policy for snapshot building. Step 1: wiring only - no enforcement yet.
    
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


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256_file(p: Path) -> str:
    return _sha256_bytes(p.read_bytes())


def derive_snapshot_id(sources: list[str]) -> str:
    canon = [canonicalize_url(s) for s in sources]
    canon.sort()
    return _sha256_bytes('\n'.join(canon).encode('utf-8'))[:12]


def _load_allowlist(base: Path) -> list[str]:
    allowlist_txt = base / 'contracts' / 'web_allowlist.txt'
    out: list[str] = []
    if allowlist_txt.exists():
        for line in allowlist_txt.read_text(encoding='utf-8', errors='replace').splitlines():
            t = line.strip().lower()
            if not t or t.startswith('#'):
                continue
            out.append(t)
    return out


def _host_allowed(host: str, allow: list[str]) -> bool:
    h = host.lower()
    for a in allow:
        if h == a or h.endswith('.' + a):
            return True
    return False


def _fetch_bytes(url: str, allow: list[str]) -> bytes:
    u = urlparse(url)
    if u.scheme in ('http', 'https'):
        if repro_mode_enabled():
            assert_network_allowed('kb_fetch')
        if not u.hostname:
            raise RuntimeError('URL missing hostname')
        if not _host_allowed(u.hostname, allow):
            raise RuntimeError(f'Host not allowed: {u.hostname}')
        req = Request(url, headers={'User-Agent': 'nlc-kb-builder/1.0'})
        with urlopen(req, timeout=30) as resp:
            return resp.read()
    if u.scheme == 'file':
        return Path(u.path).read_bytes()
    if u.scheme == '':
        return Path(url).read_bytes()
    raise RuntimeError(f'Unsupported URL scheme: {u.scheme}')


def compute_snapshot_hash(snapshot_dir: Path) -> str:
    files = sorted([p for p in snapshot_dir.rglob('*') if p.is_file()], key=lambda p: str(p.relative_to(snapshot_dir)))
    parts: list[str] = []
    for fp in files:
        rel = str(fp.relative_to(snapshot_dir))
        if rel == 'SNAPSHOT.sha256':
            continue
        parts.append(rel)
        parts.append(_sha256_file(fp))
    return _sha256_bytes('\n'.join(parts).encode('utf-8'))


def build_snapshot(base: Path, snapshot_id: str, sources: list[str], write_latest: bool = True) -> Path:
    if not sources:
        raise RuntimeError('sources required')
    if not snapshot_id or snapshot_id == 'AUTO':
        snapshot_id = derive_snapshot_id(sources)

    kb_root = base / 'nlc' / 'kb'
    (kb_root / 'snapshots').mkdir(parents=True, exist_ok=True)
    snap_dir = kb_root / 'snapshots' / snapshot_id
    docs_dir = snap_dir / 'docs'
    docs_dir.mkdir(parents=True, exist_ok=True)
    (snap_dir / 'examples').mkdir(parents=True, exist_ok=True)

    allow = _load_allowlist(base)
    documents: list[dict] = []

    for src in sorted(list(sources)):
        canon_url = canonicalize_url(src)
        doc_id = hashlib.sha256(canon_url.encode('utf-8')).hexdigest()[:16]
        raw = _fetch_bytes(src, allow)
        txt = html_to_text(raw.decode('utf-8', errors='replace'))
        out_path = docs_dir / f'{doc_id}.txt'
        out_path.write_text(txt, encoding='utf-8')
        documents.append({
            'doc_id': doc_id,
            'path': f'docs/{doc_id}.txt',
            'source_url': canon_url,
            'content_sha256': _sha256_file(out_path),
            'doc_type': 'docs',
        })

    documents.sort(key=lambda d: (d['doc_id'], d['path']))
    index = {
        'snapshot_id': snapshot_id,
        'created_from': {
            'sources_sha256': _sha256_bytes('\n'.join(sorted([canonicalize_url(s) for s in sources])).encode('utf-8')),
            'count': len(sources),
        },
        'documents': documents,
    }
    (snap_dir / 'index.json').write_text(json.dumps(index, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    snap_hash = compute_snapshot_hash(snap_dir)
    (snap_dir / 'SNAPSHOT.sha256').write_text(snap_hash + '\n', encoding='utf-8')
    if write_latest:
        (kb_root / 'latest').write_text(snapshot_id + '\n', encoding='utf-8')
    return snap_dir
