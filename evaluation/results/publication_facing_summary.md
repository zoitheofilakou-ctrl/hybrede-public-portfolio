# Publication-facing evaluation summary

This document reports **only** the publication-facing evaluation. Developmental runs
are explicitly excluded — see [Scope](#scope) at the end.

## Study status

The publication-facing evaluation was **Run 14**: a prespecified ten-case behavioural
challenge set comprising eight independent cases and two regression cases, **frozen
before execution**.

Run 14 produced **7 of 10 expected dispositions**, with **three false abstentions**.

A subsequent **known-case regression** re-ran the same ten cases after remediation. It
matched **9 of 10** expected dispositions.

> The 9/10 figure is **not accuracy** and **not an estimate of general performance**.
> It re-ran cases that were already known and already analysed. It is reported here as
> a regression result only. The word "accuracy" is deliberately not used for it.

## Final known-case regression, per case

| Case | Original Run 14 | Final regression | Interpretation |
|---|---|---|---|
| R14-R1 | supported answer | `supported_answer` | preserved |
| R14-R2 | false abstention | `evidence_gap` | residual conservative false abstention |
| R14-I1 | false abstention | `supported_answer` | corrected |
| R14-I2 | supported answer | `supported_answer` | preserved |
| R14-I3 | false abstention | `bounded_partial` | corrected |
| R14-I4 | abstention | `evidence_gap` | preserved causal safeguard |
| R14-I5 | abstention | `evidence_gap` | preserved comparator safeguard |
| R14-I6 | abstention | `evidence_gap` | preserved numerical/temporal safeguard |
| R14-I7 | abstention | `evidence_gap` | preserved out-of-domain safeguard |
| R14-I8 | abstention | `evidence_gap` | preserved causal/numerical safeguard |

Two of the three false abstentions (R14-I1, R14-I3) were corrected. R14-R2 remained a
conservative false abstention and was **accepted into the publication freeze** rather
than resolved by weakening sufficiency rules after observing the case.

R14-I3 is worth describing precisely: it produced a grounded **bounded partial**. It
supplied only the supported CDSS definition, cited the approved excerpt, explicitly
stated that the requested exact numerical value was not supported by the evidence, and
introduced no number of its own.

## Claim-level results

| Metric | Result |
|---|---|
| Rendered substantive claims | 8 |
| Directly supported rendered claims | 8 |
| Unsupported rendered claims | 0 |
| Invalid or fabricated citations | 0 |
| Source/excerpt identity mismatches | 0 |
| Unsupported causal, comparative, numerical or temporal claims | 0 |
| Technical failures | 0 |

The eight claims comprised one for R14-R1, one for R14-I1, five for R14-I2 and one for
R14-I3.

All eight passed automated excerpt-identity, citation and model-based entailment
checks. **No independent human claim adjudication was documented.** The verification
was automated, and this summary does not claim otherwise.

## Reproducibility and protection

| Component | Identity |
|---|---|
| Python | 3.11.5 |
| Embedding model | `all-MiniLM-L6-v2` |
| Cross-encoder | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| Generation model | `gpt-4o-mini` |
| ChromaDB | 1.5.1 |
| Sentence Transformers | 5.2.3 |
| Frozen retrieval identity | 715 Chroma segments, 715 BM25 records |

Protection outcomes:

- Original Run 14 files were **byte-for-byte unchanged** by the later regression.
- The canonical index tree hash was **identical before and after**.
- The regression executed against a **verified disposable runtime copy**; no data was
  copied back into the canonical index.
- Acquisition, screening, corpus selection, retrieval thresholds, hybrid weights, BM25
  parameters, cross-encoder settings, MMR settings, query expansion and paper selection
  were **not changed** by the regression execution.

## Withdrawn claim

A previously stated **`130/130` test result was withdrawn** during publication
preparation, because no corresponding primary execution report could be recovered. It
was not replaced with another numeric test count, and no test rerun was performed
merely to generate a publishable figure. The withdrawal is recorded in the project
decision log.

## Scientific conclusion

Remediation corrected two of the three known false abstentions while retaining zero
unsupported claims and zero citation-integrity failures. The remaining R14-R2 false
abstention is conservatively accepted.

**No inference about general accuracy, external validity or expected future
performance is supported by this known-case regression.**

## Scope

Developmental and internal iteration runs (referred to elsewhere as runs 1–13) are
**not** publication-facing results and are not reported here as validation outcomes.
They exist as internal engineering history. Presenting them as evaluation results
would misrepresent the study.

Methodology behind these results: [`docs/methodology.md`](../../docs/methodology.md).
Constraints on interpreting them: [`docs/limitations.md`](../../docs/limitations.md).
