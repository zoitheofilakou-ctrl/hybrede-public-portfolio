import json
import os
import tempfile
import unittest
from unittest.mock import Mock

from validation.evaluation import run_evaluation_20260727_run7 as run7
from llm import rag_generator


def complete_result(question):
    contract = {
        "original_question": question, "requested_components": ["outcome"],
        "supported_components": ["outcome"], "missing_components": [],
        "essential_missing_components": [], "decision": "sufficient",
        "decision_reason": "direct", "approved_sources_by_component": {"outcome": ["paper-a"]},
        "resolved_approved_excerpts": [{"paperId": "paper-a", "excerpt_id": "paper-a:1", "text": "evidence"}],
        "permitted_answer_scope": ["outcome"], "prohibited_answer_scope": [],
        "approved_quantitative_claims": [],
    }
    return {
        "answer": "Supported [1].", "generation_contract": contract,
        "evidence_sufficiency": {"raw_output": "{}", "diagnostic_category": None, "error": None},
        "quantitative_validation": {"valid": True}, "citation_validation": {"valid": True},
        "citations": [1], "references": [{"number": 1, "paperId": "paper-a"}],
        "final_disposition": "supported_answer",
    }


class Run7ProductionPathTests(unittest.TestCase):
    def test_runner_default_is_canonical_evaluate_single_query(self):
        self.assertIs(run7.evaluate_single_query, rag_generator.evaluate_single_query)
        self.assertIs(run7.run.__defaults__[-1], rag_generator.evaluate_single_query)

    def test_runtime_jsonl_and_markdown_preserve_complete_contract(self):
        query = {"id": "q1", "category": "in_domain", "query": "Outcome?"}
        row = run7.serialize_runtime_row(query, complete_result(query["query"]), "start", "finish")
        decoded = json.loads(json.dumps(row))
        for field in run7.CONTRACT_FIELDS:
            self.assertIn(field, decoded["generation_contract"])
        markdown = run7.render_markdown_report([row])
        for field in run7.CONTRACT_FIELDS:
            self.assertIn(f"`{field}`", markdown)
        self.assertIn("Citation diagnostics", markdown)
        self.assertIn("Quantitative diagnostics", markdown)

    def test_overwrite_refusal_precedes_evaluation_and_writing(self):
        evaluator = Mock()
        with tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "results.jsonl")
            report = os.path.join(temp_dir, "report.md")
            with open(output, "w", encoding="utf-8") as handle:
                handle.write("sentinel")
            with self.assertRaises(FileExistsError):
                run7.run(run7.Q, output, report, evaluator)
            evaluator.assert_not_called()
            with open(output, encoding="utf-8") as handle:
                self.assertEqual("sentinel", handle.read())
            self.assertFalse(os.path.exists(report))

    def test_run7_uses_injected_canonical_evaluator_and_writes_test_targets(self):
        evaluator = Mock(side_effect=lambda question, provider, k: complete_result(question))
        with tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "results.jsonl")
            report = os.path.join(temp_dir, "report.md")
            rows = run7.run(run7.Q, output, report, evaluator)
            self.assertEqual(11, len(rows))
            self.assertEqual(11, evaluator.call_count)
            self.assertTrue(os.path.exists(output))
            self.assertTrue(os.path.exists(report))
            with open(output, encoding="utf-8") as handle:
                decoded = [json.loads(line) for line in handle]
            self.assertEqual(11, len(decoded))
            self.assertIn("generation_contract", decoded[0])


if __name__ == "__main__":
    unittest.main()
