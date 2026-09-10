import json, unittest
from llm import rag_generator as rg

def source():
    return {"paperId":"p1","excerpt_id":"p1:1","rank":1,"title":"P","year":2024,
            "text":"A clinical decision support system is software that assists clinical decisions."}

class LLM:
    def __init__(self,*responses): self.responses=iter(responses)
    def generate_structured(self,prompt,system_message=None):
        value=next(self.responses)
        if isinstance(value,Exception): raise value
        return value

class PostRun11ParserTests(unittest.TestCase):
    def ids(self,q): return {c["component_id"] for c in rg.build_question_specification(q)["components"]}
    def test_qualifiers_do_not_become_components(self):
        self.assertEqual({"causal_contribution"},self.ids(
            "What factors cause automation bias in AI-based clinical decision support systems?"))
        self.assertEqual({"direct_relationship"},self.ids(
            "How do clinicians describe workflow barriers in hospitals?"))
    def test_definition_plus_number_is_two_independent_components(self):
        spec=rg.build_question_specification(
            "What is a clinical decision support system, and what percentage does it reduce diagnostic errors?")
        self.assertEqual({"definition_concept","numerical_value"},{c["component_id"] for c in spec["components"]})
        self.assertTrue(all(c["independent"] for c in spec["components"]))
    def test_comparison_is_one_component_with_qualifiers(self):
        spec=rg.build_question_specification("Is AI-CDSS more effective than rule-based CDSS for diagnostic errors?")
        self.assertEqual(1,len(spec["components"]))
        c=spec["components"][0]
        self.assertEqual("quantitative_comparison",c["component_id"])
        self.assertTrue(c["comparator"])
        self.assertTrue(c["outcome"])
    def test_temporal_causal_negation_and_qualification_are_fields(self):
        c=rg.build_question_specification(
            "Does AI-CDSS not cause lower mortality over 30 days in adults?")["components"][0]
        self.assertTrue(c["causal_requirement"]); self.assertTrue(c["time_requirement"])
        self.assertTrue(c["negations"]); self.assertTrue(c["population"])

class PostRun11DispositionTests(unittest.TestCase):
    def payload(self,disposition="abstain"):
        return {"disposition":disposition,"claims":[{"claim_id":"cl1","component_id":"definition_concept",
          "claim_text":"A CDSS is software that assists clinical decisions.","excerpt_ids":["p1:1"],
          "paper_ids":["p1"],"evidence_strength":"definition"}],"unsupported_components":[]}
    def test_declared_abstention_does_not_destroy_valid_claim(self):
        llm=LLM(json.dumps(self.payload("abstain")),json.dumps({"verdict":"entailed","rationale":"direct"}))
        result=rg.generate_validated_claims("What is CDSS?",
          {"decision":"sufficient","permitted_answer_scope":["definition_concept"],"prohibited_answer_scope":[]},
          [source()],llm)
        self.assertEqual("answer",result["recomputed_disposition"])
        self.assertEqual(1,len(result["valid_claims"]))
        self.assertTrue(result["disposition_mismatch"])
    def test_invalid_claim_does_not_remove_valid_independent_claim(self):
        payload=self.payload("answer")
        payload["claims"].append({**payload["claims"][0],"claim_id":"cl2","component_id":"unknown"})
        llm=LLM(json.dumps(payload),json.dumps({"verdict":"entailed","rationale":"direct"}))
        result=rg.generate_validated_claims("Compound?",
          {"decision":"sufficient","permitted_answer_scope":["definition_concept"],"prohibited_answer_scope":[]},
          [source()],llm)
        self.assertEqual(1,len(result["valid_claims"])); self.assertEqual(1,len(result["removed_claims"]))
    def test_supported_and_unsupported_recomputes_partial(self):
        payload=self.payload("answer"); payload["unsupported_components"]=["numerical_value"]
        llm=LLM(json.dumps(payload),json.dumps({"verdict":"entailed","rationale":"direct"}))
        result=rg.generate_validated_claims("Compound?",
          {"decision":"partial","permitted_answer_scope":["definition_concept"],
           "prohibited_answer_scope":["numerical_value"]},[source()],llm)
        self.assertEqual("partial",result["recomputed_disposition"])

if __name__=="__main__": unittest.main()
