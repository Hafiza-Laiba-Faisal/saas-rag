"""RAG Evaluation / Quality loop.

Stores an evaluation dataset (question bank), runs evaluations against the live
retrieval + generation pipeline, computes retrieval and answer metrics, and
analyzes knowledge-base quality. Tables live in the per-tenant SQLite database.

Metrics:
    Hit@5 / Recall@5  — expected document/chunk found in top-5 context
    Faithfulness      — answer supported by retrieved context (LLM-judged)
    Relevancy         — answer addresses the question (LLM-judged)
    RAG Score         — overall = mean(hit_rate, faithfulness, relevancy)
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .llm import create_llm_client

log = logging.getLogger(__name__)

_EVAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluation_cases (
    case_id           TEXT PRIMARY KEY,
    tenant_id         TEXT NOT NULL,
    dataset_id        TEXT NOT NULL DEFAULT 'default',
    question          TEXT NOT NULL,
    expected_answer   TEXT,
    expected_document TEXT,
    expected_chunk_id TEXT,
    source            TEXT NOT NULL DEFAULT 'manual',
    created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS evaluation_runs (
    run_id             TEXT PRIMARY KEY,
    tenant_id          TEXT NOT NULL,
    dataset_id         TEXT NOT NULL DEFAULT 'default',
    status             TEXT NOT NULL DEFAULT 'running',
    total_cases        INTEGER NOT NULL DEFAULT 0,
    passed_cases       INTEGER NOT NULL DEFAULT 0,
    retrieval_hit_rate REAL,
    faithfulness_score REAL,
    relevancy_score    REAL,
    overall_score      REAL,
    config_snapshot    TEXT NOT NULL DEFAULT '{}',
    started_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at       TEXT
);

CREATE TABLE IF NOT EXISTS evaluation_results (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id             TEXT NOT NULL,
    case_id            TEXT NOT NULL,
    question           TEXT NOT NULL,
    expected_document  TEXT,
    retrieval_hit      INTEGER NOT NULL DEFAULT 0,
    retrieved_chunks   TEXT NOT NULL DEFAULT '[]',
    generated_answer   TEXT,
    faithfulness_score REAL,
    relevancy_score    REAL,
    failure_type       TEXT,
    evaluation_reason  TEXT
);
"""


def _utcnow() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.strip().lower())


def _document_hit(chunk_metadata: dict, expected_document: str | None, expected_chunk_id: str | None) -> bool:
    """True if a retrieved chunk matches the case's expected document/chunk."""
    if expected_chunk_id and chunk_metadata.get("chunk_id") == expected_chunk_id:
        return True
    if expected_document:
        doc_name = chunk_metadata.get("document_name") or chunk_metadata.get("name") or ""
        if _normalize(expected_document) == _normalize(doc_name):
            return True
        # Loose containment fallback (e.g. "coworking" in "coworking - Hotel X")
        exp = _normalize(expected_document)
        act = _normalize(doc_name)
        if exp and act and (exp in act or act in exp):
            return True
    return False


