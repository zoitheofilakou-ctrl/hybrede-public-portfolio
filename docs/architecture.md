# Architecture

A description of the HyBreDe system design. Components marked **(not included)** were
principally authored by capstone collaborators and are described here rather than
redistributed — see [CONTRIBUTIONS.md](../CONTRIBUTIONS.md).

## Two phases

HyBreDe separates an **offline corpus construction** phase from an **online retrieval
and synthesis** phase. The separation matters scientifically: once the corpus and index
are frozen, the online phase can be evaluated repeatedly without the evidence base
shifting underneath it.

## Offline: corpus construction

### 1. Metadata acquisition — `src/acquisition/scraper.py`

Queries the Semantic Scholar Graph API across a set of topical queries, restricted to
2020–2024, requesting only the fields the downstream stages need: title, abstract,
year, external identifiers, URL, citation count. Results are deduplicated on
`paperId`. Rate limiting is respected with a 1.1 s inter-request delay.

Only bibliographic metadata is retrieved. No publisher content is downloaded here.

### 2. LLM-assisted screening — `src/screening/llm_screening.py`

Two-step screening of each title/abstract pair:

1. **Screening call.** The model applies prespecified inclusion and exclusion criteria
   and must answer in a fixed `Decision:` / `Justification:` format at temperature 0.
2. **Verification call.** An independent second call checks only whether the decision
   is logically consistent with its own justification and the criteria. It does not
   re-screen.

Design properties worth noting:

- **Conservative default.** Any malformed, missing or ambiguous decision is coerced to
  `EXCLUDE`. The failure mode is a missed candidate, never an unjustified inclusion.
- **Both gates required.** A paper enters the filtered corpus only if it is `INCLUDE`
  *and* `VALID`.
- **Resumable and idempotent.** Already-screened `paperId`s are skipped, so an
  interrupted run resumes without rescreening or double-counting.
- **Audit logging.** Every validated decision is appended to an audit log with a
  UTC timestamp, paper id, decision and validation status.

### 3. Full-text acquisition and extraction **(not included)**

For the screened set, full text is obtained and converted to plain text. This stage is
excluded from the public repository for both authorship and copyright reasons.

### 4. Indexing — hybrid store **(retrieval indexer not included)**

The screened corpus is segmented and indexed twice: into a dense vector store
(ChromaDB, `all-MiniLM-L6-v2` embeddings) and into a BM25 lexical index. The frozen
publication-facing identity was **715 Chroma segments and 715 BM25 records**.

### Immutability controls — `src/indexing/immutable_index.py` *(included, sole authorship)*

This module enforces that evaluation can never mutate the canonical index:

- `tree_manifest()` / `tree_hash()` produce a deterministic SHA-256 over every file in
  an index tree (path, size, content hash, canonically serialised).
- `create_verified_runtime_copy()` copies the canonical index to a fresh runtime
  location, re-manifests the copy, and **raises** unless it is byte-identical. It
  refuses to overwrite an existing runtime directory and refuses a runtime path equal
  to the source. It writes a `.source-verification.json` marker recording both tree
  hashes and an explicit `copy_back_prohibited` flag.
- `assert_source_unchanged()` re-hashes the canonical source afterwards and raises if
  it differs.

In practice this gave a provable statement in the publication record: the canonical
index tree hash was identical before and after the evaluation run.

## Online: retrieval and synthesis **(mostly not included)**

### 5. Hybrid candidate generation

Dense semantic retrieval and BM25 lexical retrieval run in parallel and their results
are fused. The rationale: dense retrieval handles paraphrase and conceptual similarity
but misses exact clinical terminology and rare tokens; BM25 handles exact terms but
misses paraphrase. Neither alone was sufficient on this corpus.

### 6. Reranking and diversification

Candidates are reranked with a cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`)
and diversified with MMR so that the evidence set is not several near-duplicate
passages from one paper.

### 7. Proposition-aware evidence exposure

Rather than passing whole documents to the generator, the system exposes specific
supporting excerpts. Two consequences follow, both important:

- the generator is constrained to material that actually addresses the query;
- every rendered claim can be traced back to an identifiable excerpt, which is what
  makes automated claim-level verification possible at all.

### 8. Evidence-sufficiency gate

Before generation, retrieved evidence is assessed for whether it can support an answer.
Outcomes:

| Disposition | Meaning |
|---|---|
| `supported_answer` | Sufficient evidence; a grounded answer is rendered |
| `bounded_partial` | Part of the question is supported; the unsupported part is explicitly refused |
| `evidence_gap` | Insufficient evidence; the system abstains and says so |

Abstention is a designed outcome, not an error. A conservative false abstention is
treated as preferable to an unsupported claim — the evaluation records show this
tradeoff being made deliberately and one such false abstention being accepted into the
publication freeze rather than tuned away after the fact.

### 9. Claim and citation verification

Each rendered substantive claim is checked for:

- **excerpt identity** — the cited text actually exists in the cited source;
- **citation validity** — the citation resolves to a real indexed document;
- **entailment** — the claim is supported by the excerpt it cites;
- **guarded claim types** — causal, comparative, numerical and temporal claims are
  checked specifically, since these are where ungrounded generation is most damaging.

### 10. Researcher decision authority

The system pre-screens, retrieves and drafts. It does not make clinical decisions and
does not present itself as a clinical decision support system. The human researcher
retains evaluative authority over every output.

## Data flow summary

```
Semantic Scholar API
        |  metadata only
        v
  LLM screening  --(second-pass verification)-->  audit log
        |  INCLUDE + VALID
        v
  Filtered corpus  -->  full-text acquisition  -->  text extraction
        |
        v
  Hybrid index (dense + BM25)  ==[frozen, hash-verified]==> canonical store
        |                                                        |
        |                                        verified disposable copy
        v                                                        v
  Query --> hybrid retrieval --> rerank --> proposition exposure --> sufficiency gate
                                                                        |
                                      +---------------------------------+
                                      |                                 |
                              insufficient                        sufficient
                                      |                                 |
                        evidence_gap / bounded_partial          grounded generation
                                      |                                 |
                                      +------------> claim + citation verification
                                                                        |
                                                          researcher decision authority
```
