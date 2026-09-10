# Examples

Two things live here:

| Item | Purpose |
|---|---|
| [`smoke_test.py`](smoke_test.py) | Startup check: every module imports from a bare checkout, every path resolves from configuration, a missing evidence store fails clearly. With `--build-index` it builds a real hybrid index from the synthetic corpus and queries it. |
| [`synthetic_corpus/`](synthetic_corpus/) | Three fabricated records (two abstract-only, one with a synthetic full-text body) in the exact schema the indexer expects. Written for this repository; describes nothing real and reproduces nothing copyrighted. |

Run them:

```bash
python examples/smoke_test.py                 # no dependencies beyond the repo
python examples/smoke_test.py --build-index   # needs chromadb + sentence-transformers
```

`--build-index` additionally needs `all-MiniLM-L6-v2` and
`cross-encoder/ms-marco-MiniLM-L-6-v2` already present in the local Hugging Face cache,
because retrieval loads them with `local_files_only=True`.

The synthetic corpus is a **plumbing test, not a demo of retrieval quality**. Three
fabricated records cannot show whether hybrid retrieval works; they show that the code
runs. For meaningful behaviour you need a real corpus of your own.

## No real corpus data is included here

## Why it is empty of data

The original research corpus is copyrighted journal literature and cannot be
redistributed. See [DATA_POLICY.md](../DATA_POLICY.md). Shipping a "small sample" of
publisher PDFs would be the same copyright problem at smaller scale, so nothing is
shipped.

## What a compliant sample corpus would look like

If you want to add one — for your own fork, or as a contribution — every item must be
individually verified as redistributable. "It was freely downloadable" is not a licence.

A compliant sample would be:

```
examples/sample_corpus/
  LICENSES.md              # per-item: DOI, title, licence, source URL, verified date
  <doi-or-id>.pdf          # only if that item's licence permits redistribution
  <doi-or-id>.txt          # extracted text, same licence constraint
```

`LICENSES.md` must record, for every item:

| Field | Example |
|---|---|
| DOI / identifier | `10.2196/12345` |
| Title | … |
| Licence | CC BY 4.0 / CC0 / public domain |
| Source URL | canonical publisher or repository URL |
| Verified on | date the licence was checked |

Acceptable licences: **CC0**, **CC BY**, **CC BY-SA**, or unambiguous public domain.
Anything else — including "free to read", "open access" without a stated licence, or
publisher-hosted PDFs with no licence statement — does not qualify.

## Building your own corpus

You do not need any full text to get started:

1. **Acquisition** (`python data_acquisition/scraper.py`) retrieves bibliographic
   metadata only — titles and abstracts. No publisher content is downloaded, so there
   is no redistribution question for the metadata you generate locally.
2. **Screening** (`python screening/llm_screening.py`) runs entirely on those titles
   and abstracts and writes `processed/filtered_papers.json`.
3. **Indexing** (`python Retrieval/retrieval.py index`) will index abstract-only
   records perfectly well. Full text improves retrieval but is not required.

Abstracts returned by the Semantic Scholar API are still publisher content. Fetching
them for your own use is not the same as redistributing them — do not commit them.

Full-text acquisition (`data_acquisition/PDFscraper.py`, `data_acquisition/pdf_to_text.py`)
is included and works, but what it harvests is copyrighted and must stay local.
See [DATA_POLICY.md](../DATA_POLICY.md) and
[`docs/architecture.md`](../docs/architecture.md).
