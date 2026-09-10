import json
import unittest

from llm.rag_generator import assess_evidence_sufficiency, build_question_specification


class CapturingGate:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    def generate_structured(self, prompt, system_message=None):
        self.prompts.append(prompt)
        return json.dumps(self.response)


def unsupported_response(question, rationale):
    return {
        "components": [
            {"component_id": component["component_id"], "status": "unsupported",
             "supporting_source_ids": [], "supporting_excerpt_ids": [], "rationale": rationale}
            for component in build_question_specification(question)["components"]
        ],
        "concise_rationale": rationale,
    }


def source(text):
    return {
        "paperId": "paper-1",
        "excerpt_id": "paper-1:1",
        "title": "Retrieved paper",
        "text": text,
    }


class ScientificEntailmentGuardrailTests(unittest.TestCase):
    def test_trust_evidence_is_not_accepted_as_automation_bias_causation(self):
        question = "What factors contribute to automation bias in AI-based clinical decision support systems?"
        llm = CapturingGate(unsupported_response(
            question, "The excerpt concerns trust, not causes of automation bias."))
        result = assess_evidence_sufficiency(
            question,
            [source("Trust predicted intention to use an AI-CDSS.")], llm,
        )
        self.assertEqual("insufficient", result["decision"])
        self.assertIn("does not support automation bias", llm.prompts[0])

    def test_association_and_qualitative_evidence_do_not_raise_specificity(self):
        question = "What percentage of errors are caused by clinician trust?"
        llm = CapturingGate(unsupported_response(
            question, "Neither causation nor a percentage is reported."))
        result = assess_evidence_sufficiency(
            question,
            [source("Interviewees described trust as associated with system use.")], llm,
        )
        self.assertEqual("insufficient", result["decision"])
        self.assertIn("does not support causation", llm.prompts[0])
        self.assertIn("do not support an unstated number", llm.prompts[0])

    def test_no_query_or_paper_specific_production_hard_coding(self):
        spec = build_question_specification("What factors contribute to an unfamiliar bias?")
        self.assertIn("causal_contribution", {c["component_id"] for c in spec["components"]})


if __name__ == "__main__":
    unittest.main()
