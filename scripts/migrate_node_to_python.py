"""One-time migration: Node.js dev.db -> hotel-only Python SQLite architecture.

Reads ONLY from ``rbs-rag-node/prisma/dev.db`` (source of truth, never mutated)
and writes a fresh ``.rbs_rag/admin.db`` plus the per-tenant
``.rbs_rag/tenants/Grand-Hotel-delaville/rag.db``.

Migrated data:
  - 1 tenant  (Grand-Hotel-delaville: config + system_prompt + api_key)
  - 16 hotel / Parma concierge documents with their ~354 embedded chunks
    (embeddings copied verbatim, no re-embedding)
  - 54 session_turns
  - 5 activity_logs (scrape operations for the concierge site research)

Timestamps are converted from epoch-milliseconds to ISO-8601 UTC.
The ``llm_api_key`` / ``embedding_api_key`` are Fernet-encrypted at rest via
the existing RAG_ENCRYPTION_KEY (admin_db.upsert_tenant handles that).
"""
from __future__ import annotations

import sqlite3
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rbs_rag.web.admin_db import AdminStore  # noqa: E402
from rbs_rag.provisioning import provision_tenant  # noqa: E402
from rbs_rag.store import SQLiteRagStore, close_pool  # noqa: E402

NODE_DB = ROOT / "rbs-rag-node" / "prisma" / "dev.db"
ADMIN_DB = ROOT / ".rbs_rag" / "admin.db"
TENANT_DB = ROOT / ".rbs_rag" / "tenants" / "Grand-Hotel-delaville" / "rag.db"

TARGET_TENANT_ID = "Grand-Hotel-delaville"

# 16 hotel / Parma concierge documents selected from the Node dev.db
# (karan 3, test3 1, test2 1, test 22 2, rag-testing-v2 9 = 354 chunks).
DOCUMENT_IDS = [
    "6603ff412b83e4acabac7ed4028a4635c1f0626d",  # karan  grandhoteldelaville home
    "cf01d82944b26436914e62ff7978905a8722fdba",  # karan  palazzodallarosaprati
    "d70e735851244e4b37e1677e8522eb560ee9ef1d",  # karan  palazzogaribaldiparma
    "b010f32c84445c8649d00710834276157b59f071",  # test3  grandhoteldelaville homepage
    "ab624c6ea3b34b53d231b7a9cffad0ca7be48161",  # test2  google hotels
    "b49d0147db63b58be484f9951706af0bab2fb0e0",  # test22 dichiarazione accessibilità
    "6a15b84f6b7d40e919ff48002cc5edc90f993444",  # test22 palazzogaribaldi scrape
    "170f6f436e0739e4b2e2487f5af4dd531b30d5f4",  # rag-testing-v2 crawl
    "03c9f7f923c9a78a66049e7b0f64bda38be361da",  # rag-testing-v2 crawl
    "f4be0e79a40bebf4870d93882653cdf419c706a1",  # rag-testing-v2 crawl
    "c9f2f40f13f203839889ed3361392a96b7a7bab6",  # rag-testing-v2 crawl
    "bbd788e0c993b326201cc2349a48d9dbf366529f",  # rag-testing-v2 crawl
    "f171c9297f5250cd01be50cb91b18261c2d4f656",  # rag-testing-v2 crawl
    "3c48e96ece66a1d137e9643fbe6dc79b738f2983",  # rag-testing-v2 crawl
    "60e288cb30bb8e0b0bf739ba65b9096567c64980",  # rag-testing-v2 crawl
    "162b98414389d7eb34d064dcd56ca9831c648e5d",  # rag-testing-v2 crawl
]


def epoch_ms_to_iso(ms: int | None) -> str:
    if ms is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def open_node() -> sqlite3.Connection:
    if not NODE_DB.exists():
        raise SystemExit(f"Source Node dev.db not found: {NODE_DB}")
    conn = sqlite3.connect(NODE_DB)
    conn.row_factory = sqlite3.Row
    return conn


def build_admin(node: sqlite3.Connection) -> dict:
    tenant = node.execute(
        "SELECT * FROM tenants WHERE tenant_id = ?", (TARGET_TENANT_ID,)
    ).fetchone()
    if tenant is None:
        raise SystemExit(f"Tenant {TARGET_TENANT_ID!r} not found in Node dev.db")

    data = dict(tenant)
    data.pop("created_at", None)
    data.pop("updated_at", None)
    # slug is ASCII-safe and matches tenant_id; db_path is ROOT_DIR-relative
    # (resolved against .rbs_rag/ at runtime by server._tenant_db_path).
    data["slug"] = TARGET_TENANT_ID
    data["db_path"] = str(TENANT_DB.relative_to(ADMIN_DB.parent))
    return data


