import json
import os
import tempfile
import unittest
from unittest.mock import Mock

from llm import rag_generator
from validation.evaluation import run_evaluation_20260727_run8 as run8


def complete_result(question):
    contract = {
        "original_question": question,
        "requested_components": ["outcome"],
        "supported_components": ["outcome"],
        "missing_components": [],
        "essential_missing_components": [],
        "decision": "sufficient",
        "decision_reason": "direct",
        "approved_sources_by_component": {"outcome": ["paper-a"]},
        "resolved_approved_excerpts": [
            {
                "paperId": "paper-a",
                "excerpt_id": "paper-a:1",
                "text": "evidence",
            }
        ],
        "permitted_answer_scope": ["outcome"],
        "prohibited_answer_scope": [],
        "approved_quantitative_claims": [],
    }
    return {
        "answer": "Supported [1].",
        "generation_contract": contract,
        "evidence_sufficiency": {
            "raw_output": "{}",
            "initial_raw_output": "{}",
            "initial_diagnostic_category": None,
            "initial_error": None,
            "repair_attempted": False,
            "repair_raw_output": "",
            "diagnostic_category": None,
            "error": None,
        },
        "quantitative_validation": {"valid": True},
        "citation_validation": {"valid": True},
        "citations": [1],
        "references": [{"number": 1, "paperId": "paper-a"}],
        "final_disposition": "supported_answer",
    }


class Run8ProductionPathTests(unittest.TestCase):
    def test_runner_uses_canonical_evaluator_and_frozen_inputs(self):
        self.assertIs(run8.evaluate_single_query, rag_generator.evaluate_single_query)
        self.assertIs(run8.run.__defaults__[-1], rag_generator.evaluate_single_query)
        queries = run8.load_frozen_queries()
        self.assertEqual(list(run8.EXPECTED_QUERY_IDS), [q["id"] for q in queries])

    def test_overwrite_refusal_precedes_evaluation(self):
        evaluator = Mock()
        with tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "results.jsonl")
            report = os.path.join(temp_dir, "report.md")
            with open(output, "w", encoding="utf-8") as handle:
                handle.write("sentinel")
            with self.assertRaises(FileExistsError):
                run8.run(run8.Q, output, report, evaluator)
            evaluator.assert_not_called()

    def test_run8_serializes_11_rows_and_repair_diagnostics(self):
        evaluator = Mock(
            side_effect=lambda question, provider, k: complete_result(question)
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "results.jsonl")
            report = os.path.join(temp_dir, "report.md")
            rows = run8.run(run8.Q, output, report, evaluator)
            self.assertEqual(11, len(rows))
            self.assertEqual(11, evaluator.call_count)
            with open(output, encoding="utf-8") as handle:
                decoded = [json.loads(line) for line in handle]
            self.assertEqual(11, len(decoded))
            with open(report, encoding="utf-8") as handle:
                markdown = handle.read()
            self.assertIn("Repair attempted", markdown)
            self.assertIn("Initial raw gate output", markdown)


if __name__ == "__main__":
    unittest.main()
