# Tests

Run everything:

```bash
python -m pytest tests/ -q          # or: python -m unittest discover -s tests -t .
```

## What passes in a bare public checkout

Nine of the thirteen modules pass completely — **89 tests, no failures** — with no
corpus, no evidence store and no API key. They exercise the evidence-sufficiency
gate, claim-support verification, citation and excerpt-identity checks, proposition
exposure, entailment guardrails, the retrieval scoring and fusion logic, and the
Run 14 / Run 15 remediation invariants.

| Module | Result |
|---|---|
| `test_generation_safeguards.py` | 11 passed |
| `test_post_run11_remediation.py` | 7 passed |
| `test_proposition_excerpt_exposure.py` | 10 passed |
| `test_protocol_v4_remediation.py` | 8 passed |
| `test_rag_generator.py` | 15 passed |
| `test_retrieval.py` | 17 passed |
| `test_run14_technical_remediation.py` | 7 passed |
| `test_run15_scientific_remediation.py` | 11 passed |
| `test_scientific_entailment_guardrails.py` | 3 passed |

## What does not pass, and why

None of these are caused by the public sanitization breaking the code. Three of the
four fail **identically in the private frozen research checkout**, because they depend
on artifacts that are not present there either.

| Module | Status | Cause |
|---|---|---|
| `test_production_orchestration_25.py` | import error | needs `validation.evaluation`, a historical run-harness package absent from the frozen source too |
| `test_run7_production_path.py` | import error | same |
| `test_run8_production_path.py` | import error | same |
| `test_validated_claim_pipeline_v2.py` | 7 passed, 2 errors | one error needs `validation/prospective_evaluation_v2/`, absent from the frozen source too; the other reads the corpus source manifest and the Chroma store, which are deliberately **not distributed** (see [DATA_POLICY.md](../DATA_POLICY.md)) |

They are kept rather than deleted so the real test surface of the project is visible
rather than a curated subset of it.

## Startup smoke test

[`examples/smoke_test.py`](../examples/smoke_test.py) is the check to run first. It
verifies that every module imports from a bare checkout, that all paths resolve from
configuration rather than from any author's machine, and that a missing evidence store
produces a clear error. With `--build-index` it builds a real hybrid index from the
synthetic corpus and queries it.
