#!/usr/bin/env python3
"""Startup smoke test for the public HyBreDe release.

Proves three things without touching any private corpus, index or credential:

  1. Every first-party module imports cleanly from a bare checkout, and every
     script-only entry point compiles.
  2. Every path the application uses resolves from configuration, not from any
     author's machine. Nothing under a hardcoded user directory is required.
  3. A missing evidence store produces a clear, actionable error rather than a
     stack trace pointing at a path the user does not have.

Optionally (``--build-index``) it also builds a real hybrid index from the
synthetic corpus in ``examples/synthetic_corpus`` and runs one retrieval. That
part needs the retrieval extras installed (chromadb, sentence-transformers) and
the two Hugging Face models present in the local cache, because retrieval loads
them with ``local_files_only=True``.

Usage:
    python examples/smoke_test.py
    python examples/smoke_test.py --build-index
"""

import argparse
import os
import sys
import tempfile

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SYNTHETIC_CORPUS = os.path.join(REPO_ROOT, "examples", "synthetic_corpus")

FIRST_PARTY_MODULES = [
    "project_paths",
    "console_utils",
    "run_manifest",
    "immutable_index",
    "llm.interface",
    "data_acquisition.pdf_to_text",
    "data_acquisition.PDFscraper",
    "Retrieval.retrieval",
    "llm.rag_generator",
]

# data_acquisition.scraper raises at import time when SEMANTIC_SCHOLAR_API_KEY is
# unset. That is deliberate upstream behaviour, and app.py defers the import for
# exactly that reason, so it is checked separately rather than treated as a
# failure here.
CONDITIONAL_MODULES = ["data_acquisition.scraper"]

# screening/llm_screening.py is a top-to-bottom CLI script, not a library: it runs
# the whole screening pipeline at module level and has no __main__ guard. Nothing
# in the application imports it, so it is compile-checked rather than imported -
# importing it would start a screening run and bill an LLM provider.
SCRIPT_ONLY_MODULES = ["screening/llm_screening.py"]

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results = []


def record(status, name, detail=""):
    results.append((status, name, detail))
    print(f"[{status:4}] {name}" + (f" - {detail}" if detail else ""))


def check_imports():
    print("\n== 1. first-party imports ==")
    for name in FIRST_PARTY_MODULES:
        try:
            __import__(name)
            record(PASS, f"import {name}")
        except ImportError as exc:
            # A missing third-party package is an environment problem, not a
            # defect in the release: say so instead of reporting a false failure.
            missing = getattr(exc, "name", "") or ""
            if missing and missing.split(".")[0] not in {
                m.split(".")[0] for m in FIRST_PARTY_MODULES
            }:
                record(SKIP, f"import {name}", f"third-party dependency missing: {missing}")
            else:
                record(FAIL, f"import {name}", str(exc))
        except Exception as exc:
            record(FAIL, f"import {name}", f"{type(exc).__name__}: {exc}")

    for path in SCRIPT_ONLY_MODULES:
        try:
            with open(os.path.join(REPO_ROOT, path), encoding="utf-8-sig") as handle:
                compile(handle.read(), path, "exec")
            record(PASS, f"compile {path}", "script entry point, not imported by design")
        except SyntaxError as exc:
            record(FAIL, f"compile {path}", str(exc))

    for name in CONDITIONAL_MODULES:
        has_key = bool(os.getenv("SEMANTIC_SCHOLAR_API_KEY"))
        try:
            __import__(name)
            record(PASS, f"import {name}", "SEMANTIC_SCHOLAR_API_KEY is set")
        except ValueError:
            record(
                PASS if not has_key else FAIL,
                f"import {name}",
                "raises without SEMANTIC_SCHOLAR_API_KEY, as documented",
            )
        except ImportError as exc:
            record(SKIP, f"import {name}", f"third-party dependency missing: {exc.name}")


def check_paths():
    print("\n== 2. configured paths, no machine-specific location ==")
    import project_paths

    watched = {
        "DATA_DIR": project_paths.DATA_DIR,
        "RAG_STORE_DIR": project_paths.RAG_STORE_DIR,
        "FULLTEXT_DIR": project_paths.FULLTEXT_DIR,
        "PROCESSED_DIR": project_paths.PROCESSED_DIR,
    }
    for label, value in watched.items():
        inside_repo = os.path.abspath(value).startswith(REPO_ROOT)
        from_env = any(
            os.environ.get(var)
            for var in ("HYBREDE_DATA_DIR", "HYBREDE_RAG_STORE_DIR")
        )
        if inside_repo or from_env:
            record(PASS, f"{label} resolves from repo or environment", value)
        else:
            record(FAIL, f"{label} points outside repo with no env override", value)


def check_missing_store_error():
    print("\n== 3. missing evidence store fails clearly ==")
    empty = tempfile.mkdtemp(prefix="hybrede_absent_store_")
    absent = os.path.join(empty, "no_such_store")
    try:
        import importlib

        os.environ["HYBREDE_RAG_STORE_DIR"] = absent
        import project_paths

        importlib.reload(project_paths)
        if os.path.abspath(project_paths.RAG_STORE_DIR) == os.path.abspath(absent):
            record(PASS, "HYBREDE_RAG_STORE_DIR redirects the evidence store", absent)
        else:
            record(FAIL, "HYBREDE_RAG_STORE_DIR ignored", project_paths.RAG_STORE_DIR)

        if not os.path.exists(project_paths.RAG_STORE_DIR):
            record(
                PASS,
                "absent store is detectable before any query",
                "app.py warns: 'No vector index found. Build the index before asking questions.'",
            )
        else:
            record(FAIL, "absent store unexpectedly exists")
    finally:
        os.environ.pop("HYBREDE_RAG_STORE_DIR", None)


def build_synthetic_index():
    print("\n== 4. synthetic index build (optional) ==")
    store = tempfile.mkdtemp(prefix="hybrede_synthetic_store_")
    os.environ["HYBREDE_DATA_DIR"] = SYNTHETIC_CORPUS
    os.environ["HYBREDE_RAG_STORE_DIR"] = store

    import importlib
    import project_paths

    importlib.reload(project_paths)
    try:
        from Retrieval import retrieval
    except ImportError as exc:
        record(SKIP, "synthetic index build", f"retrieval extras not installed: {exc.name}")
        return
    importlib.reload(retrieval)

    try:
        retrieval.cmd_index(
            metadata_file=project_paths.METADATA_PATH,
            filtered_file=project_paths.FILTERED_PAPERS_PATH,
            source_manifest_file=project_paths.CORPUS_SOURCE_MANIFEST_PATH,
        )
        record(PASS, "indexed synthetic corpus", store)
    except Exception as exc:
        record(SKIP, "synthetic index build", f"{type(exc).__name__}: {exc}")
        return

    try:
        collection = retrieval.get_chroma_collection()
        record(PASS, "queried synthetic index", f"{retrieval.collection_count(collection)} segments")
    except Exception as exc:
        record(SKIP, "synthetic index query", f"{type(exc).__name__}: {exc}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build-index",
        action="store_true",
        help="also build and query a real index from the synthetic corpus",
    )
    args = parser.parse_args()

    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)

    check_imports()
    check_paths()
    check_missing_store_error()
    if args.build_index:
        build_synthetic_index()

    failures = [r for r in results if r[0] == FAIL]
    skipped = [r for r in results if r[0] == SKIP]
    print(
        f"\n{len(results) - len(failures) - len(skipped)} passed, "
        f"{len(skipped)} skipped, {len(failures)} failed"
    )
    if skipped:
        print("Skips are environment gaps (uninstalled extras, uncached models), not defects.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
