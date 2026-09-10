import copy
import unittest

from llm import rag_generator as rg


def result(papers):
    return {
        "ids": [[paper["representative"] for paper in papers]],
        "documents": [[paper["chunks"][0]["text"] for paper in papers]],
        "metadatas": [[{
            "paperId": paper["paper"], "title": paper["paper"],
            "candidate_chunks": paper["chunks"],
        } for paper in papers]],
    }


def chunk(cid, paper, text, score=0.5):
    return {"chunk_id": cid, "paperId": paper, "text": text,
            "section": "body", "chunk_score": score}


class PropositionExcerptExposureTests(unittest.TestCase):
    def test_non_representative_definition_is_exposed(self):
        data = result([{"paper": "p", "representative": "p:1", "chunks": [
            chunk("p:1", "p", "Related clinical background.", 0.9),
            chunk("p:2", "p", "Decision support is software designed to aid clinical decisions.", 0.4),
        ]}])
        spec = rg.build_question_specification("What is clinical decision support?")
        selected = rg.select_proposition_excerpts(data, spec)
        self.assertIn("p:2", selected["proposition_to_excerpts"][0]["selected_excerpt_ids"])
        self.assertEqual("p:2", next(x["excerpt_id"] for x in selected["sources"]
                                     if x["excerpt_id"] == "p:2"))

    def test_topical_high_score_does_not_displace_direct_definition(self):
        data = result([{"paper": "p", "representative": "p:1", "chunks": [
            chunk("p:1", "p", "Clinical technology implementation discussion.", 0.99),
            chunk("p:2", "p", "Clinical decision support is software for clinical decisions.", 0.1),
        ]}])
        spec = rg.build_question_specification("Define clinical decision support.")
        selected = rg.select_proposition_excerpts(data, spec)
        self.assertEqual(["p:1", "p:2"],
                         [source["excerpt_id"] for source in selected["sources"]])
        self.assertIn("p:2",
                      selected["proposition_to_excerpts"][0]["selected_excerpt_ids"])

    def test_existing_representative_remains_after_proposition_expansion(self):
        data = result([{"paper": "p", "representative": "p:representative", "chunks": [
            chunk("p:representative", "p", "Existing directly supporting definition."),
            chunk("p:barrier", "p", "Implementation barrier and workflow interruption."),
        ]}])
        selected = rg.select_proposition_excerpts(
            data, rg.build_question_specification("What implementation barriers were reported?")
        )
        self.assertEqual(
            "p:representative", selected["sources"][0]["excerpt_id"]
        )
        self.assertEqual(
            1,
            [source["excerpt_id"] for source in selected["sources"]].count(
                "p:representative"
            ),
        )

    def test_definition_representative_is_not_displaced_by_barrier_excerpts(self):
        data = result([{"paper": "p", "representative": "p:def", "chunks": [
            chunk("p:def", "p", "Clinical decision support is software aiding decisions."),
            chunk("p:b1", "p", "Implementation barriers include workflow interruption."),
            chunk("p:b2", "p", "A further obstacle is duplicated work."),
        ]}])
        selected = rg.select_proposition_excerpts(
            data,
            rg.build_question_specification(
                "What workflow obstacles arise with clinical decision support?"
            ),
        )
        ids = [source["excerpt_id"] for source in selected["sources"]]
        self.assertIn("p:def", ids)
        self.assertLessEqual(len(ids), rg.EXCERPTS_PER_PAPER)

    def test_two_propositions_may_use_two_chunks_same_paper(self):
        data = result([{"paper": "p", "representative": "p:1", "chunks": [
            chunk("p:1", "p", "Clinical decision support is software designed for decisions."),
            chunk("p:2", "p", "Diagnostic errors were prevented by 12%."),
        ]}])
        spec = rg.build_question_specification(
            "Define clinical decision support and state the exact percentage by which it prevents diagnostic errors.")
        selected = rg.select_proposition_excerpts(data, spec)
        mapped = {x["component_id"]: x["selected_excerpt_ids"]
                  for x in selected["proposition_to_excerpts"]}
        self.assertIn("p:1", mapped["definition_concept"])
        self.assertIn("p:2", mapped["numerical_value"])

    def test_equal_scores_have_stable_chunk_id_tie_break(self):
        data = result([{"paper": "p", "representative": "p:b", "chunks": [
            chunk("p:b", "p", "Outcome evidence."),
            chunk("p:a", "p", "Outcome evidence."),
        ]}])
        spec = rg.build_question_specification("What was the outcome?")
        first = rg.select_proposition_excerpts(copy.deepcopy(data), spec)
        second = rg.select_proposition_excerpts(copy.deepcopy(data), spec)
        self.assertEqual(first, second)
        self.assertEqual(["p:a", "p:b"],
                         first["proposition_to_excerpts"][0]["selected_excerpt_ids"])

    def test_limits_are_enforced_and_audited(self):
        papers = []
        for p in range(5):
            papers.append({"paper": f"p{p}", "representative": f"p{p}:0",
                           "chunks": [chunk(f"p{p}:{i}", f"p{p}",
                                            "Outcome evidence with clinical outcome.")
                                      for i in range(5)]})
        spec = rg.build_question_specification("What was the clinical outcome?")
        selected = rg.select_proposition_excerpts(result(papers), spec)
        self.assertLessEqual(len(selected["sources"]), rg.TOTAL_EXCERPT_LIMIT)
        self.assertLessEqual(len(selected["proposition_to_excerpts"][0]["selected_excerpt_ids"]),
                             rg.EXCERPTS_PER_PROPOSITION)
        self.assertTrue(any("limit" in x["reason"] for x in selected["candidate_audit"]))

    def test_no_overlap_is_rejected_with_reason(self):
        data = result([{"paper": "p", "representative": "p:1", "chunks": [
            chunk("p:1", "p", "Earthquake geology tectonic plate."),
        ]}])
        spec = rg.build_question_specification("Define clinical decision support.")
        selected = rg.select_proposition_excerpts(data, spec)
        self.assertEqual(["p:1"], [s["excerpt_id"] for s in selected["sources"]])
        self.assertEqual(
            [],
            selected["proposition_to_excerpts"][0]["selected_excerpt_ids"],
        )
        self.assertTrue(any(
            item["reason"] == "rejected: no proposition overlap"
            for item in selected["candidate_audit"]
        ))

    def test_qualifier_fields_preserve_direction_time_magnitude_context(self):
        component = rg.build_question_specification(
            "Give the exact 30-day survival percentage by which AI decision support "
            "improves outcomes in primary-care studies.")["components"][0]
        self.assertEqual("30 days", component["time_requirement"])
        self.assertEqual("improve", component["outcome_direction"])
        self.assertIn("primary care", component["study_context"])
        self.assertEqual(["numerical"], component["required_evidence_type"])

    def test_selected_paper_order_is_not_changed(self):
        data = result([
            {"paper": "first", "representative": "first:1",
             "chunks": [chunk("first:1", "first", "Clinical outcome evidence.")]},
            {"paper": "second", "representative": "second:1",
             "chunks": [chunk("second:1", "second", "Clinical outcome evidence.")]},
        ])
        before = copy.deepcopy(data["ids"])
        rg.select_proposition_excerpts(data, rg.build_question_specification("What was the clinical outcome?"))
        self.assertEqual(before, data["ids"])


if __name__ == "__main__":
    unittest.main()