def migrate_admin(data: dict) -> None:
    if ADMIN_DB.exists():
        ADMIN_DB.unlink()
        for suffix in ("-wal", "-shm"):
            p = Path(str(ADMIN_DB) + suffix)
            if p.exists():
                p.unlink()
    admin = AdminStore(ADMIN_DB)
    provision_tenant(admin, data, ROOT)


def migrate_tenant(node: sqlite3.Connection) -> None:
    if TENANT_DB.exists():
        TENANT_DB.unlink()
        for suffix in ("-wal", "-shm"):
            p = Path(str(TENANT_DB) + suffix)
            if p.exists():
                p.unlink()
    TENANT_DB.parent.mkdir(parents=True, exist_ok=True)
    SQLiteRagStore(TENANT_DB)  # initializes the schema
    close_pool()

    conn = sqlite3.connect(TENANT_DB)
    conn.execute("PRAGMA foreign_keys=ON")

    placeholders = ",".join("?" for _ in DOCUMENT_IDS)
    docs = node.execute(
        f"SELECT * FROM documents WHERE document_id IN ({placeholders})",
        DOCUMENT_IDS,
    ).fetchall()
    if len(docs) != len(DOCUMENT_IDS):
        raise SystemExit(f"Expected {len(DOCUMENT_IDS)} docs, found {len(docs)}")

    for d in docs:
        conn.execute(
            """INSERT OR REPLACE INTO documents
               (document_id, tenant_id, knowledge_base_id, path, name, document_type,
                text, metadata_json, ocr_applied, ocr_engine, page_count,
                source, source_url, ingested_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                d["document_id"], TARGET_TENANT_ID, d["knowledge_base_id"],
                d["path"], d["name"], d["document_type"],
                d["text"], d["metadata_json"],
                1 if d["ocr_applied"] else 0, d["ocr_engine"], d["page_count"],
                d["source"], d["source_url"], epoch_ms_to_iso(d["ingested_at"]),
            ),
        )
        chunks = node.execute(
            "SELECT * FROM chunks WHERE document_id = ? ORDER BY ordinal",
            (d["document_id"],),
        ).fetchall()
        for c in chunks:
            conn.execute(
                """INSERT OR REPLACE INTO chunks
                   (chunk_id, document_id, tenant_id, knowledge_base_id, ordinal,
                    text, metadata_json, embedding_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    c["chunk_id"], c["document_id"], TARGET_TENANT_ID,
                    c["knowledge_base_id"], c["ordinal"],
                    c["text"], c["metadata_json"], c["embedding_json"],
                ),
            )

    turns = node.execute(
        "SELECT * FROM session_turns WHERE tenant_id = ? ORDER BY id",
        (TARGET_TENANT_ID,),
    ).fetchall()
    for t in turns:
        conn.execute(
            """INSERT INTO session_turns (tenant_id, session_id, user_id, role, content, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (TARGET_TENANT_ID, t["session_id"], t["user_id"], t["role"],
             t["content"], epoch_ms_to_iso(t["created_at"])),
        )

    conn.commit()
    conn.close()
    close_pool()


def migrate_activity_logs(node: sqlite3.Connection) -> None:
    rows = node.execute(
        "SELECT * FROM activity_logs WHERE tenant_id = ? ORDER BY id",
        (TARGET_TENANT_ID,),
    ).fetchall()
    with sqlite3.connect(ADMIN_DB) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        for r in rows:
            conn.execute(
                """INSERT INTO activity_logs
                   (tenant_id, level, operation, message, details_json, traceback, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    TARGET_TENANT_ID,
                    (r["level"] or "INFO").upper(),
                    r["operation"],
                    r["message"],
                    r["details"],
                    r["traceback"],
                    epoch_ms_to_iso(r["created_at"]),
                ),
            )
        conn.commit()


def verify() -> None:
    conn = sqlite3.connect(ADMIN_DB)
    conn.row_factory = sqlite3.Row
    n_tenants = conn.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]
    n_logs = conn.execute(
        "SELECT COUNT(*) FROM activity_logs WHERE tenant_id = ?", (TARGET_TENANT_ID,)
    ).fetchone()[0]
    conn.close()

    conn = sqlite3.connect(TENANT_DB)
    n_docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    n_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    n_turns = conn.execute("SELECT COUNT(*) FROM session_turns").fetchone()[0]
    n_user_memory = conn.execute("SELECT COUNT(*) FROM user_memory").fetchone()[0]
    conn.close()

    print("=== MIGRATION RESULT ===")
    print(f"tenants        : {n_tenants}")
    print(f"activity_logs  : {n_logs}")
    print(f"documents      : {n_docs}")
    print(f"chunks         : {n_chunks}")
    print(f"session_turns  : {n_turns}")
    print(f"user_memory    : {n_user_memory}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    if args.verify_only:
        verify()
        return 0

    node = open_node()
    tenant_data = build_admin(node)
    migrate_admin(tenant_data)
    migrate_tenant(node)
    migrate_activity_logs(node)
    node.close()
    verify()
    print("\nMigration complete. Source Node dev.db untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
