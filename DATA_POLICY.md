# Data policy

## No literature is included in this repository

This repository contains **no scientific literature of any kind**. Specifically it
excludes:

- publisher PDFs of journal articles
- extracted full text of journal articles
- PubMed Central full-text XML
- corpus excerpts, passages or quoted article content
- vector stores, BM25 indexes or any artifact derived from article text
- the frozen research evidence store (Chroma persistence, HNSW binaries,
  `lexical_index.json`) and the private demo runtime it was served from
- evaluation result payloads that quote corpus excerpts
- freeze backups, git bundles and archived snapshots of the private repository

This is deliberate and non-negotiable. **The full application code is included**; only
data and data-derived artifacts are withheld. See [SANITIZATION.md](SANITIZATION.md).

## Why

The original research corpus consists of **copyrighted journal articles**. Downloading
them for research use is one thing; **redistributing them from a public repository is
another**, and it is not something a licence I hold can authorise. The articles come
from a mix of publishers under a mix of terms — some open access, some not — with no
per-item licence record attached, so they cannot be safely republished even
selectively.

Derived artifacts inherit the restriction. Extracted full text is still the article.
An embedding store built from article text still encodes it. Excluding the PDFs but
shipping the index would not solve the problem, so neither is included.

The `.gitignore` in this repository blocks `data/`, `*.pdf`, `fulltext/`,
`harvested_pdfs/`, `corrected_sources/`, `rag_store/`, `DEMO_RUNTIME/`,
`FREEZE_BACKUPS/`, `*.sqlite3`, `*.bin`, `*.safetensors`, `*.bundle` and `*.zip` so
that corpus material, runtime state and model binaries cannot be committed by
accident.

## What this means for reproduction

You cannot reproduce the original published retrieval results from this repository.
That requires the frozen corpus and index, which are retained privately and are not
redistributable. See [`docs/reproducibility.md`](docs/reproducibility.md).

## Building your own corpus

The acquisition stage in `data_acquisition/scraper.py` collects **bibliographic metadata
only** — titles, abstracts, years, identifiers and citation counts from the Semantic
Scholar Graph API. It does not download publisher content. That metadata layer is what
drives screening, and you can rebuild it yourself with your own API key.

To assemble a full-text corpus for your own use:

1. Run the acquisition stage to build a metadata set for your topic.
2. Run the screening stage to filter it against your inclusion criteria.
3. Obtain full text **through legitimate channels you are entitled to use** — your
   institutional subscriptions, open-access sources such as PubMed Central or Europe
   PMC, or direct author copies.
4. Keep that corpus local. Do not commit it.

## If you want to add a sample corpus

A small demonstration corpus may be added **only** if every item's licence is verified
individually as public domain, CC BY, or otherwise explicitly redistributable, and the
licence of each item is recorded alongside it.

"It was freely downloadable" is not a licence. Verify per item, or ship nothing.

This repository ships no sample of *real* literature. It does ship
`examples/synthetic_corpus/` — three fabricated records written for this repository,
describing nothing real and reproducing nothing copyrighted. They exist so the indexing
and retrieval code can be executed end to end without any corpus at all. Three invented
records demonstrate plumbing, not retrieval quality. The `examples/` directory also
explains what a compliant real sample corpus would look like.

## Personal data

No participant data, patient data or human-subject data was involved at any stage of
this project. The corpus consists of published scientific literature. Author names and
correspondence addresses appearing inside published articles are third-party personal
data — another reason article text is not republished here.
