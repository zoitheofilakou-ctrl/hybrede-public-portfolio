# Reproducibility

## What this repository can and cannot do

**Can:** be read and reviewed; run the **entire pipeline** — acquisition, screening,
extraction, indexing, hybrid retrieval, reranking, diversification, generation and
claim verification — against your own corpus with your own API keys; reuse the
immutability utilities directly; study the evaluation and governance methodology.

**Cannot:** reproduce the original published retrieval results. That needs the frozen
corpus and index, which are copyrighted and not redistributable. The code is no longer
the limitation; the data is.

This is stated up front so nobody wastes time trying.

## Recorded environment of the publication-facing evaluation

| Component | Version / identity |
|---|---|
| Python | 3.11.5 |
| Embedding model | `all-MiniLM-L6-v2` |
| Cross-encoder reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| Generation model | `gpt-4o-mini` |
| ChromaDB | 1.5.1 |
| Sentence Transformers | 5.2.3 |
| Frozen retrieval identity | 715 Chroma segments, 715 BM25 records |

The recorded execution environment, rather than any repository setup file, is
authoritative for reporting the historical run.

## Running the included stages

```bash
git clone <this-repo>
cd HyBreDe_Public_Portfolio

python -m venv .venv
# Windows:  .venv\Scripts\activate
# POSIX:    source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env      # then edit .env and add your own keys
```

Required credentials — **use your own**, none are supplied:

- `SEMANTIC_SCHOLAR_API_KEY` — from Semantic Scholar
- `OPENAI_API_KEY` — from OpenAI

Optional overrides: `HYBREDE_DATA_DIR` (default `data`), `HYBREDE_METADATA_PATH`,
`HYBREDE_SCREENING_MODEL` (default `gpt-4o-mini`).

Run from the repository root so `src` resolves as a package:

```bash
# Stage 1 - metadata acquisition (bibliographic metadata only)
python -m src.acquisition.scraper

# Stage 2 - LLM screening with independent verification
python -m src.screening.llm_screening
```

Outputs are written under `HYBREDE_DATA_DIR/processed/`:
`metadata.json`, `filtered_papers.json`, `screening_log.json`, `audit_log.json`.
All of these are gitignored.

Screening is resumable: already-screened `paperId`s are skipped, so an interrupted run
can be restarted without rescreening or double-counting.

### Cost and rate limits

Screening makes **two** model calls per paper (screening + verification). Budget
accordingly before running it over a large metadata set. Acquisition sleeps 1.1 s
between API requests to respect the Semantic Scholar rate limit.

## Using the immutability utilities standalone

`immutable_index.py` has no third-party dependencies and is usable on any
directory tree you want to protect during an experiment:

```python
from pathlib import Path
from src.indexing.immutable_index import (
    tree_hash, create_verified_runtime_copy, assert_source_unchanged,
)

canonical = Path("index/canonical")
before = tree_hash(canonical)

report = create_verified_runtime_copy(canonical, Path("index/runtime_run_01"))
# ... run your experiment against index/runtime_run_01 ...

assert_source_unchanged(canonical, before)   # raises if the canonical tree changed
```

`create_verified_runtime_copy` refuses to overwrite an existing runtime directory,
refuses a runtime path equal to the source, and raises if the copy is not
byte-identical.

## Rebuilding a comparable corpus

1. Run stage 1 with your own topical queries.
2. Run stage 2 to filter against the inclusion/exclusion criteria in
   `screening/llm_screening.py`.
3. Obtain full text through channels you are entitled to use (institutional access,
   PubMed Central, Europe PMC, author copies).
4. Index with your own retrieval stack — the design is described in
   [architecture.md](architecture.md).

Your corpus will differ from the original, so results will differ. That is expected and
should be reported as such.

## Provenance of the original frozen states

| State | Commit |
|---|---|
| Publication freeze | `1a49d73fd000e1b956ba69bfe2d99f208fac2caa` |
| Presentation demo freeze | `ed3692054b327313d7a8092513c49672c7c70d98` |

These repositories are retained privately, unmodified. This public repository has a
fresh, unrelated git history: sanitizing the frozen repositories by rewriting history
would have changed those commit SHAs, and the manuscript and conference materials cite
them. The frozen identities were preserved in preference to a shared history.
