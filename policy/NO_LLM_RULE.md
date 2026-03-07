NO LLM / MODEL POLICY (HARD RULE)

This repository must contain ZERO:
- model weights / binaries
- model tooling artifacts
- vendor/model references in docs/scripts/workflows

Prohibited binaries / extensions (tracked files):
- *.gguf, *.ggml, *.safetensors, *.pt, *.pth, *.onnx

Prohibited tracked directories:
- models/
- llama.cpp/
- ollama/

Prohibited terms in tracked text sources (selected extensions):
- LLM, OpenAI, GPT, llama, ollama, gguf, ggml, safetensors, huggingface,
  Qwen, Mistral, Anthropic, Claude, Gemini, Groq, LangChain

Enforcement:
- scripts/ci/verify_no_llm_artifacts.sh must pass locally and in CI.
- CI failure is mandatory if any prohibited artifact or reference exists.
