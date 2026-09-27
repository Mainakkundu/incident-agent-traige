# Decisions

## 2026-08-31

- Removed `load_logs.py`: marked dead in `AGENT.md`; log generation/loading now proceeds through the active data setup scripts.

## 2026-09-01

- Use local Hugging Face `sentence-transformers/all-mpnet-base-v2` embeddings for runbooks and past incidents. This keeps embedding generation free after model download while still storing real pgvector values; unit tests use fake providers and do not download the model.

## 2026-09-18

- Added `scripts/llm_tool_execute_smoke_01.py` as the full gld_001 LLM loop smoke. It lets the model choose read tools and arguments, executes those tools, feeds results back, and traces the final diagnosis in Phoenix.
- Added a dependency-target guard to the smoke loop: if CMDB results expose `depends_on` targets, the loop will not accept a final answer until those target services have had logs inspected. This is derived from tool output and prevents premature finalization without hardcoding the target service or tool arguments.
