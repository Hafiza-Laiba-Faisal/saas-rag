# RBS RAG CLI Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working CLI-first RAG foundation with reusable services for future UI/API integration.

**Architecture:** A Python package provides ingestion, retrieval, memory, validation, and LLM orchestration services. The CLI is a thin adapter over those services. Local storage and embeddings keep the baseline runnable without external services; only final LLM generation requires a configured API key.

**Tech Stack:** Python 3.11+, argparse, sqlite3, urllib, unittest, optional qdrant-client/fastembed/pypdf extras.

---

### Task 1: Test Contract

**Files:**
- Create: `tests/test_config.py`
- Create: `tests/test_chunking.py`
- Create: `tests/test_engine_retrieval.py`
- Create: `tests/test_llm.py`
- Create: `tests/test_cli.py`

- [x] **Step 1: Write failing tests**

Tests define config initialization, chunking, ingestion/search, metadata filtering, LLM provider detection, prompt construction, and CLI smoke behavior.

- [x] **Step 2: Run tests and confirm failure**

Run: `python -m unittest discover -s tests -v`
Expected: failures due to missing `rbs_rag` modules.

### Task 2: Core Package

**Files:**
- Create: `src/rbs_rag/*.py`
- Create: `pyproject.toml`
- Create: `.gitignore`

- [x] **Step 1: Implement minimal modules**

Implement config, loading, chunking, embeddings, storage, retrieval, reranking, memory, validation, LLM adapters, engine orchestration, and CLI.

- [x] **Step 2: Run tests**

Run: `python -m unittest discover -s tests -v`
Expected: all tests pass.

### Task 3: CLI Smoke

**Files:**
- Modify: `README.md`

- [x] **Step 1: Document setup and CLI flow**

Include `rag init`, `rag ingest`, `rag search`, `rag ask`, and API config examples.

- [x] **Step 2: Run smoke commands**

Run project initialization, ingest a sample file, and search it.

### Self-Review

- Spec coverage: CLI, ingestion, chunking, retrieval, metadata, memory, validation, LLM API adapters, and future UI reuse are covered.
- Placeholder scan: no TBD/TODO implementation placeholders.
- Type consistency: service names and command names match the test contract.