class EvaluationStore:
    """Question bank + evaluation run persistence (per-tenant SQLite)."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(_EVAL_SCHEMA)
            conn.commit()

    # ── Cases ──────────────────────────────────────────────────────────────────

    def list_cases(self, tenant_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evaluation_cases WHERE tenant_id = ? ORDER BY created_at DESC, rowid DESC",
                (tenant_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_case(self, case_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM evaluation_cases WHERE case_id = ?", (case_id,)).fetchone()
            return dict(row) if row else None

    def add_case(
        self,
        tenant_id: str,
        question: str,
        expected_answer: str | None = None,
        expected_document: str | None = None,
        expected_chunk_id: str | None = None,
        source: str = "manual",
    ) -> dict:
        case_id = uuid.uuid4().hex[:12]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO evaluation_cases
                    (case_id, tenant_id, question, expected_answer, expected_document, expected_chunk_id, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (case_id, tenant_id, question, expected_answer, expected_document, expected_chunk_id, source, _utcnow()),
            )
            conn.commit()
        return self.get_case(case_id)

    def update_case(self, case_id: str, fields: dict) -> dict | None:
        allowed = {"question", "expected_answer", "expected_document", "expected_chunk_id"}
        sets = []
        values: list = []
        for key in allowed:
            if key in fields:
                sets.append(f"{key} = ?")
                values.append(fields[key])
        if not sets:
            return self.get_case(case_id)
        values.append(case_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE evaluation_cases SET {', '.join(sets)} WHERE case_id = ?", values)
            conn.commit()
        return self.get_case(case_id)

    def delete_case(self, case_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM evaluation_cases WHERE case_id = ?", (case_id,))
            conn.commit()

    # ── Runs ───────────────────────────────────────────────────────────────────

    def create_run(self, tenant_id: str, config_snapshot: dict) -> str:
        run_id = uuid.uuid4().hex[:12]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO evaluation_runs
                    (run_id, tenant_id, status, total_cases, config_snapshot, started_at)
                VALUES (?, ?, 'running', 0, ?, ?)
                """,
                (run_id, tenant_id, json.dumps(config_snapshot), _utcnow()),
            )
            conn.commit()
        return run_id

    def list_runs(self, tenant_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evaluation_runs WHERE tenant_id = ? ORDER BY started_at DESC",
                (tenant_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_run(self, run_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM evaluation_runs WHERE run_id = ?", (run_id,)).fetchone()
            return dict(row) if row else None

    def update_run(self, run_id: str, fields: dict) -> None:
        allowed = {"status", "total_cases", "passed_cases", "retrieval_hit_rate", "faithfulness_score", "relevancy_score", "overall_score", "completed_at"}
        sets = []
        values: list = []
        for key in allowed:
            if key in fields:
                sets.append(f"{key} = ?")
                values.append(fields[key])
        if not sets:
            return
        values.append(run_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE evaluation_runs SET {', '.join(sets)} WHERE run_id = ?", values)
            conn.commit()

    def get_run_results(self, run_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evaluation_results WHERE run_id = ? ORDER BY id ASC",
                (run_id,),
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["retrieved_chunks"] = json.loads(d.get("retrieved_chunks") or "[]")
                results.append(d)
            return results

    def add_result(self, run_id: str, result: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO evaluation_results
                    (run_id, case_id, question, expected_document, retrieval_hit, retrieved_chunks,
                     generated_answer, faithfulness_score, relevancy_score, failure_type, evaluation_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    result["case_id"],
                    result["question"],
                    result.get("expected_document"),
                    int(result.get("retrieval_hit", False)),
                    json.dumps(result.get("retrieved_chunks", [])),
                    result.get("generated_answer"),
                    result.get("faithfulness_score"),
                    result.get("relevancy_score"),
                    result.get("failure_type"),
                    result.get("evaluation_reason"),
                ),
            )
            conn.commit()


# ── LLM helpers ───────────────────────────────────────────────────────────────

def _extract_json(text: str) -> Any:
    """Best-effort parse of a JSON object/array possibly wrapped in fences."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Find the outermost {...} or [...] block
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == open_ch:
                depth += 1
            elif text[i] == close_ch:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    return None


_JUDGE_SYSTEM = (
    "You are a strict RAG evaluator. Rate answers on two scales, 0.0 to 1.0.\n"
    "faithfulness: how much of the answer is directly supported by the retrieved context "
    "(0 = hallucinated/unsupported, 1 = fully grounded).\n"
    "relevancy: how well the answer addresses the user's question (0 = off-topic, 1 = fully relevant).\n"
    "Return ONLY a JSON object: {\"faithfulness\": <float>, \"relevancy\": <float>, \"reason\": \"<short note>\"}"
)


def _judge_answer(client, question: str, answer: str, contexts: list[dict], expected_answer: str | None = None) -> dict:
    """LLM-judge an answer; falls back to lexical heuristics when the LLM fails."""
    fallback: dict = {"faithfulness": 1.0, "relevancy": 1.0, "reason": "lexical fallback"}
    if not answer or not answer.strip():
        return {"faithfulness": 0.0, "relevancy": 0.0, "reason": "empty answer"}

    ctx_text = "\n\n".join(
        f"[{i + 1}] {c.get('document_name', 'doc')}: {(c.get('text') or '')[:600]}" for i, c in enumerate(contexts[:5])
    )
    user = (
        f"Question: {question}\n\nRetrieved context:\n{ctx_text}\n\n"
        f"Generated answer:\n{answer}"
        + (f"\n\nExpected answer (reference): {expected_answer}" if expected_answer else "")
    )
    try:
        raw = client.generate([{"role": "system", "content": _JUDGE_SYSTEM}, {"role": "user", "content": user}])
        data = _extract_json(raw)
        if isinstance(data, dict):
            faithfulness = float(data.get("faithfulness", 0.0))
            relevancy = float(data.get("relevancy", 0.0))
            return {
                "faithfulness": max(0.0, min(1.0, faithfulness)),
                "relevancy": max(0.0, min(1.0, relevancy)),
                "reason": str(data.get("reason", ""))[:300],
            }
    except Exception as exc:
        log.warning("LLM judge failed (%s); using lexical fallback", exc)

    # Lexical fallback: overlap between answer and context/question
    answer_tokens = set(re.findall(r"[a-z0-9]{3,}", answer.lower()))
    if contexts:
        ctx_tokens = set()
        for c in contexts:
            ctx_tokens |= set(re.findall(r"[a-z0-9]{3,}", (c.get("text") or "").lower()))
        fallback["faithfulness"] = round(len(answer_tokens & ctx_tokens) / max(1, len(answer_tokens)), 2)
    q_tokens = set(re.findall(r"[a-z0-9]{3,}", question.lower()))
    fallback["relevancy"] = round(len(answer_tokens & q_tokens) / max(1, min(len(q_tokens), len(answer_tokens))), 2)
    return fallback


# ── Evaluation run ────────────────────────────────────────────────────────────

def run_evaluation(
    engine,
    tenant_id: str,
    store: EvaluationStore,
    run_id: str,
    case_ids: list[str] | None = None,
    progress_cb=None,
) -> dict:
    """Run one evaluation pass over the question bank against the live pipeline."""
    cases = store.list_cases(tenant_id)
    if case_ids:
        wanted = set(case_ids)
        cases = [c for c in cases if c["case_id"] in wanted]
    if not cases:
        store.update_run(run_id, {"status": "failed", "completed_at": _utcnow(), "total_cases": 0})
        return {"status": "failed", "reason": "no cases"}

    store.update_run(run_id, {"total_cases": len(cases)})
    # The LLM is optional: if unavailable we still measure retrieval (Hit@5)
    # and skip answer generation + judging.
    try:
        client = create_llm_client(engine.config.llm)
    except Exception as exc:
        log.warning("Evaluation running in retrieval-only mode (LLM unavailable: %s)", exc)
        client = None
    config_snapshot = {
        "embedding_provider": engine.config.embeddings.provider,
        "embedding_model": engine.config.embeddings.model,
        "dense_weight": engine.config.retrieval.dense_weight,
        "sparse_weight": engine.config.retrieval.sparse_weight,
        "top_k": engine.config.retrieval.top_k,
        "rerank_top_k": engine.config.retrieval.rerank_top_k,
        "final_context_k": engine.config.retrieval.final_context_k,
        "reranker": engine.config.retrieval.reranker,
        "chunk_max_tokens": engine.config.chunking.max_tokens,
    }

    hit_count = 0
    faithfulness_total = 0.0
    relevancy_total = 0.0
    passed = 0

    for idx, case in enumerate(cases, start=1):
        if progress_cb:
            progress_cb(idx, len(cases))
        try:
            # Live retrieval (production path)
            session_id = f"__eval__{run_id}"
            results = engine.search_with_profile(case["question"], "default")[0]
            contexts = [
                {
                    "chunk_id": r.chunk.chunk_id,
                    "document_name": r.chunk.metadata.get("document_name", "unknown"),
                    "section": r.chunk.metadata.get("section"),
                    "text": r.chunk.text[:800],
                    "score": round(r.score, 4),
                }
                for r in results[:5]
            ]
            expected_doc = case.get("expected_document")
            expected_chunk = case.get("expected_chunk_id")
            gradeable = bool(expected_doc or expected_chunk)
            hit = any(
                _document_hit(
                    {"chunk_id": c["chunk_id"], "document_name": c["document_name"]},
                    expected_doc,
                    expected_chunk,
                )
                for c in contexts
            )
            if not gradeable:
                # No expected source given — retrieval passes if any context was
                # retrieved (answer grounding is graded by faithfulness/relevancy).
                hit = bool(contexts)

            # Answer generation (production path)
            if client is None:
                answer = ""
                judged = {"faithfulness": 0.0, "relevancy": 0.0, "reason": "LLM unavailable; retrieval-only run"}
            else:
                answer = engine.ask(
                    case["question"],
                    kb="default",
                    session_id=session_id,
                    user_id="__evaluator__",
                    system_prompt=engine.config.system_prompt,
                ).text
                judged = _judge_answer(client, case["question"], answer, contexts, case.get("expected_answer"))

            # Failure analysis
            failure_type = "none"
            reason = ""
            if not hit:
                failure_type = "retrieval"
                reason = "Expected document not retrieved in top-5."
            elif judged["faithfulness"] < 0.6:
                failure_type = "generation"
                reason = "Answer not fully supported by retrieved context."
            elif judged["relevancy"] < 0.6:
                failure_type = "generation"
                reason = "Answer does not fully address the question."

            result = {
                "case_id": case["case_id"],
                "question": case["question"],
                "expected_document": case.get("expected_document"),
                "retrieval_hit": hit,
                "retrieved_chunks": contexts,
                "generated_answer": answer,
                "faithfulness_score": judged["faithfulness"],
                "relevancy_score": judged["relevancy"],
                "failure_type": failure_type,
                "evaluation_reason": reason or judged.get("reason", ""),
            }
            store.add_result(run_id, result)

            hit_count += 1 if hit else 0
            faithfulness_total += judged["faithfulness"]
            relevancy_total += judged["relevancy"]
            if failure_type == "none":
                passed += 1
        except Exception as exc:
            log.exception("Evaluation case failed: %s", case["question"])
            store.add_result(
                run_id,
                {
                    "case_id": case["case_id"],
                    "question": case["question"],
                    "expected_document": case.get("expected_document"),
                    "retrieval_hit": False,
                    "retrieved_chunks": [],
                    "generated_answer": "",
                    "faithfulness_score": 0.0,
                    "relevancy_score": 0.0,
                    "failure_type": "error",
                    "evaluation_reason": f"Evaluation error: {exc}",
                },
            )

    n = len(cases)
    hit_rate = round(hit_count / n, 4)
    faithfulness = round(faithfulness_total / n, 4)
    relevancy = round(relevancy_total / n, 4)
    overall = round((hit_rate + faithfulness + relevancy) / 3, 4)
    store.update_run(
        run_id,
        {
            "status": "completed",
            "passed_cases": passed,
            "retrieval_hit_rate": hit_rate,
            "faithfulness_score": faithfulness,
            "relevancy_score": relevancy,
            "overall_score": overall,
            "config_snapshot": json.dumps(config_snapshot),
            "completed_at": _utcnow(),
        },
    )
    # Clean up the internal eval session turns so they don't pollute the
    # Playground session list.
    try:
        engine.store.delete_session(tenant_id, f"__eval__{run_id}")
    except Exception:
        pass
    return {
        "status": "completed",
        "total_cases": n,
        "passed_cases": passed,
        "retrieval_hit_rate": hit_rate,
        "faithfulness_score": faithfulness,
        "relevancy_score": relevancy,
        "overall_score": overall,
    }


# ── Question generation ───────────────────────────────────────────────────────

_GEN_SYSTEM = (
    "You generate evaluation questions for a RAG system over a knowledge base. "
    "Create diverse questions: factual ones, paraphrased rewordings (so semantic retrieval is tested), "
    "and a few unanswerable/negative questions about things NOT present in the source text "
    "(expected_answer = 'N/A' for those).\n"
    'Return ONLY a JSON array of objects: [{"question": "...", "expected_answer": "...", "expected_document": "<document name>"}]'
)


def generate_cases(
    engine,
    tenant_id: str,
    store: EvaluationStore,
    count: int = 20,
    max_documents: int = 10,
) -> list[dict]:
    """Auto-generate evaluation cases from the tenant's chunks using the tenant LLM.

    Falls back to a deterministic extractor when the LLM is unavailable.
    """
    chunks = engine.store.list_chunks(tenant_id, "default")
    if not chunks:
        return []

    # Sample up to `max_documents` documents, a few chunks each
    by_doc: dict[str, list] = {}
    for chunk in chunks:
        by_doc.setdefault(chunk.document_id, []).append(chunk)
    sampled: list = []
    for doc_id, doc_chunks in by_doc.items():
        step = max(1, len(doc_chunks) // 3)
        sampled.extend(doc_chunks[::step][:3])
    sampled = sampled[: max_documents * 3]

    client = create_llm_client(engine.config.llm)
    created: list[dict] = []
    per_batch = 3
    batches = [sampled[i : i + per_batch] for i in range(0, len(sampled), per_batch)]

    for batch in batches:
        block = "\n\n".join(
            f"### DOC: {c.metadata.get('document_name', 'unknown')}\n{(c.text or '')[:1200]}" for c in batch
        )
        user = (
            f"Generate {min(count - len(created), per_batch * 2)} questions from this knowledge base content. "
            f"Mix factual, paraphrased, and unanswerable questions. Keep questions self-contained.\n\n{block}"
        )
        try:
            raw = client.generate([{"role": "system", "content": _GEN_SYSTEM}, {"role": "user", "content": user}])
            data = _extract_json(raw)
            items = data if isinstance(data, list) else []
            for item in items:
                if not isinstance(item, dict) or not item.get("question"):
                    continue
                case = store.add_case(
                    tenant_id,
                    str(item["question"]).strip(),
                    expected_answer=(str(item.get("expected_answer")) if item.get("expected_answer") else None),
                    expected_document=(str(item.get("expected_document")) if item.get("expected_document") else None),
                    source="auto",
                )
                created.append(case)
                if len(created) >= count:
                    break
        except Exception as exc:
            log.warning("Question generation batch failed: %s", exc)

    # Deterministic fallback for the remainder (no LLM needed)
    if len(sampled) == 1:
        sampled = sampled * 2
    cursor = 0
    while len(created) < count and cursor < len(sampled) * 2:
        chunk = sampled[cursor % len(sampled)]
        cursor += 1
        first_line = next((ln.strip() for ln in (chunk.text or "").splitlines() if len(ln.strip()) > 20), "")
        if not first_line:
            continue
        question = first_line if first_line.endswith("?") else f"What does the document say about: {first_line[:80]}?"
        case = store.add_case(
            tenant_id,
            question,
            expected_answer=(chunk.text or "")[:300],
            expected_document=chunk.metadata.get("document_name"),
            source="auto",
        )
        created.append(case)
    return created


# ── Knowledge-base quality ────────────────────────────────────────────────────

def kb_quality(engine, tenant_id: str) -> dict:
    """Analyze the indexed KB for duplicates, boilerplate, and tiny/low-quality chunks."""
    chunks = engine.store.list_chunks(tenant_id, "default")
    documents = engine.store.list_documents(tenant_id, "default")
    total = len(chunks)
    if total == 0:
        return {
            "documents": len(documents),
            "chunks": 0,
            "duplicate_pct": 0.0,
            "boilerplate_pct": 0.0,
            "tiny_pct": 0.0,
            "quality_score": 0.0,
            "chunks_per_doc": 0.0,
        }

    normalized: dict[str, int] = {}
    boilerplate = 0
    tiny = 0
    for chunk in chunks:
        text = chunk.text or ""
        norm = re.sub(r"\s+", " ", text).strip().lower()
        normalized[norm] = normalized.get(norm, 0) + 1
        if len(text.strip()) < 25:
            tiny += 1
        lower = text.lower()
        if len(lower.split()) < 8 and not lower.strip():
            boilerplate += 1
        elif any(marker in lower for marker in ("cookie", "accept all", "privacy policy", "menu item", "button")) and len(text.split()) < 15:
            boilerplate += 1

    duplicates = sum(1 for count in normalized.values() if count > 1)
    duplicate_pct = round(duplicates / total * 100, 1)
    boilerplate_pct = round(boilerplate / total * 100, 1)
    tiny_pct = round(tiny / total * 100, 1)

    quality = 100 - duplicate_pct * 0.5 - boilerplate_pct * 0.3 - tiny_pct * 0.2
    quality = round(max(0.0, min(100.0, quality)), 1)

    return {
        "documents": len(documents),
        "chunks": total,
        "duplicate_pct": duplicate_pct,
        "boilerplate_pct": boilerplate_pct,
        "tiny_pct": tiny_pct,
        "quality_score": quality,
        "chunks_per_doc": round(total / max(1, len(documents)), 1),
    }
