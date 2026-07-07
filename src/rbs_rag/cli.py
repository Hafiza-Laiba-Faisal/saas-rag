from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import create_default_config, load_config
from .engine import RagEngine


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    root = Path(args.root).resolve()

    try:
        if args.command == "init":
            path = create_default_config(root, force=args.force)
            print(f"Created config at {path}")
            return 0

        config = load_config(root, Path(args.config).resolve() if args.config else None)
        engine = RagEngine(config, root)

        if args.command == "config":
            if args.config_command == "show":
                print(json.dumps(config.to_safe_dict(), indent=2))
                return 0
        if args.command == "ingest":
            summary = engine.ingest_path(Path(args.path), kb=args.kb, metadata=_parse_key_values(args.metadata))
            print(f"Indexed {summary.documents} documents and {summary.chunks} chunks into KB '{args.kb or config.default_kb}'.")
            if summary.skipped:
                print(f"Skipped {summary.skipped} files.")
            for error in summary.errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1 if summary.documents == 0 and summary.errors else 0
        if args.command == "search":
            results = engine.search(args.query, kb=args.kb, filters=_parse_key_values(args.filter))
            _print_results(results)
            return 0
        if args.command == "ask":
            answer = engine.ask(
                args.query,
                kb=args.kb,
                session_id=args.session,
                user_id=args.user,
                filters=_parse_key_values(args.filter),
            )
            _safe_print(answer.text)
            _safe_print("\nCitations:")
            for citation in answer.citations:
                section = f" / {citation.section}" if citation.section else ""
                _safe_print(f"[{citation.index}] {citation.document_name}{section}")
            _safe_print(f"\nValidation: {answer.validation.confidence}")
            return 0
        if args.command == "chat":
            return _chat(engine, args.kb, args.session, args.user)
        if args.command == "sessions":
            if args.sessions_command == "list":
                sessions = engine.list_sessions()
                if not sessions:
                    print("No sessions found.")
                for session in sessions:
                    print(f"{session['session_id']} user={session['user_id']} turns={session['turns']} last={session['last_turn_at']}")
                return 0
        if args.command == "memory":
            if args.memory_command == "set":
                engine.set_user_memory(args.user, args.key, args.value)
                print(f"Saved memory for user '{args.user}': {args.key}")
                return 0
            if args.memory_command == "list":
                memory = engine.get_user_memory(args.user)
                if not memory:
                    print("No user memory found.")
                for key, value in memory.items():
                    _safe_print(f"{key}: {value}")
                return 0
        if args.command == "documents":
            if args.documents_command == "list":
                documents = engine.list_documents(args.kb)
                if not documents:
                    print("No documents found.")
                for document in documents:
                    print(f"{document['name']} ({document['document_type']}) {document['path']}")
                return 0
    except Exception as exc:  # noqa: BLE001 - CLI converts failures to a concise user-visible error.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rag", description="CLI-first reusable RAG foundation.")
    parser.add_argument("--root", default=".", help="Project root containing .rbs_rag/config.json")
    parser.add_argument("--config", default=None, help="Explicit config JSON path")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Create local RAG config and storage folders.")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing config.")

    config_parser = subparsers.add_parser("config", help="Inspect configuration.")
    config_sub = config_parser.add_subparsers(dest="config_command")
    config_sub.add_parser("show", help="Show effective config with secrets redacted.")

    ingest_parser = subparsers.add_parser("ingest", help="Index a file or folder.")
    ingest_parser.add_argument("path")
    ingest_parser.add_argument("--kb", default=None)
    ingest_parser.add_argument("--metadata", action="append", default=[], help="Metadata key=value. Repeatable.")

    search_parser = subparsers.add_parser("search", help="Search indexed chunks without calling the LLM.")
    search_parser.add_argument("query")
    search_parser.add_argument("--kb", default=None)
    search_parser.add_argument("--filter", action="append", default=[], help="Metadata filter key=value. Repeatable.")

    ask_parser = subparsers.add_parser("ask", help="Ask a question using retrieved context and configured LLM API.")
    ask_parser.add_argument("query")
    ask_parser.add_argument("--kb", default=None)
    ask_parser.add_argument("--session", default="default")
    ask_parser.add_argument("--user", default="local-user")
    ask_parser.add_argument("--filter", action="append", default=[], help="Metadata filter key=value. Repeatable.")

    chat_parser = subparsers.add_parser("chat", help="Interactive chat with session memory.")
    chat_parser.add_argument("--kb", default=None)
    chat_parser.add_argument("--session", default="default")
    chat_parser.add_argument("--user", default="local-user")

    sessions_parser = subparsers.add_parser("sessions", help="Manage chat sessions.")
    sessions_sub = sessions_parser.add_subparsers(dest="sessions_command")
    sessions_sub.add_parser("list", help="List sessions.")

    memory_parser = subparsers.add_parser("memory", help="Manage user memory.")
    memory_sub = memory_parser.add_subparsers(dest="memory_command")
    memory_set = memory_sub.add_parser("set", help="Save user memory key/value.")
    memory_set.add_argument("key")
    memory_set.add_argument("value")
    memory_set.add_argument("--user", default="local-user")
    memory_list = memory_sub.add_parser("list", help="List user memory.")
    memory_list.add_argument("--user", default="local-user")

    documents_parser = subparsers.add_parser("documents", help="Inspect indexed documents.")
    documents_sub = documents_parser.add_subparsers(dest="documents_command")
    documents_list = documents_sub.add_parser("list", help="List documents.")
    documents_list.add_argument("--kb", default=None)

    return parser


def _parse_key_values(items: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"Expected key=value, got '{item}'")
        key, value = item.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def _print_results(results) -> None:
    if not results:
        print("No results.")
        return
    for index, result in enumerate(results, start=1):
        metadata = result.chunk.metadata
        section = f" / {metadata.get('section')}" if metadata.get("section") else ""
        _safe_print(f"[{index}] score={result.score:.3f} source={metadata.get('document_name', 'unknown')}{section}")
        _safe_print(result.chunk.text[:800])
        _safe_print("")


def _chat(engine: RagEngine, kb: str | None, session_id: str, user_id: str) -> int:
    print("RAG chat. Type 'exit' or 'quit' to leave.")
    while True:
        try:
            query = input("> ").strip()
        except EOFError:
            print()
            return 0
        if query.lower() in {"exit", "quit"}:
            return 0
        if not query:
            continue
        answer = engine.ask(query, kb=kb, session_id=session_id, user_id=user_id)
        _safe_print(answer.text)


def _safe_print(value: object = "", stream=None) -> None:
    stream = stream or sys.stdout
    text = str(value)
    print(_clean_text_for_encoding(text, getattr(stream, "encoding", None)), file=stream)


def _clean_text_for_encoding(text: str, encoding: str | None) -> str:
    if not encoding:
        return text
    try:
        text.encode(encoding)
        return text
    except UnicodeEncodeError:
        return text.encode(encoding, errors="replace").decode(encoding)
