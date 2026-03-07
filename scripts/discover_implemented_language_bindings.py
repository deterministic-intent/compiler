#!/usr/bin/env python3
"""
Discover actual implemented language bindings from on-disk modules and generator branches.
Outputs out/debug_language_discovery.json: {language: [artifact_class, ...]}.
Deterministic, snapshot-pinned.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
MODULES_ROOT = BASE / "orchestrator" / "modules"
OUT_PATH = BASE / "out" / "debug_language_discovery.json"

# artifact_class -> language when no explicit language in module
_AC_TO_LANG: dict[str, str] = {
    "bash_cli": "bash",
    "c_cli": "c",
    "cpp_cli": "cpp",
    "csharp_cli": "csharp",
    "docker_image": "docker",
    "go_cli": "go",
    "html_site": "html",
    "java_cli": "java",
    "javascript_web": "javascript",
    "kotlin_cli": "kotlin",
    "mongodb_pack": "mongodb",
    "php_cli": "php",
    "python_cli": "python",
    "python_api": "python",
    "python_gui": "python",
    "python_debug_script": "python",
    "ruby_cli": "ruby",
    "rust_cli": "rust",
    "solidity_contract": "solidity",
    "sql_pack": "sql",
    "typescript_cli": "typescript",
    "yaml_config": "yaml",
}

# webview uses web_site module; supports html, javascript, typescript
_WEBVIEW_LANGS = ["html", "javascript", "typescript"]


def _add(bindings: dict[str, list[str]], lang: str, ac: str) -> None:
    if lang not in bindings:
        bindings[lang] = []
    if ac not in bindings[lang]:
        bindings[lang].append(ac)


def main() -> int:
    bindings: dict[str, list[str]] = {}

    # 1) From modules
    for p in sorted(MODULES_ROOT.rglob("*.json")):
        rel = p.relative_to(MODULES_ROOT)
        parts = rel.parts
        if len(parts) < 1:
            continue

        ac_from_path = parts[0]
        lang: str | None = None

        # lang/* excluded from v1: not in snapshot supported_artifact_classes
        if parts[0] == "lang":
            continue

        try:
            mod = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            if isinstance(mod, dict) and mod.get("language"):
                lang = str(mod["language"]).strip()
        except Exception:
            pass

        if not lang and ac_from_path in _AC_TO_LANG:
            lang = _AC_TO_LANG[ac_from_path]

        if not lang:
            continue

        # web_site -> webview for html (generator uses webview)
        if ac_from_path == "web_site" and lang == "html":
            for wl in _WEBVIEW_LANGS:
                _add(bindings, wl, "webview")
        else:
            _add(bindings, lang, ac_from_path)

    # 2) From generator branches: python_api, python_gui have no dedicated module
    for ac in ("python_api", "python_gui"):
        _add(bindings, "python", ac)

    for k in bindings:
        bindings[k] = sorted(bindings[k])
    bindings = dict(sorted(bindings.items()))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "schema_version": "v1",
        "source": "orchestrator/modules + generator branches",
        "implemented_language_bindings": bindings,
    }
    OUT_PATH.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
