#!/usr/bin/env bash
set -euo pipefail

banned_ext_regex='\.(gguf|ggml|safetensors|pt|pth|onnx)$'
if git ls-files | grep -Eiq "$banned_ext_regex"; then
  echo "FAIL: banned model artifact extension found in tracked files."
  git ls-files | grep -Ei "$banned_ext_regex" || true
  exit 2
fi

banned_matches=$(git ls-files | grep -Ei '^(\.cursor/|agents/|agent/|prompts/|scraper/|scrapers/|scraper_audit_staging/|db/|nlc/db/|models/|llama\.cpp/|ollama/)' || true)
# Allow proof-critical nlc/db code (__init__.py, manifest_builder.py)
allowed_nlc_db='^nlc/db/__init__\.py$|^nlc/db/manifest_builder\.py$'
remaining=$(echo "$banned_matches" | grep -vE "$allowed_nlc_db" || true)
if [ -n "$remaining" ]; then
  echo "FAIL: banned directory tracked."
  echo "$remaining"
  exit 2
fi

banned_terms=(
  "cursor"
  "Cursor"
  "LLM"
  "OpenAI"
  "GPT"
  "llama"
  "ollama"
  "gguf"
  "ggml"
  "safetensors"
  "huggingface"
  "Qwen"
  "Mistral"
  "Anthropic"
  "Claude"
  "Gemini"
  "Groq"
  "LangChain"
)

# Exclude policy doc and verifier; exclude v1 architectural paths (adapters, policy schema); exclude SQL cursor usage
# Exclude README, docs, and paths that document LLM-as-adapter architecture (no LLM, untrusted adapter, etc.)
exclude_pattern='^policy/NO_LLM_RULE\.md$|^scripts/ci/|^nlc/llm_|^nlc/prompt_compiler\.py|^policy/policy|^scripts/verify_milestone_4_|^scripts/verify_step7\.py|^scripts/run_replay\.py|^workers/run_repair\.py|^nlc/index/index_builder\.py$|^nlc/db_miner\.py$|^nlc/regression_suite\.py$|^scripts/migrate_delta_schema\.py$|^workers/run_generator\.py$|^\.github/|^README\.md$|^docs/|^dcs_cli/main\.py$|^orchestrator/api_server\.py$|^scripts/audit/|^scripts/e2e/run_e2e0\.py$|^scripts/suites/verify_golden_replay\.py$|^workers/run_verifier\.py$'
files=$(git ls-files | grep -E '\.(md|txt|py|js|ts|tsx|json|yml|yaml|sh|bash|toml)$' | grep -vE "$exclude_pattern" || true)

for term in "${banned_terms[@]}"; do
  if [ -n "$files" ]; then
    match=$(echo "$files" | xargs grep -RIn --fixed-strings -- "$term" 2>/dev/null || true)
    if [ -n "$match" ]; then
      echo "FAIL: banned term detected: $term"
      echo "$match" | head -n 100
      exit 2
    fi
  fi
done

echo "OK: no model artifacts or references detected."
