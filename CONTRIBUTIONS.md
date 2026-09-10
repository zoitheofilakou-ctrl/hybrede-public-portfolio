# Contributions and authorship

This document exists so that nothing in this repository misrepresents who wrote
what. **HyBreDe is a multi-author work and is published here as one.**

## Origin

HyBreDe began as a **group ICT capstone project at Turku University of Applied
Sciences**. The original repository has **7 contributors** and **112 commits**
spanning February to September 2026. After the capstone concluded, I (Zoi
Theofilakou) continued the project independently; that later work is described
in its own section below.

I am one of those seven contributors, with 50 of the 112 commits. **I do not
claim authorship of the project as a whole, and nothing in this repository
should be read as such a claim.**

## What changed in this release

The first commit of this repository published only the subset of files I had
principally authored. Everything else was described but withheld.

That is no longer the case. **This release publishes the complete application
architecture, including modules principally authored by collaborators.** The
decision to publish the whole system was mine to make as a contributor to an
already MIT-licensed project; the licence terms are unchanged, and the original
capstone copyright notice is preserved verbatim in [LICENSE](LICENSE) alongside
mine. See that file for the copyright treatment.

## Per-module authorship

Figures are **line-level `git blame`** against the original history at the
frozen presentation commit. They count surviving lines, so a module rewritten
after the capstone attributes to whoever wrote the surviving code — this is why
`llm/rag_generator.py` is now principally mine while `Retrieval/retrieval.py`
is not.

| Module | Principal author | Line attribution |
|---|---|---|
| `Retrieval/retrieval.py` — hybrid retrieval: dense, BM25, fusion, cross-encoder rerank, MMR | **Collaborator A** | A 1840 · me 135 |
| `llm/interface.py` — LLM provider abstraction (OpenAI / Ollama) | **Collaborator B** | B 75 · A 27 · me 17 |
| `data_acquisition/PDFscraper.py` — PDF harvesting | **Collaborator C** | C 143 · A 12 |
| `data_acquisition/pdf_to_text.py` — PDF → text extraction, fuzzy identity matching | **Collaborator C** | C 104 · A 12 |
| `run_manifest.py` — run manifest emission | **Collaborator A** | A 42 (sole) |
| `console_utils.py` — console JSON dumping | **Collaborator A** | A 26 (sole) |
| `project_paths.py` — canonical path layout | **Collaborator A** | A 27 · me 7 (+ public-release changes, see SANITIZATION.md) |
| `tests/test_retrieval.py` | **Collaborator A** | A 424 · me 39 |
| `llm/rag_generator.py` — RAG orchestration, evidence gate, claim verification | **me** | me 1051 · A 172 · B 125 |
| `app.py` — Streamlit interface | **me** | me 1267 · Collaborator D 30 |
| `screening/llm_screening.py` — LLM screening, verification, audit logging | **me** | me 433 · A 17 |
| `data_acquisition/scraper.py` — Semantic Scholar metadata acquisition | **me** | me 105 · A 11 |
| `immutable_index.py` — immutable-source / disposable-runtime controls | **me** | me 71 (sole) |
| `tests/` (12 remaining files) | **me** | me 1752 · A 86 |

Where a module is principally a collaborator's, **it is theirs**: I contributed
integration lines (imports, `sys.path` bootstrapping, path constants, and in
`Retrieval/retrieval.py` the post-capstone remediation fixes), not its design.

### On collaborator names

Collaborators are identified here as A–D rather than by name, and **no
collaborator email address appears anywhere in this repository**. This
repository was built with a fresh history precisely so that author identities
in commit metadata are not republished. The mapping from A–D to real people
exists in the original capstone repository. Any collaborator who would prefer to
be credited by name, attributed differently, or have their contribution removed
should say so and I will act on it.

## My independent post-capstone contribution

After the capstone concluded I continued the project alone. This work is solely
mine and is the substantive research-engineering content of this portfolio:

- **Evidence sufficiency gate** — refusing to answer rather than answering
  thinly, and bounding partial answers to what the evidence supports
  (`llm/rag_generator.py`).
- **Claim-support verification** — every rendered claim checked against an
  approved excerpt before display; unsupported claims withheld.
- **Citation and source-identity verification** — excerpt-identity and citation
  checks preventing a claim from being attributed to a paper that does not
  support it.
- **Proposition-aware evidence exposure** — surfacing the specific excerpt a
  claim rests on rather than a whole document.
- **Freeze discipline and provenance** — immutable scientific states, freeze
  gates, protection manifests, immutability proofs (`immutable_index.py`,
  `run_manifest.py` usage, `validation/`).
- **Evaluation design** — prespecified challenge-set methodology, run protocols,
  claim-level auditing, failure localization and remediation protocols.
- **Corpus integrity and acquisition auditing** — `validation/acquisition_corpus_audit/`.
- **The current Streamlit interface** — disposition rendering, evidence
  exposure, scope handling.
- **Publication preparation** — validation documentation, decision logs, the
  manuscript, and this public sanitized release.

## Third-party components

The system depends on third-party models and services that are neither authored
by any project contributor nor redistributed here: `all-MiniLM-L6-v2`,
`cross-encoder/ms-marco-MiniLM-L-6-v2`, OpenAI models, Ollama, ChromaDB,
Sentence Transformers, and the Semantic Scholar Graph API. Each remains under
its own licence and terms.
