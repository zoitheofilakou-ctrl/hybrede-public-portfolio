# Contributions and authorship

This document exists so that nothing in this repository misrepresents who wrote what.

## Origin

HyBreDe originated as a **group ICT capstone project at Turku University of Applied
Sciences**. The original repository has **7 contributors** and **112 commits** spanning
February to September 2026. It is a genuine multi-author work.

I am one of those seven contributors, with 50 of the 112 commits. I do not claim
authorship of the project as a whole.

## What this public repository contains

Only material I authored and am entitled to redistribute. Every candidate file was
checked with line-level `git blame` against the original repository before inclusion.

| File | My share of lines | Basis for inclusion |
|---|---|---|
| `src/indexing/immutable_index.py` | 71 / 71 (100%) | Sole author |
| `src/screening/llm_screening.py` | 433 / 450 (96%) | Principal author |
| `src/acquisition/scraper.py` | 105 / 116 (90%) | Principal author |
| `src/common/paths.py` | new | Written fresh for this release |

For the two files with a minority collaborator contribution, those lines were
`sys.path` bootstrapping and imports of a shared, co-authored path module. That module
is **not** redistributed here, and the sanitized versions replace those imports with
`src/common/paths.py`, which I wrote for this release. The residual collaborator
contribution in the published files is therefore minimal.

If a collaborator would nonetheless prefer their remaining contribution removed or
attributed differently, I will act on that on request.

## What is deliberately excluded

These modules are principally authored by teammates. **They are not included, and
nothing here relicenses them.**

| Excluded module | Reason |
|---|---|
| `Retrieval/retrieval.py` | Principally authored by a collaborator |
| `llm/rag_generator.py` | Principally authored by a collaborator |
| `run_manifest.py` | Authored by a collaborator |
| `console_utils.py` | Authored by a collaborator |
| `project_paths.py` | Principally authored by a collaborator |
| `app.py` (Streamlit UI) | Authorship split roughly evenly; rights unclear |
| `technical_documentation.docx` | University capstone deliverable |

The behaviour of the retrieval and generation stages is **described** in
[`docs/architecture.md`](docs/architecture.md). Describing a system's design is not the
same as claiming authorship of its implementation, and no collaborator code is
reproduced in those descriptions.

## My independent post-capstone contribution

After the capstone concluded, I continued the project independently. This work is
solely mine and forms the substantive research content of this portfolio:

- evaluation design and prespecified challenge-set methodology
- freeze discipline: immutable scientific states, freeze gates, protection manifests
- provenance tracking and immutability proofs
- claim-level and citation-identity verification methodology
- failure localization and remediation protocols
- corpus integrity and acquisition auditing
- publication-facing validation documentation, decision logs and the manuscript

## Privacy

Collaborator names and email addresses are **not** reproduced here. The original
repository embeds author identities in commit metadata, which is one of several
reasons that repository is not published and this one was built with a fresh history
instead.

## Third-party components

The system depends on third-party models and services that are neither authored by me
nor redistributed here: `all-MiniLM-L6-v2`, `cross-encoder/ms-marco-MiniLM-L-6-v2`,
OpenAI models, ChromaDB, Sentence Transformers, and the Semantic Scholar Graph API.
Each remains under its own licence and terms.
