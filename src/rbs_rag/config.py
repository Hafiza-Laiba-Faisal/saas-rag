from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .llm import LLMSettings

CONFIG_DIR = ".rbs_rag"
CONFIG_FILE = "config.json"


@dataclass(slots=True)
class StorageConfig:
    provider: str = "sqlite"
    path: str = ".rbs_rag/rag.db"


@dataclass(slots=True)
class EmbeddingConfig:
    provider: str = "hash"
    dimensions: int = 384
    model: str = "BAAI/bge-small-en-v1.5"
    base_url: str | None = None
    api_key: str | None = None
    tier: str = "hash"   # hash | fastembed | bge_m3 | openai | gemini


@dataclass(slots=True)
class RetrievalConfig:
    top_k: int = 20
    rerank_top_k: int = 8
    final_context_k: int = 5
    dense_weight: float = 0.55
    sparse_weight: float = 0.45
    reranker: str = "bge_cross_encoder"   # local | bge_cross_encoder


@dataclass(slots=True)
class ChunkingConfig:
    max_tokens: int = 320
    overlap_tokens: int = 48
    semantic_chunking: bool = True
    semantic_similarity_threshold: float = 0.75


@dataclass(slots=True)
class QdrantConfig:
    host: str = "localhost"
    port: int = 6333
    grpc_port: int = 6334
    prefer_grpc: bool = False
    api_key: str = ""
    https: bool = False
    collection_config: dict = field(default_factory=lambda: {
        "vectors": {"size": 384, "distance": "Cosine"},
        "optimizers_config": {"default_segment_number": 2},
        "replication_factor": 1,
    })


@dataclass(slots=True)
class RateLimitConfig:
    enabled: bool = True
    requests_per_minute: int = 60
    burst_size: int = 10


@dataclass(slots=True)
class SecurityConfig:
    encrypt_keys: bool = False
    admin_auth_enabled: bool = False
    admin_jwt_secret: str = ""
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    prompt_injection_detection: bool = False
    terminal_enabled: bool = True


@dataclass(slots=True)
class ObservabilityConfig:
    health_endpoint: bool = True
    metrics_enabled: bool = False
    structured_logging: bool = True
    log_level: str = "INFO"
    log_file: str = ""


@dataclass(slots=True)
class AppConfig:
    tenant_id: str = "local"
    default_kb: str = "default"
    session_memory_limit: int = 8
    chat_retention_days: int = 30
    system_prompt: str | None = None
    storage: StorageConfig = field(default_factory=StorageConfig)
    embeddings: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    llm: LLMSettings = field(default_factory=LLMSettings)
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)

    def to_safe_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data["llm"].get("api_key"):
            data["llm"]["api_key"] = "***"
        return data


def create_default_config(root: Path, force: bool = False) -> Path:
    config_dir = root / CONFIG_DIR
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / CONFIG_FILE
    if config_path.exists() and not force:
        return config_path
    config = AppConfig(
        llm=LLMSettings(
            provider="gemini",
            api_key="${RAG_LLM_API_KEY}",
            model="gemini-2.5-flash-lite",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            fallback_models=["gemini-2.5-flash"],
        )
    )
    config_path.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
    return config_path


def load_config(root: Path, config_path: Path | None = None) -> AppConfig:
    path = config_path or root / CONFIG_DIR / CONFIG_FILE
    if not path.exists():
        raise FileNotFoundError(f"Config not found at {path}. Run 'rag init' first.")
    raw = json.loads(path.read_text(encoding="utf-8"))
    env = _load_local_env(root) | dict(os.environ)
    expanded = _expand_env(raw, env)
    return AppConfig(
        tenant_id=expanded.get("tenant_id", "local"),
        default_kb=expanded.get("default_kb", "default"),
        session_memory_limit=expanded.get("session_memory_limit", 8),
        chat_retention_days=expanded.get("chat_retention_days", 30),
        storage=StorageConfig(**expanded.get("storage", {})),
        embeddings=EmbeddingConfig(**expanded.get("embeddings", {})),
        retrieval=RetrievalConfig(**expanded.get("retrieval", {})),
        chunking=ChunkingConfig(**expanded.get("chunking", {})),
        llm=LLMSettings(**expanded.get("llm", {})),
        qdrant=QdrantConfig(**expanded.get("qdrant", {})),
        rate_limit=RateLimitConfig(**expanded.get("rate_limit", {})),
        security=SecurityConfig(**expanded.get("security", {})),
        observability=ObservabilityConfig(**expanded.get("observability", {})),
    )


def resolve_storage_path(root: Path, config: AppConfig) -> Path:
    path = Path(config.storage.path)
    if not path.is_absolute():
        path = root / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _expand_env(value: Any, env: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _expand_env(item, env) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item, env) for item in value]
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return env.get(value[2:-1], "")
    return value


def _load_local_env(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for name in [".env", ".env.local"]:
        path = root / name
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = _strip_env_quotes(value.strip())
    return values


def _strip_env_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value