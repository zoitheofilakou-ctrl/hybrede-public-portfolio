import unittest
import tempfile
from pathlib import Path

from immutable_index import (
    assert_source_unchanged,
    create_verified_runtime_copy,
    tree_hash,
)
from llm.rag_generator import build_question_specification


class DefinitionIntentRegressionTests(unittest.TestCase):
    def assert_definition(self, question):
        spec = build_question_specification(question)
        self.assertEqual("definition", spec["components"][0]["request_type"])
        self.assertEqual("definition_concept", spec["components"][0]["component_id"])

    def test_definition_variants(self):
        for question in (
            "How is automation bias defined?",
            "How is automation bias defined in healthcare studies?",
            "What does automation bias mean?",
            "What is meant by alert fatigue?",
            "How do studies define clinical decision support?",
            "How is clinical decision support conceptualized?",
            "How is automation bias operationalized?",
            "What definition of alert fatigue is used?",
        ):
            with self.subTest(question=question):
                self.assert_definition(question)

    def test_definition_preserves_population_and_context(self):
        spec = build_question_specification(
            "How is automation bias among clinicians in healthcare defined?"
        )
        component = spec["components"][0]
        self.assertIn("clinicians", component["population"])
        self.assertIn("healthcare", component["context"])


class ImmutableRuntimeCopyTests(unittest.TestCase):
    def test_fresh_copy_is_verified_and_source_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "chroma.sqlite3").write_bytes(b"scientific input")
            expected = tree_hash(source)
            runtime = root / "runtime"
            report = create_verified_runtime_copy(source, runtime)
            self.assertTrue(report["verified"])
            self.assertNotEqual(report["source"], report["runtime"])
            (runtime / "chroma.sqlite3").write_bytes(b"operational mutation")
            assert_source_unchanged(source, expected)

    def test_source_path_and_existing_runtime_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source"
            source.mkdir()
            with self.assertRaises(ValueError):
                create_verified_runtime_copy(source, source)
            runtime = Path(temp) / "runtime"
            runtime.mkdir()
            with self.assertRaises(FileExistsError):
                create_verified_runtime_copy(source, runtime)

    def test_source_mutation_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source"
            source.mkdir()
            item = source / "chroma.sqlite3"
            item.write_bytes(b"before")
            expected = tree_hash(source)
            item.write_bytes(b"after")
            with self.assertRaises(RuntimeError):
                assert_source_unchanged(source, expected)

    def test_definition_plus_numerical_request_is_compound(self):
        spec = build_question_specification(
            "What is alert fatigue, and what percentage of clinicians report it?"
        )
        self.assertEqual(
            {"definition_concept", "numerical_value"},
            {component["component_id"] for component in spec["components"]},
        )

    def test_non_definition_intents_remain_strong(self):
        cases = {
            "What is the association between trust and adoption?": "association",
            "Does alert fatigue cause diagnostic errors?": "causal",
            "Is AI-CDSS better than rule-based CDSS?": "comparison",
            "How does a construct that is defined as alert fatigue affect nurses?": "association",
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                request_types = {
                    component["request_type"]
                    for component in build_question_specification(question)["components"]
                }
                self.assertIn(expected, request_types)

    def test_barrier_request_has_typed_component(self):
        component = build_question_specification(
            "Which workflow barriers do clinicians report when implementing CDSS?"
        )["components"][0]
        self.assertEqual("direct_relationship", component["component_id"])
        self.assertEqual("barrier_identification", component["request_type"])
        self.assertIn("clinicians", component["population"])


if __name__ == "__main__":
    unittest.main()
