"""Controlled post-remediation regression of the ten frozen Run 14 cases."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
IDENTITY = os.environ.get(
    "RUN14_REGRESSION_IDENTITY", "post_remediation_run14_regression"
)
OUT = HERE / IDENTITY
RUNTIME = HERE / f"{IDENTITY}_runtime"
SOURCE_INDEX = ROOT / "rag_store"
ORIGINAL_RUN = ROOT / "validation" / "prospective_evaluation_v5" / "run_14"
QUERY_FILE = ROOT / "validation" / "prospective_evaluation_v5" / "queries_v5.json"

if OUT.exists() or RUNTIME.exists():
    raise FileExistsError("Regression output/runtime path already exists; overwrite prohibited")

sys.path.insert(0, str(ROOT))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_manifest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(ROOT).as_posix(): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


started = datetime.now(timezone.utc).isoformat()
original_run_pre = file_manifest(ORIGINAL_RUN)
status_lines = git("status", "--porcelain=v1").splitlines()
changed_paths = [line[3:] for line in status_lines if len(line) > 3]
production_test_paths = [
    ROOT / relative
    for relative in changed_paths
    if relative.startswith(("Retrieval/", "llm/", "tests/"))
    or relative in {"project_paths.py", "immutable_index.py", "app.py"}
]
production_test_hashes = {
    path.relative_to(ROOT).as_posix(): sha256(path)
    for path in production_test_paths
    if path.is_file()
}

from immutable_index import assert_source_unchanged, create_verified_runtime_copy, tree_hash

source_tree_pre = tree_hash(SOURCE_INDEX)
runtime_copy = create_verified_runtime_copy(SOURCE_INDEX, RUNTIME)
os.environ["HYBREDE_RAG_STORE_DIR"] = str(RUNTIME)

import httpx

huggingface_network_attempts = []
original_httpx_request = httpx.Client.request


def guarded_request(client, method, url, *args, **kwargs):
    if "huggingface.co" in str(url):
        huggingface_network_attempts.append({"method": method, "url": str(url)})
        raise RuntimeError("Unexpected Hugging Face request in offline regression")
    return original_httpx_request(client, method, url, *args, **kwargs)


httpx.Client.request = guarded_request

from Retrieval.retrieval import (
    BM25_B,
    BM25_K1,
    COLLECTION_NAME,
    CROSS_ENCODER_TOP_N,
    CROSS_ENCODER_MODEL_NAME,
    DEFAULT_MIN_SCORE,
    EMBED_MODEL_NAME,
    HYBRID_CANDIDATE_POOL,
    LEXICAL_CANDIDATE_POOL,
    MMR_CANDIDATE_POOL,
    MMR_LAMBDA,
    PAPER_SUPPORT_MAX_BONUS,
    PAPER_SUPPORT_MAX_CHUNKS,
    PAPER_SUPPORT_MIN_RELATIVE_SCORE,
    get_chroma_collection,
    get_cross_encoder_model,
    get_embedding_model,
)
from llm.interface import get_llm_provider
from llm.rag_generator import evaluate_query_batch

queries_payload = json.loads(QUERY_FILE.read_text(encoding="utf-8"))
frozen_cases = queries_payload["queries"]
queries = [case["query"] for case in frozen_cases]
collection = get_chroma_collection()
embedding = get_embedding_model()
cross_encoder = get_cross_encoder_model()
llm = get_llm_provider("openai", model="gpt-4o-mini")
rows = evaluate_query_batch(
    queries,
    provider="openai",
    k=5,
    llm=llm,
    collection=collection,
    embedding_model=embedding,
)
close = getattr(getattr(llm, "client", None), "close", None)
if callable(close):
    close()

results = []
claim_audit = []
for frozen, row in zip(frozen_cases, rows):
    row["id"] = frozen["id"]
    row["case_type"] = frozen["case_type"]
    retrieval = row.get("retrieval") or {}
    metadata = (retrieval.get("metadatas") or [[]])[0]
    exposure = row.get("excerpt_exposure") or {}
    gate = row.get("evidence_sufficiency") or {}
    contract = row.get("generation_contract") or {}
    trace = row.get("structured_claim_validation") or {}
    citations = row.get("citations") or []
    sources = row.get("sources") or []
    citation_mapping = [
        {
            "citation": number,
            "paperId": sources[number - 1].get("paperId"),
            "excerpt_id": sources[number - 1].get("excerpt_id"),
        }
        for number in citations
        if 1 <= number <= len(sources)
    ]
    unsupported_statement = (
        "does not directly support" in str(row.get("answer", "")).lower()
        or "do not establish" in str(row.get("answer", "")).lower()
        or bool(row.get("insufficient_evidence"))
    )
    diagnostic = {
        "id": frozen["id"],
        "query": frozen["query"],
        "retrieved_paper_ids": [item.get("paperId") for item in metadata],
        "exposed_excerpt_ids": [
            item.get("excerpt_id") for item in exposure.get("sources", [])
        ],
        "proposition_decomposition": (
            gate.get("question_specification")
            or {"components": []}
        ).get("components", []),
        "qualifier_coverage": [
            {
                key: component.get(key)
                for key in (
                    "component_id",
                    "population",
                    "context",
                    "intervention_or_exposure",
                    "comparator",
                    "outcome",
                    "time_requirement",
                    "outcome_direction",
                    "magnitude",
                    "causal_requirement",
                    "numerical_requirement",
                )
            }
            for component in (
                gate.get("question_specification") or {"components": []}
            ).get("components", [])
        ],
        "proposition_to_excerpt_support": [
            {
                "component_id": component.get("component_id"),
                "status": component.get("status"),
                "supporting_source_ids": component.get("supporting_source_ids", []),
                "supporting_excerpt_ids": component.get("supporting_excerpt_ids", []),
                "rationale": component.get("rationale", ""),
            }
            for component in gate.get("components", [])
        ],
        "sufficiency_disposition": gate.get("decision"),
        "generation_occurred": not bool(row.get("generation_bypassed")),
        "complete_generated_answer": row.get("answer"),
        "citation_mapping": citation_mapping,
        "explicit_unsupported_proposition_statement": unsupported_statement,
        "final_observed_disposition": row.get("final_disposition"),
        "technical_failure": bool(row.get("technical_failure")),
        "error": row.get("error"),
        "raw_result": row,
    }
    results.append(diagnostic)
    for claim in trace.get("valid_claims", []):
        claim_audit.append(
            {
                "id": frozen["id"],
                "claim_id": claim.get("claim_id"),
                "statement": claim.get("claim_text"),
                "support_class": "directly_supported",
                "citation_status": "citation-valid",
                "paper_ids": claim.get("paper_ids", []),
                "excerpt_ids": claim.get("excerpt_ids", []),
                "validator_raw": claim.get("validator_raw"),
            }
        )
    for claim in trace.get("removed_claims", []):
        claim_audit.append(
            {
                "id": frozen["id"],
                "claim_id": claim.get("claim_id"),
                "statement": claim.get("claim_text"),
                "support_class": (
                    "partially_supported"
                    if claim.get("removal_reason") == "insufficiently_specific"
                    else "unsupported"
                ),
                "citation_status": (
                    "citation-invalid"
                    if "identity" in str(claim.get("removal_reason"))
                    else "not-rendered"
                ),
                "paper_ids": claim.get("paper_ids", []),
                "excerpt_ids": claim.get("excerpt_ids", []),
                "removal_reason": claim.get("removal_reason"),
                "validator_raw": claim.get("validator_raw"),
            }
        )

assert_source_unchanged(SOURCE_INDEX, source_tree_pre)
original_run_post = file_manifest(ORIGINAL_RUN)
lexical_payload = json.loads((RUNTIME / "lexical_index.json").read_text(encoding="utf-8"))
lexical_records = lexical_payload["records"]

OUT.mkdir()
(OUT / "working_tree.diff").write_text(
    git("diff", "--binary") + git("diff", "--cached", "--binary"),
    encoding="utf-8",
)
(OUT / "results.json").write_text(
    json.dumps(results, indent=2, ensure_ascii=False, default=str) + "\n",
    encoding="utf-8",
)
(OUT / "claim_level_audit.json").write_text(
    json.dumps(claim_audit, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

provenance = {
    "identity": IDENTITY,
    "scientific_status": "known-case post-remediation regression; not prospective validation",
    "started_at_utc": started,
    "finished_at_utc": datetime.now(timezone.utc).isoformat(),
    "git": {
        "branch": git("branch", "--show-current").strip(),
        "commit": git("rev-parse", "HEAD").strip(),
        "status": status_lines,
        "production_test_file_sha256": production_test_hashes,
        "working_tree_diff": "working_tree.diff",
    },
    "environment": {
        "python": platform.python_version(),
        "dependencies": {
            name: version(name)
            for name in (
                "chromadb",
                "sentence-transformers",
                "transformers",
                "torch",
                "openai",
                "numpy",
            )
        },
        "offline": {
            "HF_HUB_OFFLINE": os.environ["HF_HUB_OFFLINE"],
            "TRANSFORMERS_OFFLINE": os.environ["TRANSFORMERS_OFFLINE"],
            "huggingface_network_attempts": huggingface_network_attempts,
        },
        "models": {
            "embedding": EMBED_MODEL_NAME,
            "embedding_type": type(embedding).__name__,
            "cross_encoder": CROSS_ENCODER_MODEL_NAME,
            "cross_encoder_type": type(cross_encoder).__name__,
            "generation": "gpt-4o-mini",
        },
    },
    "retrieval_identity": {
        "collection": COLLECTION_NAME,
        "source_index_tree_sha256_pre": source_tree_pre,
        "source_index_tree_sha256_post": tree_hash(SOURCE_INDEX),
        "runtime_copy": runtime_copy,
        "chroma_segment_count": collection.count(),
        "bm25_segment_count": len(lexical_records),
        "bm25_sha256": sha256(RUNTIME / "lexical_index.json"),
        "corpus_sha256": {
            path.relative_to(ROOT).as_posix(): sha256(path)
            for path in (
                ROOT / "data" / "processed" / "filtered_papers.json",
                ROOT / "data" / "processed" / "corpus_source_manifest_v3.json",
            )
        },
        "settings": {
            "default_min_score": DEFAULT_MIN_SCORE,
            "hybrid_candidate_pool": HYBRID_CANDIDATE_POOL,
            "lexical_candidate_pool": LEXICAL_CANDIDATE_POOL,
            "cross_encoder_top_n": CROSS_ENCODER_TOP_N,
            "mmr_candidate_pool": MMR_CANDIDATE_POOL,
            "mmr_lambda": MMR_LAMBDA,
            "bm25_k1": BM25_K1,
            "bm25_b": BM25_B,
            "paper_support_max_chunks": PAPER_SUPPORT_MAX_CHUNKS,
            "paper_support_min_relative_score": PAPER_SUPPORT_MIN_RELATIVE_SCORE,
            "paper_support_max_bonus": PAPER_SUPPORT_MAX_BONUS,
        },
    },
    "original_run14": {
        "path": ORIGINAL_RUN.relative_to(ROOT).as_posix(),
        "pre_sha256": original_run_pre,
        "post_sha256": original_run_post,
        "unchanged": original_run_pre == original_run_post,
    },
}
(OUT / "provenance.json").write_text(
    json.dumps(provenance, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
print(json.dumps({
    "output": str(OUT),
    "cases": len(results),
    "technical_failures": sum(item["technical_failure"] for item in results),
    "dispositions": {
        item["id"]: item["final_observed_disposition"] for item in results
    },
    "claims": len(claim_audit),
    "original_run14_unchanged": original_run_pre == original_run_post,
}, ensure_ascii=False))
