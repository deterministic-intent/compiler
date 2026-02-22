#!/usr/bin/env python3
"""Deterministic canonicalization for KB snapshots."""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode


_TRACKING_PREFIXES = ('utm_', 'fbclid', 'gclid', 'mc_cid', 'mc_eid')


def canonicalize_url(url: str) -> str:
    u = urlparse(url)
    scheme = (u.scheme or '').lower()
    netloc = (u.netloc or '').lower()
    path = u.path or ''
    fragment = ''

    q = []
    for k, v in parse_qsl(u.query, keep_blank_values=True):
        kk = (k or '').lower()
        if kk.startswith(_TRACKING_PREFIXES) or kk in _TRACKING_PREFIXES:
            continue
        q.append((k, v))
    q.sort(key=lambda kv: (kv[0], kv[1]))
    query = urlencode(q, doseq=True)

    if path != '/' and path.endswith('/'):
        path = path[:-1]

    return urlunparse((scheme, netloc, path, u.params, query, fragment))


_LAST_UPDATED_RE = re.compile(r'(?im)^\s*(last\s+updated|updated|last\s+modified)\b.*$')


def canonicalize_text(text: str) -> str:
    s = text.replace('\r\n', '\n').replace('\r', '\n')
    s = _LAST_UPDATED_RE.sub('', s)
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip() + '\n'


def html_to_text(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
            tag.decompose()
        txt = soup.get_text('\n')
        return canonicalize_text(txt)
    except Exception:
        s = re.sub(r'(?is)<script.*?>.*?</script>', ' ', html)
        s = re.sub(r'(?is)<style.*?>.*?</style>', ' ', s)
        s = re.sub(r'(?is)<[^>]+>', '\n', s)
        return canonicalize_text(s)
