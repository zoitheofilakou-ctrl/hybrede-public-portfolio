import json
import unittest

from llm import rag_generator as rg


class GateLLM:
    def __init__(self, payload):
        self.payload = payload
    def generate_structured(self, *_args, **_kwargs):
        return json.dumps(self.payload)


def source(text="Direct evidence.", paper="paper-1", excerpt="paper-1:1"):
    return {"paperId": paper, "excerpt_id": excerpt, "rank": 1, "title": "Paper",
            "year": 2024, "text": text, "section": "results"}


class Run15ParserRemediationTests(unittest.TestCase):
    def test_workflow_obstacles_are_typed_barriers_with_qualifiers(self):
        component = rg.build_question_specification(
            "What workflow obstacles have healthcare professionals reported when "
            "hospitals introduce computerized clinical decision support?"
        )["components"][0]
        self.assertEqual("direct_relationship", component["component_id"])
        self.assertEqual("barrier_identification", component["request_type"])
        self.assertIn("healthcare professionals", component["population"])
        self.assertIn("hospital", component["context"])
        self.assertIn("clinical decision support system", component["intervention_or_exposure"])
        self.assertFalse(component["causal_requirement"])
        self.assertIsNone(component["numerical_requirement"])

    def test_hyphenated_primary_care_definition_preserves_context(self):
        component = rg.build_question_specification(
            "How is evidence-based practice conceptualized in primary-care studies?"
        )["components"][0]
        self.assertEqual("definition_concept", component["component_id"])
        self.assertIn("primary care", component["context"])
        self.assertIsNone(component["numerical_requirement"])

    def test_compound_definition_and_percentage_are_independent(self):
        components = rg.build_question_specification(
            "Define computerized clinical decision support and state the exact "
            "percentage by which it prevents diagnostic mistakes."
        )["components"]
        by_id = {component["component_id"]: component for component in components}
        self.assertEqual({"definition_concept", "numerical_value"}, set(by_id))
        self.assertIsNone(by_id["definition_concept"]["numerical_requirement"])
        self.assertNotIn("diagnostic errors", by_id["definition_concept"]["outcome"])
        self.assertEqual("explicit value required", by_id["numerical_value"]["numerical_requirement"])
        self.assertIn("diagnostic errors", by_id["numerical_value"]["outcome"])

    def test_causal_numerical_qualifiers_remain_on_numerical_proposition(self):
        component = rg.build_question_specification(
            "Give the exact 30-day survival percentage attributable to AI decision support."
        )["components"][0]
        self.assertTrue(component["causal_requirement"])
        self.assertEqual("30 days", component["time_requirement"])
        self.assertIn("survival", component["outcome"])


