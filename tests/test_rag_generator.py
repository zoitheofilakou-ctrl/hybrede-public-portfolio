import unittest
from unittest.mock import Mock, patch

from llm import rag_generator


class FakeArray:
    def __init__(self, payload):
        self._payload = payload

    def tolist(self):
        return self._payload


class RagGeneratorTests(unittest.TestCase):
    def test_gate_normalizes_supported_alias_and_infers_excerpt_ids(self):
        llm = Mock()
        llm.generate_structured.return_value = (
            '{"components":[{"component_id":"definition_concept","status":"supported",'
            '"supporting_source_ids":["paper-a"],"rationale":"Definition is explicit."}]}'
        )
        result = rag_generator.assess_evidence_sufficiency(
            "What is the concept?", [{"paperId": "paper-a", "text": "A direct definition."}], llm
        )
        self.assertEqual("sufficient", result["decision"])
        self.assertEqual("directly_supported", result["components"][0]["status"])
        self.assertEqual(["paper-a:1"], result["components"][0]["supporting_excerpt_ids"])
        self.assertEqual("Definition is explicit.", result["concise_rationale"])

    def test_question_specification_keeps_contextual_entities_nonessential(self):
        spec = rag_generator.build_question_specification(
            "What factors contribute to automation bias in AI-based clinical decision support systems?"
        )
        components = {item["component_id"]: item for item in spec["components"]}
        self.assertTrue(components["causal_contribution"]["essential"])
        self.assertTrue(components["causal_contribution"]["context"])
        self.assertTrue(components["causal_contribution"]["intervention_or_exposure"])

    def test_sufficiency_gate_accepts_valid_structured_output(self):
        llm = Mock()
        llm.generate_structured.return_value = '{"components":[{"component_id":"direct_relationship","status":"directly_supported","supporting_source_ids":["paper-a"],"supporting_excerpt_ids":["paper-a:1"],"rationale":"Direct result reported."}],"concise_rationale":"Direct result reported."}'
        result = rag_generator.assess_evidence_sufficiency("What was the outcome?", [{"paperId": "paper-a", "title": "A", "text": "Outcome improved."}], llm)
        self.assertEqual("sufficient", result["decision"])

    def test_sufficiency_gate_fails_closed_for_malformed_or_unknown_sources(self):
        llm = Mock()
        llm.generate_structured.return_value = '{"components":[{"component_id":"outcome","status":"directly_supported","supporting_source_ids":["missing"],"supporting_excerpt_ids":["paper-a:1"],"rationale":"ok"}],"concise_rationale":"ok"}'
        result = rag_generator.assess_evidence_sufficiency("What was the outcome?", [{"paperId": "paper-a", "text": "Related topic."}], llm)
        self.assertEqual("insufficient", result["decision"])
        self.assertIsNotNone(result["error"])

    def test_sufficiency_gate_preserves_partial_evidence(self):
        llm = Mock()
        llm.generate_structured.return_value = '{"components":[{"component_id":"quantitative_comparison","status":"unsupported","supporting_source_ids":[],"supporting_excerpt_ids":[],"rationale":"Missing comparator."}],"concise_rationale":"Comparison unsupported."}'
        result = rag_generator.assess_evidence_sufficiency("How effective was the intervention compared to B?", [{"paperId": "paper-a", "text": "A improved outcomes."}], llm)
        self.assertEqual("insufficient", result["decision"])
        self.assertEqual(["quantitative_comparison"], result["missing_components"])

    def test_sufficiency_gate_preserves_empty_response_diagnostic(self):
        llm = Mock()
        llm.generate_structured.return_value = ""
        result = rag_generator.assess_evidence_sufficiency("What was the outcome?", [{"paperId": "paper-a", "text": "Evidence."}], llm)
        self.assertEqual("insufficient", result["decision"])
        self.assertEqual("empty_content", result["diagnostic_category"])

    def test_definition_gate_does_not_require_unrequested_components(self):
        llm = Mock(); llm.generate_structured.return_value = '{"components":[{"component_id":"definition_concept","status":"directly_supported","supporting_source_ids":["paper-a"],"supporting_excerpt_ids":["paper-a:1"],"rationale":"Definition is explicit."}],"concise_rationale":"Definition is explicit."}'
        result = rag_generator.assess_evidence_sufficiency("What is the concept?", [{"paperId":"paper-a","text":"The concept is defined here."}], llm)
        self.assertEqual("sufficient", result["decision"])
        self.assertEqual(["definition_concept"], result["requested_components"])

    def test_gate_rejects_empty_requested_components(self):
        llm = Mock(); llm.generate_structured.return_value = '{"components":[],"concise_rationale":"none"}'
        result = rag_generator.assess_evidence_sufficiency("What is the concept?", [{"paperId":"paper-a","text":"Related."}], llm)
        self.assertEqual("insufficient", result["decision"])
        self.assertIn("components", result["error"])

    def test_gate_rejects_inconsistent_partial(self):
        llm = Mock(); llm.generate_structured.return_value = '{"decision":"partial","requested_components":["outcome"],"supported_components":["outcome"],"missing_components":[],"concise_rationale":"ok","supporting_source_ids":["paper-a"]}'
        result = rag_generator.assess_evidence_sufficiency("What was the outcome?", [{"paperId":"paper-a","text":"Outcome."}], llm)
        self.assertEqual("insufficient", result["decision"])

    def test_gate_preserves_invalid_raw_output(self):
        llm = Mock(); llm.generate_structured.return_value = '{not json'
        result = rag_generator.assess_evidence_sufficiency("What was the outcome?", [{"paperId":"paper-a","text":"Evidence."}], llm)
        self.assertEqual("{not json", result["raw_output"])
        self.assertEqual("invalid_json", result["diagnostic_category"])
        self.assertTrue(result["repair_attempted"])
        self.assertEqual(2, llm.generate_structured.call_count)

    def test_gate_repairs_one_invalid_json_response_and_records_diagnostics(self):
        llm = Mock()
        llm.generate_structured.side_effect = [
            "{not json",
            '{"components":[{"component_id":"direct_relationship","status":"directly_supported",'
            '"supporting_source_ids":["paper-a"],"supporting_excerpt_ids":["paper-a:1"],'
            '"rationale":"Direct result."}],"concise_rationale":"Direct result."}',
        ]
        result = rag_generator.assess_evidence_sufficiency(
            "What was the outcome?", [{"paperId":"paper-a","text":"Outcome improved."}], llm
        )
        self.assertEqual("sufficient", result["decision"])
        self.assertEqual("repaired_schema_output", result["diagnostic_category"])
        self.assertEqual("{not json", result["initial_raw_output"])
        self.assertTrue(result["repair_attempted"])
        self.assertIn('"components"', result["repair_raw_output"])
        self.assertEqual(2, llm.generate_structured.call_count)

    def test_generate_rag_answer_returns_insufficient_evidence_without_calling_llm(self):
        fake_collection = Mock()
        fake_collection.query.return_value = {
            "documents": [[]],
            "metadatas": [[]],
            "final_scores": [[]],
            "retrieval_notes": [["all candidates filtered by min_score"]],
        }
        fake_model = Mock()
        fake_model.encode.return_value = FakeArray([[0.1, 0.2]])

        with patch("llm.rag_generator.require_retrieval_dependencies"):
            with patch("llm.rag_generator.os.path.exists", return_value=True):
                with patch("llm.rag_generator.get_chroma_collection", return_value=fake_collection):
                    with patch("llm.rag_generator.get_embedding_model", return_value=fake_model):
                        with patch("llm.rag_generator.get_llm_provider") as get_llm_provider:
                            result = rag_generator.generate_rag_answer(
                                "blockchain in finance",
                                provider="ollama",
                            )

        self.assertEqual(rag_generator.INSUFFICIENT_EVIDENCE_MESSAGE, result["answer"])
        self.assertEqual([], result["sources"])
        self.assertTrue(result["insufficient_evidence"])
        get_llm_provider.assert_not_called()

    def test_normalize_text_answer_replaces_placeholder_citations(self):
        sources = [
            {"paperId": "paper-a", "title": "Paper A", "year": 2024},
            {"paperId": "paper-b", "title": "Paper B", "year": 2023},
        ]

        answer = rag_generator._normalize_text_answer(
            "Key finding one [Paper 1]. Comparative point [Papers 1 & 2].",
            sources,
        )

        self.assertIn("[1]", answer)
        self.assertIn("[1, 2]", answer)

    def test_normalize_text_answer_appends_real_source_index_when_missing(self):
        sources = [{"paperId": "paper-a", "title": "Paper A", "year": 2024}]

        answer = rag_generator._normalize_text_answer("Ungrounded-looking answer text.", sources)

        self.assertIn("References", answer)
        self.assertIn("[?] Paper A (2024)", answer)

    def test_build_context_and_sources_propagates_retrieval_score_breakdown(self):
        context_text, sources = rag_generator._build_context_and_sources(
            {
                "documents": [["Evidence excerpt."]],
                "metadatas": [[{
                    "paperId": "paper-a",
                    "title": "Paper A",
                    "url": "https://example.org/paper-a",
                    "year": 2024,
                    "text_source": "fulltext",
                    "section": "results",
                    "supporting_chunks": 2,
                }]],
                "embedding_scores": [[0.91]],
                "bm25_scores": [[6.0]],
                "hybrid_scores": [[0.84]],
                "paper_scores": [[0.88]],
                "cross_encoder_scores": [[0.42]],
                "mmr_scores": [[0.93]],
                "final_scores": [[0.93]],
            }
        )

        self.assertNotIn("final_score", context_text)
        self.assertNotIn("final_score", sources[0])
        self.assertNotIn("retrieval_scores", sources[0])
        self.assertNotIn("retrieval_scores", sources[0])


if __name__ == "__main__":
    unittest.main()
