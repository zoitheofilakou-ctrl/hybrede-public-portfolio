# Challenge-set design

How the behavioural evaluation cases were constructed. This is methodology, not
results — results are in
[`../results/publication_facing_summary.md`](../results/publication_facing_summary.md).

## Purpose

The challenge set does not measure retrieval quality metrics such as nDCG or recall@k.
It tests **behavioural correctness under evidential pressure**: given a query and a
frozen corpus, does the system answer when it should, abstain when it should, and
refuse the unsupported part of a question while still answering the supported part?

For an evidence-grounded system intended to support researchers, that behaviour matters
more than a ranking metric. A system that ranks well but confidently answers a question
its corpus cannot support is the more dangerous failure.

## Structure

The publication-facing set contained **ten cases**:

- **8 independent cases** (`R14-I1` … `R14-I8`) — behaviours not previously exercised.
- **2 regression cases** (`R14-R1`, `R14-R2`) — behaviours that had to be preserved.

## Prespecification

For each case, the following were written down and **frozen before execution**:

1. the query;
2. the expected disposition (`supported_answer`, `bounded_partial`, `evidence_gap`);
3. the reason that disposition is correct given the frozen corpus;
4. for expected answers, what a correct answer must and must not contain.

Freezing the expected disposition in advance is the point. Without it, an abstention
can always be rationalised after the fact as appropriate caution, and the evaluation
measures nothing.

## Dispositions

| Disposition | Correct when |
|---|---|
| `supported_answer` | The corpus contains sufficient evidence for a complete grounded answer |
| `bounded_partial` | Part of the question is supported; the rest must be explicitly refused |
| `evidence_gap` | The corpus cannot support an answer; the system must abstain and say so |

An abstention where the prespecified expectation was `supported_answer` is recorded as
a **false abstention** — a real error, not reframed as caution.

## Safeguard categories probed

Independent cases deliberately targeted the claim types where ungrounded generation is
most damaging:

| Case | Safeguard probed |
|---|---|
| R14-I4 | causal claims |
| R14-I5 | comparative claims |
| R14-I6 | numerical / temporal claims |
| R14-I7 | out-of-domain queries |
| R14-I8 | combined causal + numerical claims |

Each was constructed so the frozen corpus could **not** support the claim, making the
correct behaviour an explicit evidence gap. These test that the system declines to
manufacture a causal link, a comparison, or a number that its evidence does not contain.

## Eligibility gate

Before a run, an eligibility checklist verified that:

- the protocol and case set were frozen and hash-recorded;
- protection manifests matched the canonical artifacts;
- the runtime index was a verified byte-identical disposable copy;
- no scientific parameter had changed since the previous freeze.

A run that failed the gate was not eligible to produce publication-facing results.

## Prohibited practices

Written into the protocol and enforced in review:

- **No post-hoc target redefinition.** Expected dispositions cannot change after
  seeing outputs.
- **No case-specific tuning.** Thresholds may not be adjusted to make a known failing
  case pass. Remediation fixes mechanisms, not cases.
- **No silent case substitution.** Cases may not be dropped or swapped mid-cycle.
- **No relabelling regression as validation.** A rerun of known cases is reported as a
  regression, never as independent validation.

## Known limitation of the design

Ten cases is a small set, and after the first cycle those cases are no longer
independent — the system has been analysed against them. This is why the
post-remediation rerun is reported strictly as a **known-case regression** and why no
general-performance claim is made from it.

A genuinely prospective follow-up would require a **new** prespecified case set,
frozen before execution and never previously analysed. A held-out set was prepared for
later experimental work but is not part of the publication-facing evaluation.
