"""Tenant provisioning + per-tenant migration runner.

Targets 100+ tenants: onboarding happens programmatically (never by hand),
and schema migrations are applied to every tenant file via the migration runner.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .store import SQLiteRagStore

if TYPE_CHECKING:
    from .web.admin_db import AdminStore

log = logging.getLogger(__name__)


def provision_tenant(admin_store: "AdminStore", data: dict, root_dir: Path) -> str:
    """Register a new tenant in admin.db and initialize its isolated rag.db.

    ``data`` must contain the full tenant config (see AdminStore.upsert_tenant).
    ``db_path`` is derived from the tenant slug unless provided in ``data``.
    Returns the tenant_id.
    """
    tenant_id = data["tenant_id"]
    slug = data.get("slug", tenant_id)
    db_path = data.get("db_path") or str(Path(root_dir) / "tenants" / slug / "rag.db")

    store = SQLiteRagStore(Path(db_path))
    del store  # schema is initialized on construction

    data["slug"] = slug
    data["db_path"] = db_path
    admin_store.upsert_tenant(data)
    log.info("Provisioned tenant %s -> %s", tenant_id, db_path)
    return tenant_id


def run_tenant_migrations(admin_store: "AdminStore", root_dir: Path) -> list[str]:
    """Apply the per-tenant schema idempotently to every tenant's rag.db.

    Safe to re-run any number of times. Returns the list of tenant_ids migrated.
    """
    applied: list[str] = []
    for tenant in admin_store.list_tenants():
        tenant_id = tenant["tenant_id"]
        db_path = tenant.get("db_path") or str(Path(root_dir) / "tenants" / tenant_id / "rag.db")
        SQLiteRagStore(Path(db_path))  # idempotent schema init + migration guards
        applied.append(tenant_id)
    log.info("Migration runner applied schema to %d tenant(s)", len(applied))
    return applied
