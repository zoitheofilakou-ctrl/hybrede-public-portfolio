import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import Mock

from llm import rag_generator as rg

ROOT = Path(__file__).resolve().parents[1]


def src(pid="p1", rank=1, text="The study reports a descriptive finding."):
    return {"paperId": pid, "excerpt_id": f"{pid}:{rank}", "rank": rank,
            "title": pid, "year": 2024, "text": text}


def contract(decision="sufficient", supported=("outcome",), missing=()):
    return {"decision": decision, "permitted_answer_scope": list(supported),
            "prohibited_answer_scope": list(missing)}


def claim_payload(**updates):
    payload = {"disposition": "answer", "claims": [{
        "claim_id": "cl1", "component_id": "outcome", "claim_text": "A descriptive finding was reported.",
        "excerpt_ids": ["p1:1"], "paper_ids": ["p1"], "evidence_strength": "descriptive",
    }], "unsupported_components": []}
    payload.update(updates)
    return payload


class SequencedLLM:
    def __init__(self, *responses):
        self.responses = iter(responses)
    def generate_structured(self, prompt, system_message=None):
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return item


class ValidatedClaimContractTests(unittest.TestCase):
    def run_case(self, payload, verdict="entailed", c=None, sources=None):
        llm = SequencedLLM(json.dumps(payload), json.dumps({"verdict": verdict, "rationale": "test"}))
        return rg.generate_validated_claims("Question?", c or contract(), sources or [src()], llm)

    def test_valid_claim_is_rendered(self):
        result = self.run_case(claim_payload())
        self.assertEqual(1, len(result["valid_claims"]))
        self.assertIn("[1]", result["rendered"])

    def test_all_non_entailing_verdicts_remove_claim(self):
        for verdict in ("contradicted", "topically_related_not_entailed",
                        "insufficiently_specific", "unverifiable", "uncertain"):
            with self.subTest(verdict=verdict):
                result = self.run_case(claim_payload(), verdict)
                self.assertEqual([], result["valid_claims"])
                self.assertEqual(verdict, result["removed_claims"][0]["removal_reason"])

    def test_schema_and_identity_fail_closed(self):
        cases = [
            {},
            claim_payload(disposition="invalid"),
            claim_payload(disposition="abstain"),
            claim_payload(unsupported_components=["unknown"]),
            claim_payload(claims=[{**claim_payload()["claims"][0], "component_id": "unknown"}]),
            claim_payload(claims=[{**claim_payload()["claims"][0], "excerpt_ids": []}]),
            claim_payload(claims=[{**claim_payload()["claims"][0], "excerpt_ids": ["missing:1"]}]),
            claim_payload(claims=[{**claim_payload()["claims"][0], "paper_ids": ["wrong"]}]),
            claim_payload(claims=[{k:v for k,v in claim_payload()["claims"][0].items()
                                  if k != "evidence_strength"}]),
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                llm = SequencedLLM(json.dumps(payload))
                result = rg.generate_validated_claims("Q", contract(), [src()], llm)
                self.assertEqual([], result["valid_claims"])

    def test_validator_malformed_exception_and_unavailable_fail_closed(self):
        for response in ("not json", RuntimeError("offline")):
            with self.subTest(response=response):
                llm = SequencedLLM(json.dumps(claim_payload()), response)
                result = rg.generate_validated_claims("Q", contract(), [src()], llm)
                self.assertEqual([], result["valid_claims"])
                self.assertIn("validator_unavailable_or_malformed",
                              result["removed_claims"][0]["removal_reason"])

    def test_partial_contract_requires_matching_unsupported_components(self):
        payload = claim_payload(disposition="partial", unsupported_components=["numerical_value"])
        result = self.run_case(payload, c=contract("partial", ("outcome",), ("numerical_value",)))
        self.assertEqual(1, len(result["valid_claims"]))

    def test_adversarial_construct_substitutions_are_removed(self):
        pairs = [
            ("trust", "automation bias"), ("transparency", "mitigation of automation bias"),
            ("association", "causation"), ("barrier", "demonstrated outcome"),
            ("qualitative description", "30 percent"), ("parallel descriptions", "superiority"),
            ("intention to use", "clinical outcome"), ("recommendation", "effectiveness"),
            ("topical relevance", "question-specific evidence"), ("citation", "claim support"),
        ]
        for evidence, claim in pairs:
            with self.subTest(evidence=evidence, claim=claim):
                payload = claim_payload()
                payload["claims"][0]["claim_text"] = claim
                result = self.run_case(payload, "topically_related_not_entailed",
                                       sources=[src(text=evidence)])
                self.assertEqual([], result["valid_claims"])


class ParserAndCorpusIntegrityV2Tests(unittest.TestCase):
    def test_parser_preserves_compound_scientific_requirements(self):
        cases = {
            "What is CDSS, and what percentage reduces errors?": {"definition_concept", "numerical_value"},
            "What is trust, and does it cause bias?": {"definition_concept", "causal_contribution"},
            "Is A better compared with B?": {"quantitative_comparison"},
            "What is the long-term outcome?": {"definition_concept"},
        }
        for q, expected in cases.items():
            with self.subTest(q=q):
                ids = {x["component_id"] for x in rg.build_question_specification(q)["components"]}
                self.assertTrue(expected <= ids)

    def test_v3_corpus_and_indexes_are_exact(self):
        manifest = json.loads((ROOT/"data/processed/corpus_source_manifest_v3.json").read_text(encoding="utf8"))
        records = manifest["records"]
        self.assertEqual(107, len(records))
        self.assertEqual(2, sum(r["source_type"] == "non_evidence_bearing" for r in records))
        lexical = json.loads((ROOT/"rag_store/lexical_index.json").read_text(encoding="utf8"))["records"]
        lids = {r["chunk_id"] for r in lexical}
        db = sqlite3.connect(ROOT/"rag_store/chroma.sqlite3")
        vids = {r[0] for r in db.execute("select embedding_id from embeddings")}
        self.assertEqual(715, len(lids))
        self.assertEqual(lids, vids)
        self.assertFalse(any(r["text"].strip() == "No abstract provided" for r in lexical))

    def test_historical_immutability_proof_passes(self):
        proof = json.loads((ROOT/"validation/prospective_evaluation_v2/historical_run_immutability_proof.json").read_text())
        self.assertTrue(proof["all_unchanged"])


if __name__ == "__main__":
    unittest.main()
