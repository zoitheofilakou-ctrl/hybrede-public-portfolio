import json
import re
import unittest
from unittest.mock import Mock, patch

from llm import rag_generator as rg
from validation.evaluation import run_evaluation_20260727_run7 as run7


class FakeArray:
    def tolist(self):
        return [[0.1, 0.2]]


def make_gate(
    decision="sufficient",
    requested=("outcome",),
    supported=("outcome",),
    missing=(),
    essential_missing=(),
    approved=("paper-a",),
    excerpt_ranks=None,
):
    excerpt_ranks = excerpt_ranks or {source_id: 1 for source_id in approved}
    components = []
    for component_id in requested:
        is_supported = component_id in supported
        source_ids = list(approved) if is_supported else []
        components.append({
            "component_id": component_id,
            "status": "directly_supported" if is_supported else "unsupported",
            "supporting_source_ids": source_ids,
            "supporting_excerpt_ids": [
                f"{source_id}:{excerpt_ranks[source_id]}" for source_id in source_ids
            ],
            "rationale": "direct evidence" if is_supported else "not established",
        })
    return {
        "decision": decision,
        "requested_components": list(requested),
        "supported_components": list(supported),
        "missing_components": list(missing),
        "essential_missing_components": list(essential_missing),
        "concise_rationale": "bounded evidence assessment",
        "supporting_source_ids": list(approved),
        "components": components,
        "raw_output": "{}",
        "diagnostic_category": None,
        "error": None,
    }


