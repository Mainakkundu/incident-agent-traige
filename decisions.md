# Decisions

## 2026-08-31

- Removed `load_logs.py`: marked dead in `AGENT.md`; log generation/loading now proceeds through the active data setup scripts.

## 2026-09-01

- Use local Hugging Face `sentence-transformers/all-mpnet-base-v2` embeddings for runbooks and past incidents. This keeps embedding generation free after model download while still storing real pgvector values; unit tests use fake providers and do not download the model.
