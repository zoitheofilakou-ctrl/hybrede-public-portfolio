import copy
import json
import unittest
from unittest.mock import Mock, patch

from llm import rag_generator as rg


class FakeArray:
    def tolist(self):
        return [[0.1, 0.2]]


def source(paper_id="paper-a", rank=1):
    return {
        "paperId": paper_id, "excerpt_id": f"{paper_id}:{rank}", "rank": rank,
        "title": f"Paper {paper_id}", "year": 2024, "text": "Direct evidence.",
        "url": "https://example.test", "text_source": "abstract", "section": "abstract",
    }


def gate(decision="sufficient"):
    missing = [] if decision == "sufficient" else ["comparator"]
    return {
        "decision": decision, "requested_components": ["outcome"] + missing,
        "supported_components": ["outcome"], "missing_components": missing,
        "essential_missing_components": [], "concise_rationale": "bounded evidence",
        "supporting_source_ids": ["paper-a"],
        "components": [
            {"component_id": "outcome", "status": "directly_supported",
             "supporting_source_ids": ["paper-a"], "supporting_excerpt_ids": ["paper-a:1"],
             "rationale": "direct"}
        ],
        "raw_output": "{}", "diagnostic_category": None, "error": None,
    }


class QuestionSpecificationAndDecisionTests(unittest.TestCase):
    def test_component_detection_matrix(self):
        cases = {
            "What is automation bias?": {"definition_concept"},
            "What is the outcome in patients?": {"definition_concept"},
            "Does AI affect nurses in hospitals?": {"direct_relationship"},
            "What is long-term mortality?": {"definition_concept"},
            "What percentage compared with rule-based CDSS?": {"numerical_value"},
            "Does exposure contribute to the outcome?": {"causal_contribution"},
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                actual = {c["component_id"] for c in rg.build_question_specification(question)["components"]}
                self.assertTrue(expected.issubset(actual))
                self.assertTrue(actual.issubset(rg.COMPONENT_IDS))

    def test_derive_decision_boundaries(self):
        spec = {"components": [
            {"component_id": "outcome", "essential": True},
            {"component_id": "context", "essential": False},
        ]}
        supported = lambda cid: {"component_id": cid, "status": "directly_supported"}
        unsupported = lambda cid: {"component_id": cid, "status": "unsupported"}
        self.assertEqual("sufficient", rg.derive_decision(spec, [supported("outcome"), supported("context")])[0])
        self.assertEqual("partial", rg.derive_decision(spec, [supported("outcome"), unsupported("context")])[0])
        self.assertEqual("partial", rg.derive_decision(spec, [unsupported("outcome"), supported("context")])[0])
        self.assertEqual("insufficient", rg.derive_decision(spec, [unsupported("outcome"), unsupported("context")])[0])


class ContractAndValidationTests(unittest.TestCase):
    def test_gate_rejects_unknown_or_mismatched_excerpt_ids(self):
        for excerpt_id in ("missing:1", "paper-b:1"):
            llm = Mock()
            llm.generate_structured.return_value = json.dumps({
                "components": [{
                    "component_id": "outcome", "status": "directly_supported",
                    "supporting_source_ids": ["paper-a"],
                    "supporting_excerpt_ids": [excerpt_id], "rationale": "claimed",
                }],
                "concise_rationale": "claimed",
            })
            sources = [source("paper-a"), source("paper-b")]
            with self.subTest(excerpt_id=excerpt_id):
                result = rg.assess_evidence_sufficiency("What was the outcome?", sources, llm)
                self.assertEqual("insufficient", result["decision"])
                self.assertIsNotNone(result["error"])

    def test_contract_is_complete_detached_and_score_free(self):
        original = source()
        original["semantic_similarity"] = 0.91
        contract = rg.build_generation_contract("Outcome?", gate(), [original])
        expected = {
            "original_question", "requested_components", "supported_components",
            "missing_components", "essential_missing_components", "decision",
            "decision_reason", "approved_sources_by_component",
            "resolved_approved_excerpts", "permitted_answer_scope",
            "prohibited_answer_scope", "unsupported_proposition_labels",
            "approved_quantitative_claims",
        }
        self.assertEqual(expected, set(contract))
        self.assertNotIn("semantic_similarity", contract["resolved_approved_excerpts"][0])
        original["text"] = "mutated"
        self.assertEqual("Direct evidence.", contract["resolved_approved_excerpts"][0]["text"])

    def test_citation_validation_rejects_fabricated_unapproved_and_malformed(self):
        sources = [source()]
        for answer in (
            "Claim [2].", "Claim [paper-a].", "Claim [1, 9].", "Claim without citation.",
            "Claim [1].\n\nReferences\n[2] Fabricated",
            "Claim [1].\n\nReferences\n[1] Valid\n[2] Uncited",
        ):
            with self.subTest(answer=answer):
                self.assertFalse(rg.validate_citations_and_references(answer, sources)["valid"])
        valid = rg.validate_citations_and_references("Supported claim [1].", sources)
        self.assertTrue(valid["valid"])
        self.assertEqual([1], valid["citation_numbers"])

    def test_quantitative_validation_matches_every_scientific_dimension(self):
        approved = {
            "value": "30", "unit": "%", "measure_outcome": "readmission",
            "numerator": "30", "denominator": "100", "comparator": "usual care",
            "population": "adults", "context": "hospital", "temporal_horizon": "30 days",
            "source_id": "paper-a", "excerpt_id": "paper-a:1",
        }
        contract = {"approved_quantitative_claims": [approved]}
        self.assertTrue(rg.validate_quantitative_claims("Readmission was 30% [1].", contract, [approved])["valid"])
        for field in approved:
            changed = copy.deepcopy(approved)
            changed[field] = f"wrong-{field}"
            with self.subTest(field=field):
                self.assertFalse(
                    rg.validate_quantitative_claims("Readmission was 30% [1].", contract, [changed])["valid"]
                )
        self.assertFalse(rg.validate_quantitative_claims("Readmission was 30% [1].", contract)["valid"])


class ProductionIntegrationTests(unittest.TestCase):
    def _run(self, gate_result, generated="Supported finding [1]."):
        collection = Mock()
        collection.query.return_value = {
            "documents": [["Direct evidence."]], "metadatas": [[{
                "paperId": "paper-a", "title": "Paper A", "year": 2024,
                "url": "https://example.test", "text_source": "abstract", "section": "abstract",
            }]], "embedding_scores": [[0.9]], "cross_encoder_scores": [[0.8]],
            "retrieval_notes": [[]],
        }
        provider = Mock()
        claim = {
            "disposition": "partial" if gate_result.get("decision") == "partial" else "answer",
            "claims": [{"claim_id": "cl1", "component_id": "outcome",
                        "claim_text": generated.replace(" [1].", "."),
                        "excerpt_ids": ["paper-a:1"], "paper_ids": ["paper-a"],
                        "evidence_strength": "descriptive"}],
            "unsupported_components": gate_result.get("missing_components", []),
        }
        if "[7]" in generated:
            claim["claims"][0]["excerpt_ids"] = ["missing:7"]
        provider.generate_structured.side_effect = [
            json.dumps(claim), json.dumps({"verdict": "entailed", "rationale": "direct"})
        ]
        with patch.object(rg, "require_retrieval_dependencies"), \
             patch.object(rg.os.path, "exists", return_value=True), \
             patch.object(rg, "get_chroma_collection", return_value=collection), \
             patch.object(rg, "get_embedding_model", return_value=Mock(encode=Mock(return_value=FakeArray()))), \
             patch.object(rg, "get_llm_provider", return_value=provider), \
             patch.object(rg, "assess_evidence_sufficiency", return_value=gate_result):
            result = rg.evaluate_single_query("What was the outcome?")
        return result, provider

    def test_production_sufficient_path_is_contract_bounded(self):
        result, provider = self._run(gate())
        self.assertEqual("supported_answer", result["final_disposition"])
        self.assertEqual(["paper-a"], [s["paperId"] for s in result["sources"]])
        self.assertEqual([1], result["citations"])
        self.assertGreaterEqual(provider.generate_structured.call_count, 2)

    def test_production_partial_path_is_contract_bounded(self):
        result, provider = self._run(gate("partial"))
        self.assertEqual("bounded_partial", result["final_disposition"])
        self.assertEqual(["comparator"], result["generation_contract"]["prohibited_answer_scope"])
        self.assertGreaterEqual(provider.generate_structured.call_count, 2)

    def test_nonzero_source_insufficient_bypasses_generation(self):
        insufficient = gate("partial")
        insufficient.update({"decision": "insufficient", "essential_missing_components": ["comparator"]})
        result, provider = self._run(insufficient)
        self.assertEqual("evidence_gap", result["final_disposition"])
        self.assertTrue(result["generation_bypassed"])
        self.assertEqual([], result["citations"])
        provider.generate_structured.assert_not_called()

    def test_invalid_generation_fails_closed_and_preserves_raw_output(self):
        result, _ = self._run(gate(), "Fabricated claim [7].")
        self.assertEqual("evidence_gap", result["final_disposition"])
        self.assertIn("missing:7", result["rejected_generation_output"])
        self.assertEqual([], result["references"])


class RequiredScenarioMatrixTests(unittest.TestCase):
    def test_all_25_scenarios_have_distinct_executable_cases(self):
        cases = [
            ("01_definition", lambda: "definition_concept" in ids("What is trust?")),
            ("02_population", lambda: bool(component("How do nurses respond?")["population"])),
            ("03_context", lambda: bool(component("What occurs in hospitals?")["context"])),
            ("04_intervention", lambda: "AI" in component("Does AI help?")["requirement"] or component("Does AI help?")["component_id"]=="direct_relationship"),
            ("05_comparator", lambda: bool(component("AI versus rules")["comparator"])),
            ("06_outcome", lambda: bool(component("What mortality outcome?")["outcome"])),
            ("07_instrument", lambda: "instrument_measure" in ids("What instrument measures trust?")),
            ("08_time", lambda: bool(component("What is 30-day mortality?")["time_requirement"])),
            ("09_relationship", lambda: "direct_relationship" in ids("How do factors affect trust?")),
            ("10_causal", lambda: "causal_contribution" in ids("Does AI contribute to bias?")),
            ("11_quant_comparison", lambda: "numerical_value" in ids("What percentage compared with rules?")),
            ("12_sufficient", lambda: decision(True, True) == "sufficient"),
            ("13_partial", lambda: decision(True, False, second_essential=False) == "partial"),
            ("14_essential_missing", lambda: decision(False, True) == "partial"),
            ("15_none_supported", lambda: decision(False, False) == "insufficient"),
            ("16_valid_citation", lambda: rg.validate_citations_and_references("Claim [1].", [source()])["valid"]),
            ("17_unknown_citation", lambda: not rg.validate_citations_and_references("Claim [2].", [source()])["valid"]),
            ("18_malformed_citation", lambda: not rg.validate_citations_and_references("Claim [paper].", [source()])["valid"]),
            ("19_missing_citation", lambda: not rg.validate_citations_and_references("Claim.", [source()])["valid"]),
            ("20_no_numeric_claim", lambda: rg.validate_quantitative_claims("Claim [1].", {"approved_quantitative_claims": []})["valid"]),
            ("21_undeclared_number", lambda: not rg.validate_quantitative_claims("30% [1].", {"approved_quantitative_claims": []})["valid"]),
            ("22_unapproved_source", lambda: raises_contract(["missing"])),
            ("23_contract_scope", lambda: rg.build_generation_contract("q", gate(), [source()])["permitted_answer_scope"] == ["outcome"]),
            ("24_score_exclusion", lambda: "semantic_similarity" not in rg.build_generation_contract("q", gate(), [source()])["resolved_approved_excerpts"][0]),
            ("25_deterministic_numbering", lambda: rg.validate_citations_and_references("A [1]. B [1].", [source()])["citation_numbers"] == [1]),
        ]
        self.assertEqual(25, len(cases))
        self.assertEqual(25, len({name for name, _ in cases}))
        for name, operation in cases:
            with self.subTest(scenario=name):
                self.assertTrue(operation())


def ids(question):
    return {c["component_id"] for c in rg.build_question_specification(question)["components"]}

def component(question):
    return rg.build_question_specification(question)["components"][0]


def decision(first, second, second_essential=True):
    spec = {"components": [
        {"component_id": "outcome", "essential": True},
        {"component_id": "context", "essential": second_essential},
    ]}
    assessments = [
        {"component_id": "outcome", "status": "directly_supported" if first else "unsupported"},
        {"component_id": "context", "status": "directly_supported" if second else "unsupported"},
    ]
    return rg.derive_decision(spec, assessments)[0]


def raises_contract(approved_ids):
    bad_gate = gate()
    bad_gate["supporting_source_ids"] = approved_ids
    bad_gate["components"][0]["supporting_source_ids"] = approved_ids
    try:
        rg.build_generation_contract("q", bad_gate, [source()])
    except ValueError:
        return True
    return False


if __name__ == "__main__":
    unittest.main()