class ProductionOrchestration25Tests(unittest.TestCase):
    """Twenty-five independent offline tests of the canonical production path."""

    def _execute(
        self,
        *,
        scenario_id,
        question="What was the outcome?",
        gate=None,
        generated="Supported finding [1].",
        papers=("paper-a",),
    ):
        documents = [[f"Direct evidence from {paper_id}." for paper_id in papers]]
        metadatas = [[{
            "paperId": paper_id,
            "title": f"Paper {paper_id}",
            "year": 2024,
            "url": "https://example.test",
            "text_source": "abstract",
            "section": "abstract",
        } for paper_id in papers]]
        collection = Mock()
        collection.query.return_value = {
            "documents": documents,
            "metadatas": metadatas,
            "embedding_scores": [[0.9 for _ in papers]],
            "cross_encoder_scores": [[0.8 for _ in papers]],
            "retrieval_notes": [[]],
        }
        provider = Mock()
        effective_gate = gate if gate is not None else make_gate()
        supported = effective_gate.get("supported_components") or []
        component_id = supported[0] if supported else "outcome"
        claim_input = generated.split("References", 1)[0]
        citation_numbers = [
            int(n) for group in re.findall(r"\[[\d,\s]+\]", claim_input)
            for n in re.findall(r"\d+", group)
        ]
        excerpt_ids = [
            f"{papers[n-1]}:{n}" for n in citation_numbers
            if 1 <= n <= len(papers)
        ]
        paper_ids = [papers[n-1] for n in citation_numbers if 1 <= n <= len(papers)]
        claims = [] if not citation_numbers else [{
            "claim_id": "cl1", "component_id": component_id,
            "claim_text": re.sub(r"\s*\[\d+\]", "", generated).split("References")[0].strip(),
            "excerpt_ids": excerpt_ids or ["unknown:1"], "paper_ids": paper_ids or ["unknown"],
            "evidence_strength": "descriptive",
        }]
        provider.generate_structured.side_effect = [
            json.dumps({"disposition": "partial" if effective_gate.get("decision") == "partial" else "answer",
                        "claims": claims, "unsupported_components": effective_gate.get("missing_components", [])}),
            json.dumps({"verdict": "entailed", "rationale": "fixture direct evidence"}),
        ]
        query = {"id": scenario_id, "category": "orchestration_test", "query": question}

        with patch.object(rg, "require_retrieval_dependencies"), \
             patch.object(rg.os.path, "exists", return_value=True), \
             patch.object(rg, "get_chroma_collection", return_value=collection), \
             patch.object(
                 rg,
                 "get_embedding_model",
                 return_value=Mock(encode=Mock(return_value=FakeArray())),
             ), \
             patch.object(rg, "get_llm_provider", return_value=provider), \
             patch.object(rg, "assess_evidence_sufficiency", return_value=effective_gate):
            result = rg.evaluate_single_query(question, provider="openai", k=5)

        row = run7.serialize_runtime_row(query, result, "start", "finish")
        jsonl_line = json.dumps(row, ensure_ascii=False)
        decoded = json.loads(jsonl_line)
        markdown = run7.render_markdown_report([decoded])

        self.assertEqual(scenario_id, decoded["id"])
        self.assertEqual(question, decoded["query"])
        self.assertIn(decoded["final_disposition"], markdown)
        self.assertIn("Citation diagnostics", markdown)
        self.assertIn("Quantitative diagnostics", markdown)
        contract = decoded.get("generation_contract")
        if contract is not None:
            self.assertTrue(set(run7.CONTRACT_FIELDS).issubset(contract))
            for field in run7.CONTRACT_FIELDS:
                self.assertIn(f"`{field}`", markdown)
        return decoded, provider

    def test_01_zero_retrieval_bypasses_generation(self):
        row, provider = self._execute(scenario_id="s01", papers=())
        self.assertEqual("evidence_gap", row["final_disposition"])
        self.assertEqual("zero_sources", row["evidence_sufficiency"]["diagnostic_category"])
        self.assertTrue(row["generation_bypassed"])
        provider.generate.assert_not_called()

    def test_02_sufficient_evidence_generates_supported_answer(self):
        row, provider = self._execute(scenario_id="s02")
        self.assertEqual("supported_answer", row["final_disposition"])
        self.assertEqual([1], row["citations"])
        self.assertGreaterEqual(provider.generate_structured.call_count, 2)

    def test_03_partial_evidence_generates_bounded_partial(self):
        gate = make_gate(
            "partial", ("outcome", "context"), ("outcome",), ("context",), (), ("paper-a",)
        )
        row, provider = self._execute(scenario_id="s03", gate=gate)
        self.assertEqual("bounded_partial", row["final_disposition"])
        self.assertEqual(["context"], row["generation_contract"]["prohibited_answer_scope"])
        self.assertGreaterEqual(provider.generate_structured.call_count, 2)

    def test_04_essential_component_missing_bypasses_generation(self):
        gate = make_gate(
            "insufficient", ("outcome", "temporal_horizon"), (), ("outcome", "temporal_horizon"),
            ("outcome", "temporal_horizon"), ()
        )
        row, provider = self._execute(scenario_id="s04", gate=gate)
        self.assertEqual("evidence_gap", row["final_disposition"])
        self.assertTrue(row["generation_bypassed"])
        provider.generate.assert_not_called()

    def test_05_no_supported_components_bypasses_generation(self):
        gate = make_gate("insufficient", ("outcome",), (), ("outcome",), ("outcome",), ())
        row, provider = self._execute(scenario_id="s05", gate=gate)
        self.assertEqual([], row["citations"])
        self.assertEqual([], row["references"])
        provider.generate.assert_not_called()

    def test_06_valid_single_citation_is_serialized(self):
        row, _ = self._execute(scenario_id="s06", generated="Bounded claim [1].")
        self.assertTrue(row["citation_validation"]["valid"])
        self.assertEqual("paper-a", row["references"][0]["paperId"])

    def test_07_valid_repeated_citation_is_deduplicated(self):
        row, _ = self._execute(scenario_id="s07", generated="First [1]. Second [1].")
        self.assertEqual([1], row["citations"])
        self.assertEqual(1, len(row["references"]))

    def test_08_valid_multi_source_citations_are_serialized(self):
        gate = make_gate(
            approved=("paper-a", "paper-b"),
            excerpt_ranks={"paper-a": 1, "paper-b": 2},
        )
        row, _ = self._execute(
            scenario_id="s08", gate=gate, generated="Combined finding [1, 2].",
            papers=("paper-a", "paper-b")
        )
        self.assertEqual([1, 2], row["citations"])
        self.assertEqual(["paper-a", "paper-b"], [ref["paperId"] for ref in row["references"]])

    def test_09_unknown_citation_fails_closed(self):
        row, _ = self._execute(scenario_id="s09", generated="Fabricated claim [2].")
        self.assertEqual("evidence_gap", row["final_disposition"])
        self.assertEqual("excerpt_paper_identity_failure",
                         row["structured_claim_validation"]["removed_claims"][0]["removal_reason"])

    def test_10_malformed_citation_fails_closed(self):
        row, _ = self._execute(scenario_id="s10", generated="Malformed claim [paper-a].")
        self.assertEqual("evidence_gap", row["final_disposition"])
        self.assertEqual([], row["structured_claim_validation"]["valid_claims"])
        self.assertEqual([], row["references"])

    def test_11_missing_citation_fails_closed(self):
        row, _ = self._execute(scenario_id="s11", generated="Uncited substantive claim.")
        self.assertEqual("evidence_gap", row["final_disposition"])
        self.assertEqual([], row["structured_claim_validation"]["valid_claims"])

    def test_12_unknown_reference_entry_fails_closed(self):
        row, _ = self._execute(
            scenario_id="s12",
            generated="Supported [1].\n\nReferences\n[2] Fabricated",
        )
        self.assertEqual("supported_answer", row["final_disposition"])
        self.assertNotIn("Fabricated", row["answer"])

    def test_13_uncited_reference_entry_fails_closed(self):
        gate = make_gate(
            approved=("paper-a", "paper-b"),
            excerpt_ranks={"paper-a": 1, "paper-b": 2},
        )
        row, _ = self._execute(
            scenario_id="s13", gate=gate,
            generated="Supported [1].\n\nReferences\n[1] A\n[2] B",
            papers=("paper-a", "paper-b"),
        )
        self.assertEqual([1], row["citations"])
        self.assertNotIn("\n[2] B", row["answer"])

    def test_14_placeholder_citation_is_rejected_before_normalization(self):
        row, _ = self._execute(scenario_id="s14", generated="Claim [Paper 1].")
        self.assertEqual("evidence_gap", row["final_disposition"])
        self.assertEqual([], row["structured_claim_validation"]["valid_claims"])

    def test_15_unapproved_numeric_percentage_fails_closed(self):
        row, _ = self._execute(scenario_id="s15", generated="The outcome was 30% [1].")
        self.assertEqual("evidence_gap", row["final_disposition"])
        self.assertFalse(row["quantitative_validation"]["valid"])

    def test_16_unapproved_numeric_count_fails_closed(self):
        row, _ = self._execute(scenario_id="s16", generated="There were 45 cases [1].")
        self.assertEqual("unapproved_quantitative_claim",
                         row["quantitative_validation"]["diagnostic_category"])
        self.assertEqual([], row["references"])

    def test_17_nonquantitative_answer_passes_quantitative_validation(self):
        row, _ = self._execute(scenario_id="s17", generated="A qualitative finding was reported [1].")
        self.assertTrue(row["quantitative_validation"]["valid"])
        self.assertEqual([], row["quantitative_validation"]["detected_values"])

    def test_18_unresolved_gate_source_fails_contract_closed(self):
        gate = make_gate(approved=("paper-missing",))
        row, provider = self._execute(scenario_id="s18", gate=gate)
        self.assertEqual("evidence_gap", row["final_disposition"])
        self.assertIsNone(row["generation_contract"])
        provider.generate.assert_not_called()

    def test_19_only_gate_approved_source_reaches_generation(self):
        gate = make_gate(approved=("paper-b",), excerpt_ranks={"paper-b": 2})
        row, _ = self._execute(
            scenario_id="s19", gate=gate, generated="Approved evidence [2].",
            papers=("paper-a", "paper-b"),
        )
        self.assertEqual(["paper-b"], [source["paperId"] for source in row["sources"]])
        self.assertNotIn("paper-a", json.dumps(row["generation_contract"]))

    def test_20_retrieval_scores_are_excluded_from_contract(self):
        row, _ = self._execute(scenario_id="s20")
        serialized = json.dumps(row["generation_contract"])
        self.assertNotIn("semantic_similarity", serialized)
        self.assertNotIn("cross_encoder_score", serialized)

    def test_21_retrieval_trace_is_preserved_in_runtime_row(self):
        row, _ = self._execute(scenario_id="s21")
        self.assertEqual([[0.9]], row["retrieval"]["embedding_scores"])
        self.assertEqual([[0.8]], row["retrieval"]["cross_encoder_scores"])

    def test_22_partial_contract_preserves_supported_and_missing_scope(self):
        gate = make_gate(
            "partial", ("outcome", "comparator"), ("outcome",), ("comparator",), (),
            ("paper-a",)
        )
        row, _ = self._execute(scenario_id="s22", gate=gate)
        contract = row["generation_contract"]
        self.assertEqual(["outcome"], contract["permitted_answer_scope"])
        self.assertEqual(["comparator"], contract["prohibited_answer_scope"])

    def test_23_generation_output_with_fabricated_paper_id_fails_closed(self):
        row, _ = self._execute(scenario_id="s23", generated="Claim [paper-z].")
        self.assertEqual("evidence_gap", row["final_disposition"])
        self.assertEqual([], row["citations"])

    def test_24_canonical_reference_block_survives_jsonl_and_markdown(self):
        row, _ = self._execute(scenario_id="s24", generated="Supported finding [1].")
        self.assertIn("References", row["answer"])
        self.assertIn("[1] Paper paper-a (2024)", row["answer"])
        self.assertIn('"paperId": "paper-a"', run7.render_markdown_report([row]))

    def test_25_question_and_contract_identity_survive_serialization(self):
        question = "What outcome was reported for nurses in hospitals?"
        gate = make_gate(
            "sufficient", ("population", "context", "outcome"),
            ("population", "context", "outcome"), (), (), ("paper-a",)
        )
        row, _ = self._execute(scenario_id="s25", question=question, gate=gate)
        self.assertEqual(question, row["generation_contract"]["original_question"])
        self.assertEqual(
            ["population", "context", "outcome"],
            row["generation_contract"]["requested_components"],
        )


if __name__ == "__main__":
    unittest.main()
