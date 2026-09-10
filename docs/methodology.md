# Evaluation methodology and governance

This document describes how HyBreDe was evaluated and how scientific states were
controlled. This methodology is my independent post-capstone contribution.

## The problem it addresses

Evaluating a retrieval-augmented generation system is easy to do badly. Three failure
modes are common and all of them inflate results:

1. **Post-hoc target definition** — deciding what "correct" means after seeing outputs.
2. **Evidence drift** — the corpus or index changing between runs, so results are not
   comparable.
3. **Known-case reuse presented as validation** — re-running cases the system has
   already been tuned on and reporting the result as general performance.

The methodology below was built to make each of these structurally difficult.

## Prespecification

Evaluation cases and their **expected dispositions were written and frozen before the
run executed**. The publication-facing challenge set comprised ten cases: eight
independent and two regression. Each case specified in advance whether the correct
behaviour was a supported answer, a bounded partial, or an abstention.

This means a case cannot be quietly reinterpreted after the fact. If the system
abstained where the prespecified expectation was a supported answer, that is recorded
as a false abstention — not redefined as correct caution.

## Freeze discipline

A **freeze** is a committed, tagged, hash-verified state that is never rewritten.

- Scientific states are tagged and recorded by commit SHA.
- Before an evaluation cycle, a **freeze gate** verifies that the protected artifacts
  match their recorded hashes.
- **Protection manifests** record which artifacts must not change during a cycle.
- After execution, protection is verified again.

The practical result for the publication record: the original Run 14 artifacts were
byte-for-byte unchanged after the later regression, and the canonical index tree hash
was identical before and after.

## Immutable source, disposable runtime

Evaluation never runs against the canonical index. The harness:

1. hashes the canonical index tree;
2. copies it to a fresh runtime location and verifies the copy is byte-identical,
   raising if not;
3. writes a verification marker recording both tree hashes and prohibiting copy-back;
4. runs the evaluation against the disposable copy;
5. re-hashes the canonical source and raises if it changed.

Implementation: [`src/indexing/immutable_index.py`](../src/indexing/immutable_index.py).

This turns "we did not contaminate the index" from an assurance into a checkable claim.

## Claim-level verification

Aggregate answer-level scoring hides ungrounded content: an answer can be broadly
right and contain one fabricated number. Verification therefore operates per claim:

- **excerpt identity** — the cited text exists verbatim in the cited source;
- **citation validity** — the citation resolves to a real indexed document;
- **entailment** — the claim follows from the excerpt it cites;
- **guarded claim types** — causal, comparative, numerical and temporal claims are
  checked specifically.

Reported honestly: these checks were **automated**. No independent blinded human
adjudication of rendered claims was performed, and the record says so.

## Distinguishing prospective from regression evaluation

This distinction is enforced in the reporting, not just understood informally.

- **Prospective / independent** — cases the system has not been tuned against.
  Run 14 was prospective.
- **Known-case regression** — re-running already-known cases after remediation.
  Useful for confirming a fix did not break something; useless as a performance
  estimate.

The post-remediation run matched 9 of 10 expected dispositions. Because those ten
cases were already known, the documentation states explicitly that **this is not
accuracy and not an estimate of general performance**. The word "accuracy" is
deliberately avoided for it.

## Remediation policy

When a failure is localised, remediation follows fixed rules:

1. Localise the failure to a specific mechanism before changing anything.
2. Fix the mechanism, not the case. Loosening a sufficiency threshold until a known
   case passes is prohibited.
3. Re-verify protection manifests after the change.
4. Report the regression as a regression.
5. If a residual failure is conservative and safe, **accept and document it** rather
   than weakening a safeguard.

That last rule was exercised. One case (R14-R2) remained a conservative false
abstention. It was accepted into the publication freeze rather than fixed by relaxing
sufficiency rules after observing the case.

## Withdrawal of an unsupported claim

During publication preparation a previously stated `130/130` test result could not be
traced to a primary execution report. The claim was **withdrawn**, not restated with a
different number and not quietly dropped. The decision log records the withdrawal, the
reason, and the explicit decision not to substitute another figure or rerun tests
merely to produce a publishable number.

## Provenance record

Each evaluation cycle produced: a protocol definition, a prespecified case set, an
eligibility checklist, execution artifacts, protection verification before and after,
failure-localization output where applicable, a claim-level audit, and a decision log
entry. Together these allow a reader to reconstruct not only what the result was, but
what was decided, when, and on what basis.
