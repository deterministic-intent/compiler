#!/usr/bin/env bash
set -euo pipefail

banned_ext_regex='\.(gguf|ggml|safetensors|pt|pth|onnx)$'
if git ls-files | grep -Eiq "$banned_ext_regex"; then
  echo "FAIL: banned model artifact extension found in tracked files."
  git ls-files | grep -Ei "$banned_ext_regex" || true
  exit 2
fi

if git ls-files | grep -Eiq '^(models/|llama\.cpp/|ollama/)'; then
  echo "FAIL: banned directory tracked (models/ or llama.cpp/ or ollama/)."
  git ls-files | grep -Ei '^(models/|llama\.cpp/|ollama/)' || true
  exit 2
fi

banned_terms=(
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

# Exclude policy doc and verifier; exclude v1 architectural paths (adapters, policy schema)
exclude_pattern='^policy/NO_LLM_RULE\.md$|^scripts/ci/|^nlc/llm_|^nlc/prompt_compiler\.py|^policy/policy|^scripts/verify_milestone_4_|^scripts/verify_step7\.py|^scripts/run_replay\.py|^workers/run_repair\.py'
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
