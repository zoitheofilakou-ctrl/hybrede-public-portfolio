# Limitations

Stated plainly, because a portfolio that overstates its results is worse than one that
claims less.

## Scope and maturity

- **Research prototype.** HyBreDe is not a production system. It has no deployment
  hardening, no SLA, no monitoring, no multi-user support.
- **Not clinically validated.** It has never been used in patient care and is not a
  regulated medical device. It performs no diagnosis, no outcome prediction and no
  autonomous clinical decision-making — these were explicit exclusion criteria in the
  screening stage as well as design constraints.
- **No real deployment.** All evaluation was offline against a frozen corpus.

## Evaluation

- **Small evaluation set.** The publication-facing challenge set is **ten cases**. No
  general-performance claim can follow from ten cases, and none is made.
- **Known-case reuse.** The post-remediation run re-ran the same ten cases. It is a
  regression check, not independent validation, and cannot demonstrate generalisation.
  Its 9/10 result is **not accuracy**.
- **No blinded human adjudication.** Claim-level verification was automated
  (excerpt-identity, citation and model-based entailment checks). No independent human
  adjudicated the rendered claims.
- **Single domain.** Healthcare literature on professional practice, evidence-based
  practice and health information systems. Behaviour on other domains is unknown.
- **Single corpus.** 715 indexed segments from one screened collection. Retrieval
  behaviour on a larger or differently-constructed corpus is untested.
- **Residual known failure.** One case (R14-R2) remained a conservative false
  abstention and was accepted into the freeze deliberately.

## Reproducibility

- **Corpus not included.** Copyright prevents redistribution, so the published
  retrieval results cannot be reproduced from this repository. See
  [DATA_POLICY.md](../DATA_POLICY.md).
- **Partial codebase.** Retrieval and generation modules are omitted for authorship
  reasons, so this repository is not runnable end to end.
- **External model dependence.** Results depend on `gpt-4o-mini`, `all-MiniLM-L6-v2`
  and `cross-encoder/ms-marco-MiniLM-L-6-v2`. Hosted model behaviour can change over
  time, and exact reproduction of generation outputs is not guaranteed even with the
  original corpus.
- **Approximate nearest-neighbour indexing.** The vector store uses HNSW. At this
  corpus size search is effectively exhaustive, but bit-exact replay of an ANN graph
  is not guaranteed across rebuilds.

## Methodological

- **Screening is LLM-assisted, not authoritative.** The screening stage narrows a
  candidate set for human review. Its criteria are conservative and will exclude
  borderline-relevant work; recall was not separately measured against a human-screened
  gold standard.
- **Automated entailment has limits.** Model-based entailment checking can itself err.
  It reduces, but does not eliminate, the risk of an unsupported claim passing.
- **Prespecification limits exploration.** Freezing cases before execution protects
  against post-hoc target definition but means the evaluation cannot adapt to
  behaviours discovered mid-run. Those are recorded for future cycles instead.

## Authorship

- This repository contains **part** of a seven-person capstone project. See
  [CONTRIBUTIONS.md](../CONTRIBUTIONS.md) for exactly which parts are mine.