class PropositionDecisionTests(unittest.TestCase):
    def test_one_supported_component_produces_bounded_partial(self):
        question = (
            "Define computerized clinical decision support and state the exact "
            "percentage by which it prevents diagnostic mistakes."
        )
        payload = {"components": [
            {"component_id": "definition_concept", "status": "directly_supported",
             "supporting_source_ids": ["paper-1"], "supporting_excerpt_ids": ["paper-1:1"],
             "rationale": "explicit definition"},
            {"component_id": "numerical_value", "status": "unsupported",
             "supporting_source_ids": [], "supporting_excerpt_ids": [],
             "rationale": "no percentage"},
        ]}
        gate = rg.assess_evidence_sufficiency(
            question, [source("A clinical decision support system is software assisting decisions.")],
            GateLLM(payload),
        )
        self.assertEqual("partial", gate["decision"])
        self.assertEqual(["definition_concept"], gate["supported_components"])
        self.assertEqual(["numerical_value"], gate["missing_components"])
        contract = rg.build_generation_contract(question, gate, [source()])
        self.assertEqual(["definition_concept"], contract["permitted_answer_scope"])
        self.assertEqual(["numerical_value"], contract["prohibited_answer_scope"])

    def test_all_propositions_unsupported_abstains(self):
        question = "What percentage proves that workflow disruption causes mortality?"
        specification = rg.build_question_specification(question)
        payload = {"components": [
            {"component_id": component["component_id"], "status": "unsupported",
             "supporting_source_ids": [], "supporting_excerpt_ids": [],
             "rationale": "topical evidence is not causal numerical evidence"}
            for component in specification["components"]
        ]}
        gate = rg.assess_evidence_sufficiency(
            question, [source("Clinicians reported workflow disruption.")], GateLLM(payload)
        )
        self.assertEqual("insufficient", gate["decision"])
        self.assertEqual([], gate["supported_components"])

    def test_topical_or_substituted_construct_cannot_pass_by_structure(self):
        question = "Does clinician trust cause safer patient outcomes?"
        component = rg.build_question_specification(question)["components"][0]
        self.assertEqual("causal_contribution", component["component_id"])
        self.assertTrue(component["causal_requirement"])
        payload = {"components": [{
            "component_id": "causal_contribution", "status": "unsupported",
            "supporting_source_ids": [], "supporting_excerpt_ids": [],
            "rationale": "intention to use is not trust and association is not causation",
        }]}
        gate = rg.assess_evidence_sufficiency(
            question, [source("Intention to use was associated with acceptance.")],
            GateLLM(payload),
        )
        self.assertEqual("insufficient", gate["decision"])

    def test_contract_preserves_two_approved_excerpts_from_one_paper(self):
        question = (
            "Define clinical decision support and state the exact percentage "
            "by which it prevents diagnostic errors."
        )
        sources = [
            source("Clinical decision support is software.", excerpt="paper-1:1"),
            source("Diagnostic errors were prevented by 12%.", excerpt="paper-1:2"),
        ]
        payload = {"components": [
            {"component_id": "definition_concept", "status": "directly_supported",
             "supporting_source_ids": ["paper-1"], "supporting_excerpt_ids": ["paper-1:1"],
             "rationale": "explicit definition"},
            {"component_id": "numerical_value", "status": "directly_supported",
             "supporting_source_ids": ["paper-1"], "supporting_excerpt_ids": ["paper-1:2"],
             "rationale": "explicit percentage"},
        ]}
        gate = rg.assess_evidence_sufficiency(question, sources, GateLLM(payload))
        contract = rg.build_generation_contract(question, gate, sources)
        self.assertEqual(
            ["paper-1:1", "paper-1:2"],
            [item["excerpt_id"] for item in contract["resolved_approved_excerpts"]],
        )

    def test_bounded_partial_forces_explicit_gap_statement(self):
        contract = {
            "decision": "partial",
            "permitted_answer_scope": ["definition_concept"],
            "prohibited_answer_scope": ["numerical_value"],
        }
        approved = [source("Clinical decision support is software.")]
        generation = {
            "disposition": "partial",
            "claims": [{
                "claim_id": "cl1", "component_id": "definition_concept",
                "claim_text": "Clinical decision support is software.",
                "excerpt_ids": ["paper-1:1"], "paper_ids": ["paper-1"],
                "evidence_strength": "definition",
            }],
            "unsupported_components": ["numerical_value"],
        }

        class ClaimsLLM:
            def __init__(self):
                self.calls = 0
            def generate_structured(self, *_args, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    return json.dumps(generation)
                return json.dumps({"verdict": "entailed", "rationale": "direct"})

        result = rg.generate_validated_claims(user_query="", contract=contract,
                                              approved_sources=approved, llm=ClaimsLLM())
        self.assertEqual("partial", result["recomputed_disposition"])
        self.assertIn("does not directly support", result["rendered"])
        self.assertIn("numerical_value", result["rendered"])

    def test_bounded_partial_repairs_model_global_abstention(self):
        contract = {
            "decision": "partial",
            "permitted_answer_scope": ["definition_concept"],
            "prohibited_answer_scope": ["numerical_value"],
            "unsupported_proposition_labels": {
                "numerical_value": "the requested exact numerical value or percentage"
            },
        }
        approved = [source("Clinical decision support is software assisting decisions.")]
        responses = [
            {"disposition": "abstain", "claims": [],
             "unsupported_components": ["definition_concept"]},
            {"claims": [{
                "claim_id": "cl1", "component_id": "definition_concept",
                "claim_text": "Clinical decision support is software assisting decisions.",
                "excerpt_ids": ["paper-1:1"], "paper_ids": ["paper-1"],
                "evidence_strength": "definition",
            }]},
            {"verdict": "entailed", "rationale": "direct definition"},
        ]

        class RepairLLM:
            def generate_structured(self, *_args, **_kwargs):
                return json.dumps(responses.pop(0))

        result = rg.generate_validated_claims(
            user_query="Compound request", contract=contract,
            approved_sources=approved, llm=RepairLLM(),
        )
        self.assertEqual("partial", result["recomputed_disposition"])
        self.assertEqual(1, len(result["valid_claims"]))
        self.assertIn("[1]", result["rendered"])
        self.assertIn("exact numerical value or percentage", result["rendered"])
        self.assertTrue(
            rg.validate_citations_and_references(result["rendered"], approved)["valid"]
        )
        self.assertEqual(["numerical_value"],
                         result["contract_unsupported_components"])

    def test_failed_partial_repair_is_explicit_technical_failure(self):
        contract = {
            "decision": "partial",
            "permitted_answer_scope": ["definition_concept"],
            "prohibited_answer_scope": ["numerical_value"],
        }

        class EmptyLLM:
            def generate_structured(self, *_args, **_kwargs):
                return json.dumps({"disposition": "abstain", "claims": [],
                                   "unsupported_components": []})

        result = rg.generate_validated_claims(
            user_query="Compound request", contract=contract,
            approved_sources=[source()], llm=EmptyLLM(),
        )
        self.assertEqual("technical_failure", result["recomputed_disposition"])
        self.assertTrue(result["technical_failure"])
        self.assertIn("could not be rendered", result["rendered"])


if __name__ == "__main__":
    unittest.main()
