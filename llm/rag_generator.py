import argparse
import copy
import json
import os
import re
import sys

# Add project root to path so sibling packages can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from console_utils import dump_json_console
from Retrieval.retrieval import (
    CHROMA_DIR,
    get_chroma_collection,
    get_embedding_model,
    require_retrieval_dependencies,
)
from llm.interface import get_llm_provider

INSUFFICIENT_EVIDENCE_MESSAGE = "Insufficient evidence in the retrieved corpus to answer this question."
PLACEHOLDER_CITATION_RE = re.compile(r"([\[(])\s*Papers?\s+([0-9,\sand&]+)\s*([\])])", re.IGNORECASE)
RETRIEVAL_SCORE_FIELDS = (
    "embedding_score",
    "cross_encoder_score",
)

COMPONENT_IDS = {"definition_concept", "population", "context", "intervention_exposure",
                 "comparator", "outcome", "instrument_measure", "numerical_value",
                 "temporal_horizon", "direct_relationship", "causal_contribution",
                 "quantitative_comparison"}

EXCERPTS_PER_PROPOSITION = 2
EXCERPTS_PER_PAPER = 3
TOTAL_EXCERPT_LIMIT = 8


def _evidence_tokens(value):
    """Return stable content tokens used only for within-selected-paper ordering."""
    text = " ".join(value) if isinstance(value, list) else str(value or "")
    stop = {"the", "a", "an", "and", "or", "to", "of", "in", "for", "with",
            "what", "how", "is", "are", "by", "when", "state", "give", "exact"}
    return {token for token in re.findall(r"[a-z0-9]+", text.lower())
            if len(token) > 2 and token not in stop}


def select_proposition_excerpts(retrieval_result: dict, specification: dict) -> dict:
    """Select auditable evidence excerpts without changing selected papers/ranking.

    At most two excerpts may complement one proposition, at most three may come
    from one selected paper, and the total context is capped at eight.  These
    limits bound context growth while allowing a definition and a result/qualifier
    excerpt to coexist. Equal scores are resolved by paper rank then chunk id.
    """
    ids = (retrieval_result.get("ids") or [[]])[0]
    docs = (retrieval_result.get("documents") or [[]])[0]
    metas = (retrieval_result.get("metadatas") or [[]])[0]
    if len(ids) > TOTAL_EXCERPT_LIMIT:
        raise ValueError("selected-paper count exceeds the bounded excerpt budget")
    candidates = []
    representatives = []
    for paper_rank, paper_id in enumerate(ids, start=1):
        meta = metas[paper_rank - 1] if paper_rank <= len(metas) else {}
        paper = meta.get("paperId")
        representative = {
            "chunk_id": paper_id, "paperId": paper,
            "text": docs[paper_rank - 1] if paper_rank <= len(docs) else "",
            "section": meta.get("section", "body"), "chunk_score": 0.0,
            "paper_rank": paper_rank, "paper_title": meta.get("title"),
            "year": meta.get("year"), "url": meta.get("url"),
            "representative": True,
        }
        representatives.append(representative)
        rows = meta.get("candidate_chunks") or [representative]
        seen_in_paper = set()
        for row in rows:
            chunk_id = row.get("chunk_id")
            if not chunk_id or chunk_id in seen_in_paper:
                continue
            seen_in_paper.add(chunk_id)
            candidates.append({
                **row, "paper_rank": paper_rank, "paper_title": meta.get("title"),
                "year": meta.get("year"), "url": meta.get("url"),
                "representative": chunk_id == paper_id,
            })
        if paper_id not in seen_in_paper:
            candidates.append(representative)

    def exposed_item(row):
        return {
            "rank": 0, "paperId": row.get("paperId"),
            "excerpt_id": row["chunk_id"], "title": row.get("paper_title"),
            "year": row.get("year"), "url": row.get("url"),
            "text": row.get("text", ""), "section": row.get("section", "body"),
            "paper_rank": row["paper_rank"],
        }

    selected = [exposed_item(row) for row in representatives]
    selected_ids = {row["chunk_id"] for row in representatives}
    per_paper = {}
    for row in representatives:
        per_paper[row.get("paperId")] = per_paper.get(row.get("paperId"), 0) + 1
    mappings, audit = [], [
        {"component_id": None, "chunk_id": row["chunk_id"], "included": True,
         "reason": "selected: existing representative excerpt"}
        for row in representatives
    ]
    for component in specification.get("components", []):
        cid = component["component_id"]
        query_tokens = set()
        for key in ("requirement", "target_construct", "population", "context",
                    "intervention_or_exposure", "comparator", "outcome",
                    "time_requirement", "numerical_requirement", "required_evidence_type"):
            query_tokens |= _evidence_tokens(component.get(key))
        request_type = component.get("request_type")
        ranked = []
        for row in candidates:
            text_tokens = _evidence_tokens(row.get("text"))
            overlap = len(query_tokens & text_tokens)
            lower = row.get("text", "").lower()
            type_bonus = 0
            if request_type == "definition" and any(x in lower for x in (" defined as ", " refers to ", " are software ", " is software ")):
                type_bonus = 4
            elif request_type == "barrier_identification" and any(x in lower for x in (" barrier", " hinder", " obstacle", " interruption", " duplication", " resistance")):
                type_bonus = 4
            elif request_type == "numerical" and re.search(r"\b\d+(?:\.\d+)?\s*%", lower):
                type_bonus = 4
            score = overlap + type_bonus
            ranked.append((score, row))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]["paper_rank"],
                                      -float(pair[1].get("chunk_score") or 0.0),
                                      pair[1]["chunk_id"]))
        component_selected = []
        for score, row in ranked:
            reason = "selected: proposition relevance"
            if score <= 0:
                audit.append({"component_id": cid, "chunk_id": row["chunk_id"],
                              "included": False, "reason": "rejected: no proposition overlap"})
                continue
            if row["chunk_id"] in selected_ids:
                if score > 0 and len(component_selected) < EXCERPTS_PER_PROPOSITION:
                    component_selected.append(row["chunk_id"])
                continue
            if len(component_selected) >= EXCERPTS_PER_PROPOSITION:
                audit.append({"component_id": cid, "chunk_id": row["chunk_id"],
                              "included": False, "reason": "rejected: per-proposition limit"})
                continue
            if per_paper.get(row.get("paperId"), 0) >= EXCERPTS_PER_PAPER:
                audit.append({"component_id": cid, "chunk_id": row["chunk_id"],
                              "included": False, "reason": "rejected: per-paper limit"})
                continue
            if len(selected) >= TOTAL_EXCERPT_LIMIT:
                audit.append({"component_id": cid, "chunk_id": row["chunk_id"],
                              "included": False, "reason": "rejected: total-context limit"})
                continue
            item = exposed_item(row)
            selected.append(item); selected_ids.add(row["chunk_id"])
            per_paper[row.get("paperId")] = per_paper.get(row.get("paperId"), 0) + 1
            component_selected.append(row["chunk_id"])
            audit.append({"component_id": cid, "chunk_id": row["chunk_id"],
                          "included": True, "reason": reason, "relevance_score": score})
        mappings.append({"component_id": cid, "selected_excerpt_ids": component_selected})
    for rank, item in enumerate(selected, start=1):
        item["rank"] = rank
    return {"sources": selected, "proposition_to_excerpts": mappings,
            "candidate_audit": audit, "limits": {
                "per_proposition": EXCERPTS_PER_PROPOSITION,
                "per_paper": EXCERPTS_PER_PAPER, "total": TOTAL_EXCERPT_LIMIT}}


def build_question_specification(question: str) -> dict:
    """Parse requested propositions; semantic nouns are qualifier fields."""
    q = question.strip().lower()
    if not q:
        raise ValueError("question must not be empty")
    q_match = re.sub(r"[-\u2010-\u2015]", " ", q)
    components = []
    quantitative = any(x in q_match for x in ("percentage", "percent", "by how much", "how many", "what proportion", " rate"))
    comparative = any(x in q_match for x in ("more than", "better than", "effective than", "more effective", "compared", "versus", " vs ", "difference between"))
    causal = any(x in q_match for x in (
        "what factors", "contribute", "cause", "causal", "lead to", "result in",
        "attributable", "prove that", "raised", "increase", "decrease",
    ))
    barrier = any(x in q_match for x in ("barrier", "obstacle", "implementation challenge", "workflow challenge"))
    relationship = any(x in q_match for x in (
        "association between", "relationship between", "associated with", "affect",
        "effect", "effective", "reduce", "mortality", "outcome",
    ))
    head = re.split(
        r",\s*(?:and\s+)?|\s+and\s+(?=(?:state|what|give|report|does|is|are)\b)",
        q, maxsplit=1,
    )[0].strip()
    head_match = re.sub(r"[-\u2010-\u2015]", " ", head)
    definition_form = (
        head_match.startswith(("what is ", "what are ", "define ", "what does "))
        or (
            head_match.startswith(("how is ", "how are "))
            and any(marker in head_match for marker in (" defined", " conceptualized", " operationalized"))
        )
        or bool(re.match(r"^how do (?:studies|authors|researchers) define ", head_match))
        or head_match.startswith(("what is meant by ", "what are meant by ", "what definition of "))
    )
    # The main requested proposition controls intent. A definitional-looking
    # background clause cannot weaken an association, causal, or comparison.
    explicit_relational_head = any(
        marker in head_match
        for marker in ("association between", "relationship between", "associated with")
    )
    definition = definition_form and not explicit_relational_head

    def matched(text, candidates):
        normalized = re.sub(r"[-\u2010-\u2015]", " ", text)
        return [canonical for canonical, variants in candidates
                if any(variant in normalized for variant in variants)]

    def fields(text):
        normalized = re.sub(r"[-\u2010-\u2015]", " ", text)
        return {
            "population": matched(normalized, (
                ("primary care professionals", ("primary care professionals", "primary care clinicians")),
                ("healthcare professionals", ("healthcare professionals", "health care professionals")),
                ("patients", (" patients", "patients ")),
                ("nurses", (" nurses", "nurses ")), ("physicians", ("physicians",)),
                ("clinicians", ("clinicians",)), ("professionals", ("professional confidence",)),
                ("adults", ("adults",)),
            )),
            "context": matched(normalized, (
                ("primary care", ("primary care",)), ("end-of-life care", ("end of life care",)),
                ("healthcare", ("healthcare", "health care")), ("hospital", ("hospital",)),
                ("clinical", ("clinical",)),
            )),
            "intervention_or_exposure": matched(normalized, (
                ("AI-CDSS", ("ai cdss",)),
                ("AI-based clinical decision support systems", ("ai based clinical decision support systems",)),
                ("clinical decision support system", ("clinical decision support system", "clinical decision support", "computerized clinical decision support")),
                ("artificial intelligence", ("artificial intelligence",)), ("LLM", (" llm",)),
            )),
            "outcome": matched(normalized, (
                ("diagnostic errors", ("diagnostic errors", "diagnostic mistakes")),
                ("mortality", ("mortality",)), ("survival", ("survival",)),
                ("readmission", ("readmission",)), ("patient outcomes", ("patient outcomes",)),
                ("moral distress", ("moral distress",)), ("outcome", (" outcome",)),
            )),
            "time_requirement": next((canonical for canonical, variants in (
                ("long term", ("long term",)), ("30 days", ("30 day",)),
                ("follow up", ("follow up",)), ("over 30 days", ("over 30 days",)),
            ) if any(v in normalized for v in variants)), None),
            "outcome_direction": next((value for value in
                ("increase", "decrease", "reduce", "prevent", "improve", "worse")
                if value in normalized), None),
            "magnitude": (re.search(r"\b(?:by\s+)?(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s*(?:percent|percentage|%)", normalized).group(0)
                          if re.search(r"\b(?:by\s+)?(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s*(?:percent|percentage|%)", normalized) else None),
            "qualifications": [x for x in ("may", "might", "potential", "reported", "describe", "explicitly") if x in normalized],
            "negations": [x.strip() for x in (" not ", " no ", "without") if x in f" {normalized} "],
        }

    def add(cid, request_type, requirement, proposition_text, *, numerical=False,
            causal_required=False, comparator_required=False):
        qualifiers = fields(proposition_text)
        components.append({
            "component_id": cid, "request_type": request_type, "requirement": requirement,
            "target_construct": [requirement],
            "population": qualifiers["population"], "context": qualifiers["context"],
            "intervention_or_exposure": qualifiers["intervention_or_exposure"],
            "comparator": ["explicit comparator requested"] if comparator_required else [],
            "outcome": qualifiers["outcome"], "time_requirement": qualifiers["time_requirement"],
            "outcome_direction": qualifiers["outcome_direction"],
            "magnitude": qualifiers["magnitude"],
            "study_context": qualifiers["context"],
            "numerical_requirement": "explicit value required" if numerical else None,
            "causal_requirement": causal_required, "required_evidence_type": [request_type],
            "qualifications": qualifiers["qualifications"], "negations": qualifiers["negations"],
            "depends_on": [], "independent": True, "essential": True,
        })

    if definition:
        add("definition_concept", "definition", question.split(",", 1)[0].strip(), head)
    if quantitative:
        add("numerical_value", "numerical", "the explicitly requested numerical outcome",
            q, numerical=True, causal_required=causal, comparator_required=comparative)
    elif comparative:
        add("quantitative_comparison", "comparison", "the explicitly requested comparison",
            q, comparator_required=True)
    elif causal:
        add("causal_contribution", "causal", "the explicitly requested causal relationship",
            q, causal_required=True)
    elif "instrument" in q or "measure" in q:
        add("instrument_measure", "other", "the requested instrument or measure", q)
    elif not definition and barrier:
        add("direct_relationship", "barrier_identification",
            "the explicitly requested reported barrier", q)
    elif not definition and (q.startswith(("how do", "how can")) or relationship):
        temporal = fields(q)["time_requirement"]
        add("direct_relationship", "temporal" if temporal else "association",
            "the requested relationship or outcome", q)
    if not components:
        add("direct_relationship", "other", "direct answer to the requested proposition", q)
    return {"original_question": question, "components": components}


def derive_decision(spec: dict, assessments: list) -> tuple:
    requested = {c["component_id"] for c in spec["components"]}
    supported = {a["component_id"] for a in assessments if a.get("status") == "directly_supported"}
    missing = requested - supported
    essential_missing = {c["component_id"] for c in spec["components"] if c.get("essential") and c["component_id"] in missing}
    if not supported:
        decision = "insufficient"
    elif missing or essential_missing:
        decision = "partial"
    else:
        decision = "sufficient"
    return decision, sorted(supported), sorted(missing), sorted(essential_missing)


def _get_score_from_result_or_metadata(score_lists: dict, score_name: str, index: int, metadata: dict):
    values = score_lists.get(score_name) or []
    if index < len(values) and values[index] is not None:
        return values[index]

    retrieval_scores = metadata.get("retrieval_scores")
    if isinstance(retrieval_scores, dict) and retrieval_scores.get(score_name) is not None:
        return retrieval_scores.get(score_name)

    return metadata.get(score_name)


def _build_retrieval_scores(score_lists: dict, index: int, metadata: dict) -> dict:
    return {
        score_name: score_value
        for score_name in RETRIEVAL_SCORE_FIELDS
        for score_value in [_get_score_from_result_or_metadata(score_lists, score_name, index, metadata)]
        if score_value is not None
    }


def _build_context_and_sources(retrieval_result: dict):
    documents = retrieval_result.get("documents", [[]])[0]
    metadatas = retrieval_result.get("metadatas", [[]])[0]
    score_lists = {
        score_name: retrieval_result.get(f"{score_name}s", [[]])[0]
        for score_name in RETRIEVAL_SCORE_FIELDS
    }

    sources = []
    context_blocks = []

    for idx, (doc, meta) in enumerate(zip(documents, metadatas), start=1):
        meta = meta or {}
        paper_id = (meta.get("paperId") or "").strip()
        title = meta.get("title") or "Unknown"
        url = meta.get("url") or "N/A"
        year = meta.get("year") or "N/A"
        text_source = meta.get("text_source") or "unknown"
        section = meta.get("section") or "unknown"
        supporting_chunks = meta.get("supporting_chunks") or 1
        retrieval_scores = _build_retrieval_scores(score_lists, idx - 1, meta)

        source = {
            "rank": idx,
            "title": title,
            "url": url,
            "year": year,
            "paperId": paper_id,
            "text_source": text_source,
            "text": doc,
            "excerpt_id": f"{paper_id or 'source'}:{idx}",
            "section": section,
            "supporting_chunks": supporting_chunks,
            "semantic_similarity": retrieval_scores.get("embedding_score"),
            "cross_encoder_score": retrieval_scores.get("cross_encoder_score"),
            "keyword_overlap": meta.get("keyword_overlap"),
        }
        sources.append(source)

        context_lines = [
            f"[Source {idx}]",
            f"paperId: {paper_id or 'N/A'}",
            f"title: {title}",
            f"year: {year}",
            f"url: {url}",
            f"text_source: {text_source}",
            f"section: {section}",
            f"supporting_chunks: {supporting_chunks}",
        ]
        context_lines.append(f"excerpt:\n{doc}")
        context_blocks.append("\n".join(context_lines))

    return "\n\n".join(context_blocks), sources


def _build_source_index(sources: list) -> str:
    lines = ["References:"]
    for source in sources:
        rank = source.get("rank", "?")
        title = source.get("title") or "Unknown"
        year = source.get("year") or "N/A"
        lines.append(f"[{rank}] {title} ({year})")
    return "\n".join(lines)


def _replace_placeholder_citations(answer: str, sources: list) -> str:
    def repl(match):
        paper_numbers = [int(num) for num in re.findall(r"\d+", match.group(2))]
        valid_numbers = [n for n in paper_numbers if 1 <= n <= len(sources)]
        if not valid_numbers:
            return match.group(0)
        return "[" + ", ".join(str(n) for n in valid_numbers) + "]"

    return PLACEHOLDER_CITATION_RE.sub(repl, answer)


def _answer_has_allowed_citation(answer: str) -> bool:
    return bool(re.search(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]", answer))


def _rebuild_references_section(answer: str, sources: list) -> str:
    """Rebuild the References section from every [N] citation found in the answer.

    Scans the full answer text so citations in any section (Limitations,
    Practical Implications, etc.) are never omitted from the reference list.
    Handles varied LLM header formats: plain, bold, numbered, double-spaced.
    """
    if not sources:
        return answer

    # Collect every cited number that has a matching source
    cited = sorted({
        int(number)
        for group in re.findall(r"\[\s*(\d+(?:\s*,\s*\d+)*)\s*\]", answer)
        for number in re.findall(r"\d+", group)
        if 1 <= int(number) <= len(sources)
    })
    if not cited:
        return answer

    # Build the authoritative reference block
    entries = [
        f"[{n}] {sources[n - 1].get('title') or 'Unknown'} ({sources[n - 1].get('year') or 'N/A'})"
        for n in cited
    ]
    ref_block = "References\n\n" + "\n\n".join(entries)

    # Strip any existing references section (tolerates bold, numbered, extra whitespace)
    stripped = re.sub(
        r"\n+[ \t]*(?:\d+[\.\)]\s*)?(?:\*{1,2})?References(?:\*{1,2})?[ \t]*\n.*$",
        "",
        answer,
        flags=re.IGNORECASE | re.DOTALL,
    ).rstrip()

    return stripped + "\n\n" + ref_block


def _normalize_text_answer(answer: str, sources: list) -> str:
    normalized = (answer or "").strip()
    if not normalized:
        return INSUFFICIENT_EVIDENCE_MESSAGE

    normalized = _replace_placeholder_citations(normalized, sources)
    if sources:
        normalized = _rebuild_references_section(normalized, sources)
    if sources and not _answer_has_allowed_citation(normalized):
        normalized = f"{normalized}\n\n{_build_source_index(sources)}"
    return normalized


def _build_prompt(
    user_query: str,
    context_text: str,
    answer_template: str,
    output_mode: str,
    sources: list,
):
    n_sources = len(sources)

    base_system = f"""
    - Use ONLY the provided retrieved evidence.
    - Do NOT introduce external knowledge.
    - Do NOT provide clinical recommendations.
    - Do NOT extrapolate beyond the evidence.
    - If the retrieved evidence is empty or not directly relevant, respond exactly with: {INSUFFICIENT_EVIDENCE_MESSAGE}
    - Cite every substantive claim using numbered references matching the [Source N] number in the evidence, for example: [1] or [1, 3].
    - Only use reference numbers between 1 and {n_sources}.
    - Never use paperId values, DOIs, author-year references, or any other citation format.
    - A source is only citable if its excerpt directly addresses the specific question asked. If a source is only tangentially related or does not contain a finding relevant to the question, omit it entirely — do NOT invent or infer a finding to justify including it. Citing fewer sources accurately is always preferable to stretching content from unrelated papers.

    This system provides AI-assisted literature synthesis only.
    It does not replace professional judgment."""

    if answer_template == "structured":
        base_system += """

Use this structure:
1) Summary of the relevant topic (2-4 sentences)
2) Key findings (3-6 bullet points)
3) Limitations / gaps
4) Practical implications
5) References

Every sentence or bullet with a factual claim in sections 1-4 must include one or more numbered citations like [1] or [1, 2]."""

    if output_mode == "json":
        base_system += """

Return ONLY valid JSON with this schema:
{
  "summary": "string",
  "key_findings": ["string"],
  "limitations": ["string"],
  "practical_implications": ["string"],
  "citations_used": ["[1]", "[2]"]
}"""

    prompt = f"""Question: {user_query}

Retrieved evidence:
{context_text}

Please synthesize these papers into a coherent answer."""

    return base_system, prompt


def assess_evidence_sufficiency(user_query: str, sources: list, llm, _allow_repair: bool = True) -> dict:
    """Conservative procedural assessment of question-specific evidence sufficiency."""
    source_ids = [source.get("paperId") for source in sources if source.get("paperId")]
    excerpts = {}
    for idx, source in enumerate(sources, start=1):
        source_id = source.get("paperId")
        excerpt_id = source.get("excerpt_id") or f"{source_id or 'source'}:{idx}"
        source["excerpt_id"] = excerpt_id
        excerpts[excerpt_id] = source_id
    specification = build_question_specification(user_query)
    prompt = f"""Assess whether the supplied excerpts appear sufficient to answer the exact question.
This is a procedural evidence-sufficiency check, not a determination of scientific truth.
Use only the question and excerpts below; do not use outside knowledge or memory.
Topical similarity alone cannot be sufficient. First identify only the components explicitly
requested or logically required by this exact question. Allowed component labels include:
definition/concept, population/context, intervention/exposure, comparator, outcome,
instrument_measure, requested numerical value, temporal horizon, direct_relationship,
causal_contribution, and quantitative_comparison. Use the exact component_id values
provided in the supplied specification.
Direct support must preserve the construct and evidence strength requested by the question:
- evidence about trust, acceptance, or intention to use does not support automation bias;
- association, correlation, prediction, or participant perception does not support causation;
- qualitative findings do not support an unstated number, percentage, rate, or magnitude;
- a narrower or merely related construct does not support a broader question-specific claim;
- comparison requires an explicit comparison, and numerical comparison requires the value.
- for a non-numerical barrier-identification request, an excerpt that explicitly reports
  a barrier experienced or perceived by the requested population is direct qualitative support;
- general workflow discussion or a recommendation is not an observed barrier;
- barrier evidence does not establish a causal outcome, effectiveness, objective performance
  effect, numerical prevalence, or any population/context not represented in the excerpt.
Do not add PICO, numerical, instrument, or temporal components to a definition question
unless the question asks for them. A component is missing only if it is requested and unsupported.
Return ONLY valid JSON with these fields:
components (array of objects with component_id, status directly_supported|unsupported,
supporting_source_ids array, supporting_excerpt_ids array, rationale string),
concise_rationale (string).
Assess exactly this specification: {json.dumps(specification, ensure_ascii=False)}

Question:
{user_query}

Retrieved excerpts:
{json.dumps([{k: s.get(k) for k in ('paperId','excerpt_id','title','text')} for s in sources], ensure_ascii=False)}"""
    raw = ""
    try:
        raw = (llm.generate_structured(prompt, "You are a conservative evidence-sufficiency assessor.")
               if hasattr(llm, "generate_structured") else llm.generate(prompt, "You are a conservative evidence-sufficiency assessor."))
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("empty model response")
        parsed = json.loads(raw)
        required = {"components"}
        if not isinstance(parsed, dict): raise ValueError("output is not an object")
        missing_fields = sorted(required - set(parsed))
        if missing_fields: raise ValueError(f"missing required fields: {missing_fields}")
        if not isinstance(parsed["components"], list) or not parsed["components"]: raise ValueError("components must be a nonempty array")
        requested = {c["component_id"] for c in specification["components"]}
        seen = set()
        for component in parsed["components"]:
            if not isinstance(component, dict) or component.get("component_id") not in requested: raise ValueError("invalid component")
            cid = component["component_id"]
            if cid in seen: raise ValueError("duplicate component")
            seen.add(cid)
            status_aliases = {
                "supported": "directly_supported",
                "directly supported": "directly_supported",
                "not_supported": "unsupported",
                "not supported": "unsupported",
                "missing": "unsupported",
            }
            component["status"] = status_aliases.get(component.get("status"), component.get("status"))
            if component.get("status") not in {"directly_supported", "unsupported"}:
                raise ValueError("invalid component status")
            component.setdefault("supporting_source_ids", [])
            component.setdefault("supporting_excerpt_ids", [])
            if not isinstance(component["supporting_source_ids"], list) or not isinstance(component["supporting_excerpt_ids"], list):
                raise ValueError("invalid component source fields")
            if any(sid not in source_ids for sid in component["supporting_source_ids"]): raise ValueError("gate references nonexistent source id")
            if component["status"] == "directly_supported":
                if not component["supporting_source_ids"]:
                    raise ValueError("supported component requires source ids")
                if not component["supporting_excerpt_ids"]:
                    component["supporting_excerpt_ids"] = [
                        eid for eid, sid in excerpts.items()
                        if sid in component["supporting_source_ids"]
                    ]
                if any(eid not in excerpts for eid in component["supporting_excerpt_ids"]):
                    raise ValueError("gate references nonexistent excerpt id")
                if any(excerpts[eid] not in component["supporting_source_ids"] for eid in component["supporting_excerpt_ids"]):
                    raise ValueError("excerpt does not belong to approved source")
            elif component["supporting_source_ids"] or component["supporting_excerpt_ids"]:
                raise ValueError("unsupported component cannot cite evidence")
            component.setdefault("rationale", "")
        if seen != requested: raise ValueError("component set does not match specification")
        concise_rationale = parsed.get("concise_rationale")
        if not isinstance(concise_rationale, str) or not concise_rationale.strip():
            component_reasons = [
                component["rationale"].strip()
                for component in parsed["components"]
                if isinstance(component.get("rationale"), str) and component["rationale"].strip()
            ]
            concise_rationale = " ".join(component_reasons) or "Component-level evidence assessment completed."
        parsed["concise_rationale"] = concise_rationale
        decision, supported_components, missing_components, essential_missing = derive_decision(specification, parsed["components"])
        approved_ids = sorted({sid for c in parsed["components"] for sid in c.get("supporting_source_ids", []) if c.get("status") == "directly_supported"})
        parsed.update({"decision": decision, "requested_components": sorted(requested), "supported_components": supported_components, "missing_components": missing_components, "essential_missing_components": essential_missing, "supporting_source_ids": approved_ids, "question_specification": specification})
        parsed["error"] = None
        parsed["diagnostic_category"] = None
        parsed["raw_output"] = raw
        parsed["initial_raw_output"] = raw
        parsed["initial_error"] = None
        parsed["initial_diagnostic_category"] = None
        parsed["repair_attempted"] = False
        parsed["repair_raw_output"] = ""
        return parsed
    except Exception as exc:
        category = "invalid_json"
        if isinstance(exc, json.JSONDecodeError): category = "invalid_json"
        elif isinstance(exc, ValueError) and "empty" in str(exc): category = "empty_content"
        elif "source id" in str(exc): category = "unknown_source_ids"
        elif "required fields" in str(exc) or "decision" in str(exc): category = "schema_validation_failure"
        elif isinstance(exc, (ConnectionError, TimeoutError)): category = "api_error"
        if _allow_repair and category in {
            "invalid_json", "empty_content", "schema_validation_failure"
        }:
            repair_prompt = f"""Repair the evidence-gate response below so that it is valid JSON
matching the requested schema. Do not change the evidence judgment, add sources, or use
outside knowledge. Return ONLY the repaired JSON object.

Validation error:
{type(exc).__name__}: {exc}

Original response:
{raw}

Required schema:
components (nonempty array of objects with component_id, status
directly_supported|unsupported, supporting_source_ids array,
supporting_excerpt_ids array, rationale string), concise_rationale string."""
            repair_raw = ""
            try:
                repair_raw = (
                    llm.generate_structured(
                        repair_prompt,
                        "You repair JSON formatting only; you do not alter evidence judgments.",
                    )
                    if hasattr(llm, "generate_structured")
                    else llm.generate(
                        repair_prompt,
                        "You repair JSON formatting only; you do not alter evidence judgments.",
                    )
                )

                class _RepairResponse:
                    def generate_structured(self, *_args, **_kwargs):
                        return repair_raw

                    def generate(self, *_args, **_kwargs):
                        return repair_raw

                repaired = assess_evidence_sufficiency(
                    user_query, sources, _RepairResponse(), _allow_repair=False
                )
                repaired.update({
                    "initial_raw_output": raw,
                    "initial_error": f"{type(exc).__name__}: {exc}",
                    "initial_diagnostic_category": category,
                    "repair_attempted": True,
                    "repair_raw_output": repair_raw,
                })
                if repaired.get("error") is None:
                    repaired["diagnostic_category"] = "repaired_schema_output"
                return repaired
            except Exception as repair_exc:
                return {
                    "decision": "insufficient",
                    "requested_components": [
                        c["component_id"] for c in specification["components"]
                    ],
                    "supported_components": [],
                    "missing_components": [
                        c["component_id"] for c in specification["components"]
                    ],
                    "essential_missing_components": [
                        c["component_id"] for c in specification["components"]
                        if c.get("essential")
                    ],
                    "components": [],
                    "concise_rationale": "Evidence-sufficiency assessment failed closed.",
                    "supporting_source_ids": [],
                    "error": f"{type(repair_exc).__name__}: {repair_exc}",
                    "diagnostic_category": "repair_attempt_failed",
                    "raw_output": repair_raw,
                    "initial_raw_output": raw,
                    "initial_error": f"{type(exc).__name__}: {exc}",
                    "initial_diagnostic_category": category,
                    "repair_attempted": True,
                    "repair_raw_output": repair_raw,
                    "question_specification": specification,
                }
        return {
            "decision": "insufficient", "requested_components": [c["component_id"] for c in specification["components"]], "supported_components": [],
            "missing_components": [c["component_id"] for c in specification["components"]],
            "essential_missing_components": [c["component_id"] for c in specification["components"] if c.get("essential")],
            "components": [],
            "concise_rationale": "Evidence-sufficiency assessment failed closed.",
            "supporting_source_ids": [], "error": f"{type(exc).__name__}: {exc}",
            "diagnostic_category": category,
            "raw_output": raw, "initial_raw_output": raw,
            "initial_error": f"{type(exc).__name__}: {exc}",
            "initial_diagnostic_category": category,
            "repair_attempted": False, "repair_raw_output": "",
            "question_specification": specification,
        }


def _build_evidence_gap_response(gate: dict) -> str:
    missing = ", ".join(gate.get("missing_components") or ["the requested evidence"])
    return f"Related evidence was retrieved, but the excerpts do not establish {missing}. The system is therefore not providing a substantive answer."


def _approved_sources(sources: list, gate: dict) -> list:
    available_source_ids = {source.get("paperId") for source in sources}
    approved_source_ids = {
        source_id
        for component in gate.get("components", [])
        if component.get("status") == "directly_supported"
        for source_id in component.get("supporting_source_ids", [])
    }
    if not approved_source_ids or not approved_source_ids <= available_source_ids:
        raise ValueError("generation contract references unresolved source IDs")
    approved_excerpt_ids = [
        excerpt_id
        for component in gate.get("components", [])
        if component.get("status") == "directly_supported"
        for excerpt_id in component.get("supporting_excerpt_ids", [])
    ]
    if not approved_excerpt_ids:
        raise ValueError("generation contract has no approved excerpt IDs")
    by_excerpt_id = {source.get("excerpt_id"): source for source in sources}
    selected = [
        by_excerpt_id[excerpt_id]
        for excerpt_id in dict.fromkeys(approved_excerpt_ids)
        if excerpt_id in by_excerpt_id
    ]
    if len(selected) != len(set(approved_excerpt_ids)):
        raise ValueError("generation contract references unresolved excerpt IDs")
    return selected


def build_generation_contract(question: str, gate: dict, sources: list) -> dict:
    approved = _approved_sources(sources, gate)
    by_component = {c["component_id"]: [sid for sid in c.get("supporting_source_ids", [])] for c in gate.get("components", []) if c.get("status") == "directly_supported"}
    if any(not ids for cid, ids in by_component.items() if cid in gate.get("supported_components", [])):
        raise ValueError("supported component has no approved source")
    resolved = []
    for rank, source in enumerate(approved, start=1):
        clean = {k: copy.deepcopy(v) for k, v in source.items() if k not in RETRIEVAL_SCORE_FIELDS and k not in {
            "semantic_similarity", "cross_encoder_score", "keyword_overlap"
        }}
        clean["rank"] = rank
        resolved.append(clean)
    specification_by_id = {
        component["component_id"]: component
        for component in (gate.get("question_specification") or {}).get("components", [])
    }

    def gap_label(component_id):
        component = specification_by_id.get(component_id, {})
        request_type = component.get("request_type")
        if request_type == "numerical":
            return "the requested exact numerical value or percentage"
        if request_type == "comparison":
            return "the requested direct comparison"
        if request_type == "causal":
            return "the requested causal relationship"
        if request_type == "temporal":
            return "the requested temporal relationship"
        return component.get("requirement") or component_id

    contract = {
        "original_question": question,
        "requested_components": gate.get("requested_components", []),
        "supported_components": gate.get("supported_components", []),
        "missing_components": gate.get("missing_components", []),
        "essential_missing_components": gate.get("essential_missing_components", []),
        "decision": gate.get("decision"),
        "decision_reason": gate.get("concise_rationale", ""),
        "approved_sources_by_component": by_component,
        "resolved_approved_excerpts": resolved,
        "permitted_answer_scope": gate.get("supported_components", []),
        "prohibited_answer_scope": gate.get("missing_components", []),
        "unsupported_proposition_labels": {
            component_id: gap_label(component_id)
            for component_id in gate.get("missing_components", [])
        },
        "approved_quantitative_claims": [],
    }
    return copy.deepcopy(contract)


QUANTITATIVE_FIELDS = (
    "value", "unit", "measure_outcome", "numerator", "denominator", "comparator",
    "population", "context", "temporal_horizon", "source_id", "excerpt_id",
)


def validate_quantitative_claims(answer: str, contract: dict, claims: list = None) -> dict:
    """Validate numeric prose and any explicit structured quantitative claims."""
    text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
    body = re.split(r"\n\s*(?:\*{0,2})References(?:\*{0,2})\s*\n", text or "", maxsplit=1,
                    flags=re.IGNORECASE)[0]
    body = re.sub(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]", "", body)
    body = re.sub(r"(?m)^\s*\d+[\.)]\s*", "", body)
    numeric_tokens = re.findall(r"\b\d+(?:\.\d+)?(?:\s*%|\s+[A-Za-z]+)?", body)
    approved = contract.get("approved_quantitative_claims") or []
    claims = claims or []
    errors = []
    if numeric_tokens and not claims:
        errors.append("numeric text has no structured quantitative claim")
    for claim in claims:
        if not isinstance(claim, dict):
            errors.append("quantitative claim is not an object")
            continue
        missing = [field for field in QUANTITATIVE_FIELDS if field not in claim]
        if missing:
            errors.append(f"quantitative claim missing fields: {missing}")
            continue
        if not any(all(candidate.get(field) == claim.get(field) for field in QUANTITATIVE_FIELDS)
                   for candidate in approved if isinstance(candidate, dict)):
            errors.append("quantitative claim meaning is not approved")
    return {
        "valid": not errors,
        "detected_values": numeric_tokens,
        "claims": copy.deepcopy(claims),
        "errors": errors,
        "diagnostic_category": "unapproved_quantitative_claim" if errors else None,
    }


def validate_citations_and_references(answer: str, sources: list) -> dict:
    """Reject unknown/malformed citations before canonical reference rebuilding."""
    text = answer or ""
    parts = re.split(r"\n\s*(?:\*{0,2})References(?:\*{0,2})\s*\n", text, maxsplit=1,
                     flags=re.IGNORECASE)
    body = parts[0]
    supplied_references = parts[1] if len(parts) == 2 else ""
    citation_groups = re.findall(r"\[([^\]]+)\]", body)
    malformed = [group for group in citation_groups if not re.fullmatch(r"\s*\d+(?:\s*,\s*\d+)*\s*", group)]
    cited = sorted({int(n) for group in citation_groups for n in re.findall(r"\d+", group)})
    unknown = [n for n in cited if n < 1 or n > len(sources)]
    errors = []
    if malformed:
        errors.append(f"malformed citations: {malformed}")
    if unknown:
        errors.append(f"unapproved citation numbers: {unknown}")
    if body.strip() and sources and not cited:
        errors.append("substantive answer has no approved citation")
    reference_numbers = sorted({int(n) for n in re.findall(r"(?m)^\s*\[(\d+)\]", supplied_references)})
    unknown_references = [n for n in reference_numbers if n < 1 or n > len(sources)]
    uncited_references = [n for n in reference_numbers if n not in cited]
    if unknown_references:
        errors.append(f"unapproved reference numbers: {unknown_references}")
    if uncited_references:
        errors.append(f"references not cited in answer: {uncited_references}")
    return {
        "valid": not errors, "citation_numbers": cited,
        "reference_numbers": reference_numbers, "errors": errors,
        "diagnostic_category": "invalid_citations_or_references" if errors else None,
    }


def generate_validated_claims(user_query: str, contract: dict, approved_sources: list, llm) -> dict:
    """Generate structured claims, validate each against its declared excerpt, then render."""
    excerpt_map = {s["excerpt_id"]: s for s in approved_sources}
    generation_prompt = f"""Return ONLY JSON:
{{"disposition":"answer|partial|abstain","claims":[{{"claim_id":"cl1","component_id":"...","claim_text":"...",
"excerpt_ids":["..."],"paper_ids":["..."],"evidence_strength":"definition|descriptive|association|causal|qualitative|quantitative|comparison"}}],
"unsupported_components":[]}}
Question: {user_query}
Approved component whitelist: {json.dumps(contract["permitted_answer_scope"])}
Approved excerpts: {json.dumps([{k:s.get(k) for k in ("excerpt_id","paperId","text")} for s in approved_sources], ensure_ascii=False)}
Every claim must answer an approved component directly. Add no background, implication, advice,
recommendation, mitigation strategy, or conclusion unless that content is itself requested and
directly supported. Use only declared excerpt text."""
    try:
        raw = (llm.generate_structured(generation_prompt, "You produce evidence-bound structured claims.")
               if hasattr(llm, "generate_structured") else llm.generate(generation_prompt))
        parsed = json.loads(raw)
        claims = parsed.get("claims")
        if not isinstance(claims, list):
            raise ValueError("claims must be an array")
        expected_disposition = "partial" if contract["decision"] == "partial" else "answer"
        if parsed.get("disposition") not in {"answer", "partial", "abstain"}:
            raise ValueError("invalid disposition")
        disposition_mismatch = parsed["disposition"] != expected_disposition
        unsupported_set_mismatch = (
            set(parsed.get("unsupported_components", [])) !=
            set(contract["prohibited_answer_scope"])
        )
        if contract["decision"] == "partial":
            declared_components = {
                claim.get("component_id") for claim in claims if isinstance(claim, dict)
            }
            missing_supported = (
                set(contract["permitted_answer_scope"]) - declared_components
            )
            if missing_supported:
                repair_prompt = f"""Return ONLY JSON with a claims array.
The validated evidence contract requires one directly supported claim for each of these
missing supported components: {json.dumps(sorted(missing_supported))}.
Do not answer any unsupported component. The unsupported components are fixed by the
contract as: {json.dumps(contract["prohibited_answer_scope"])}.
Question: {user_query}
Approved excerpts: {json.dumps([{k:s.get(k) for k in ("excerpt_id","paperId","text")} for s in approved_sources], ensure_ascii=False)}
Each claim must contain claim_id, component_id, claim_text, excerpt_ids, paper_ids, and
evidence_strength. Use only approved excerpt IDs and text."""
                repair_raw = (
                    llm.generate_structured(
                        repair_prompt,
                        "You repair a contract-required supported claim; you cannot abstain globally.",
                    )
                    if hasattr(llm, "generate_structured")
                    else llm.generate(repair_prompt)
                )
                repaired = json.loads(repair_raw)
                repaired_claims = repaired.get("claims")
                if not isinstance(repaired_claims, list):
                    raise ValueError("bounded-partial repair claims must be an array")
                claims.extend(repaired_claims)
    except Exception as exc:
        return {"valid_claims": [], "removed_claims": [], "error": f"{type(exc).__name__}: {exc}",
                "raw_structured_claims": locals().get("raw", ""), "rendered": INSUFFICIENT_EVIDENCE_MESSAGE}
    valid, removed = [], []
    allowed = set(contract["permitted_answer_scope"])
    for claim in claims:
        reason = None
        if not isinstance(claim, dict) or claim.get("component_id") not in allowed:
            reason = "unapproved_component"
        excerpt_ids = claim.get("excerpt_ids") if isinstance(claim, dict) else None
        paper_ids = claim.get("paper_ids") if isinstance(claim, dict) else None
        if not reason and (not excerpt_ids or not paper_ids or not claim.get("claim_text") or not claim.get("evidence_strength")):
            reason = "invalid_claim_schema"
        declared = [excerpt_map.get(eid) for eid in (excerpt_ids or [])]
        if not reason and (any(s is None for s in declared) or {s["paperId"] for s in declared} != set(paper_ids)):
            reason = "excerpt_paper_identity_failure"
        judge_raw = ""
        if not reason:
            judge_prompt = f"""Return ONLY JSON {{"verdict":"entailed|contradicted|topically_related_not_entailed|insufficiently_specific|unverifiable","rationale":"..."}}.
Decide whether the excerpt directly entails the claim while preserving construct, population,
context, direction, causality, comparator, outcome, number, time, negation, uncertainty, and
evidence strength. Related constructs are not interchangeable. Claim: {claim["claim_text"]}
Evidence strength declared: {claim["evidence_strength"]}
Excerpts: {json.dumps([s["text"] for s in declared], ensure_ascii=False)}"""
            try:
                judge_raw = (llm.generate_structured(judge_prompt, "You are a conservative entailment validator.")
                             if hasattr(llm, "generate_structured") else llm.generate(judge_prompt))
                judgment = json.loads(judge_raw)
                if judgment.get("verdict") != "entailed":
                    reason = judgment.get("verdict") or "unverifiable"
            except Exception as exc:
                reason = f"validator_unavailable_or_malformed:{type(exc).__name__}"
        claim["validator_raw"] = judge_raw
        if reason:
            removed.append({**claim, "removal_reason": reason})
        else:
            valid.append(claim)
    rendered = "\n\n".join(
        f"{c['claim_text']} " + " ".join(f"[{approved_sources.index(excerpt_map[eid])+1}]" for eid in c["excerpt_ids"])
        for c in valid
    ) or INSUFFICIENT_EVIDENCE_MESSAGE
    valid_components = {c["component_id"] for c in valid}
    missing_validated_supported = (
        set(contract["permitted_answer_scope"]) - valid_components
    )
    technical_failure = bool(
        contract["decision"] == "partial" and missing_validated_supported
    )
    if technical_failure:
        recomputed = "technical_failure"
        rendered = (
            "A proposition classified as supported could not be rendered and validated "
            "from its approved excerpt. No substantive answer was produced."
        )
    elif not valid:
        recomputed = "abstention"
    elif (set(contract["permitted_answer_scope"]) - valid_components or
          contract["prohibited_answer_scope"]):
        recomputed = "partial"
    else:
        recomputed = "answer"
    if recomputed == "partial":
        labels = contract.get("unsupported_proposition_labels", {})
        for component_id in contract["prohibited_answer_scope"]:
            rendered += (
                "\n\nThe retrieved evidence does not directly support "
                f"{labels.get(component_id, component_id)}."
            )
    return {"raw_structured_claims": raw, "valid_claims": valid, "removed_claims": removed,
            "error": None, "rendered": rendered, "declared_disposition": parsed["disposition"],
            "disposition_mismatch": disposition_mismatch,
            "unsupported_set_mismatch": unsupported_set_mismatch,
            "contract_unsupported_components": list(contract["prohibited_answer_scope"]),
            "missing_validated_supported_components": sorted(missing_validated_supported),
            "technical_failure": technical_failure,
            "recomputed_disposition": recomputed}


def generate_rag_answer(
    user_query: str,
    provider: str = "openai",
    k: int = 5,
    answer_template: str = "default",
    output_mode: str = "text",
    llm=None,
    collection=None,
    embedding_model=None,
    **kwargs,
) -> dict:
    """
    Complete RAG pipeline:
    1. Retrieve relevant chunks
    2. Build context
    3. Generate answer with LLM

    Args:
        user_query: User's question
        provider: "openai" or "ollama"
        k: Number of papers to retrieve
        answer_template: "default" or "structured"
        output_mode: "text" or "json"
        **kwargs: Additional args for LLM provider

    Returns:
        {"answer": str, "sources": list, "query": str}
    """
    if not user_query.strip():
        raise ValueError("Query must not be empty.")

    require_retrieval_dependencies()
    if not os.path.exists(CHROMA_DIR):
        raise RuntimeError("No index found. Run: python Retrieval/retrieval.py index")

    print(f"Retrieving {k} relevant papers...")
    collection = collection or get_chroma_collection()
    model = embedding_model or get_embedding_model()

    q_emb = model.encode([user_query], convert_to_numpy=True, normalize_embeddings=True).tolist()[0]

    retrieval_result = collection.query(
        query_embeddings=[q_emb],
        n_results=k,
        query_text=user_query,
        include=["documents", "metadatas", "distances"],
    )

    specification = build_question_specification(user_query)
    excerpt_exposure = select_proposition_excerpts(retrieval_result, specification)
    if excerpt_exposure["sources"]:
        sources = excerpt_exposure["sources"]
        context_text = "\n\n".join(
            f"[{index}] {source.get('title') or 'Untitled'}\n"
            f"paperId: {source.get('paperId')}\n"
            f"excerpt_id: {source.get('excerpt_id')}\n"
            f"section: {source.get('section')}\n"
            f"excerpt: {source.get('text')}"
            for index, source in enumerate(sources, start=1)
        )
    else:
        context_text, sources = _build_context_and_sources(retrieval_result)
    retrieval_notes = retrieval_result.get("retrieval_notes", [[]])[0]

    if not sources:
        spec = specification
        requested = [c["component_id"] for c in spec["components"]]
        contract = {
            "original_question": user_query, "requested_components": requested,
            "supported_components": [], "missing_components": requested,
            "essential_missing_components": [c["component_id"] for c in spec["components"] if c.get("essential")],
            "decision": "insufficient", "decision_reason": "No sources survived retrieval.",
            "approved_sources_by_component": {}, "resolved_approved_excerpts": [],
            "permitted_answer_scope": [], "prohibited_answer_scope": requested,
            "approved_quantitative_claims": [],
        }
        return {
            "query": user_query,
            "answer": INSUFFICIENT_EVIDENCE_MESSAGE,
            "sources": [],
            "provider": provider,
            "template": answer_template,
            "output_mode": output_mode,
            "retrieval_notes": retrieval_notes,
            "retrieval": retrieval_result,
            "excerpt_exposure": excerpt_exposure,
            "insufficient_evidence": True,
            "evidence_sufficiency": {
                "decision": "insufficient", "question_specification": spec,
                "requested_components": requested, "supported_components": [],
                "missing_components": requested, "essential_missing_components": contract["essential_missing_components"],
                "supporting_source_ids": [], "components": [], "raw_output": "",
                "diagnostic_category": "zero_sources", "error": None,
                "concise_rationale": "No sources survived retrieval.",
            },
            "generation_contract": contract,
            "citations": [], "references": [], "generation_bypassed": True,
            "generation_bypass_reason": "insufficient evidence: zero retrieved sources",
            "final_disposition": "evidence_gap",
        }

    # Injected resources are borrowed: this consumer never closes them.
    llm = llm or get_llm_provider(provider, model="gpt-4o-mini", **kwargs)
    gate = assess_evidence_sufficiency(user_query, sources, llm)
    if gate["decision"] == "insufficient":
        requested = gate.get("requested_components", [])
        contract = {
            "original_question": user_query, "requested_components": requested,
            "supported_components": gate.get("supported_components", []),
            "missing_components": gate.get("missing_components", []),
            "essential_missing_components": gate.get("essential_missing_components", []),
            "decision": "insufficient", "decision_reason": gate.get("concise_rationale", ""),
            "approved_sources_by_component": {}, "resolved_approved_excerpts": [],
            "permitted_answer_scope": [], "prohibited_answer_scope": gate.get("missing_components", []),
            "approved_quantitative_claims": [],
        }
        return {
            "query": user_query, "answer": _build_evidence_gap_response(gate), "sources": sources,
            "provider": provider, "template": answer_template, "output_mode": output_mode,
            "retrieval_notes": retrieval_notes, "insufficient_evidence": True,
            "retrieval": retrieval_result,
                "evidence_sufficiency": gate, "generation_contract": contract,
                "final_disposition": "evidence_gap", "citations": [], "references": [],
                "generation_bypassed": True,
                "generation_bypass_reason": "insufficient evidence decision",
        }
    try:
        contract = build_generation_contract(user_query, gate, sources)
        approved_sources = contract["resolved_approved_excerpts"]
    except Exception as exc:
        gate["error"] = f"{type(exc).__name__}: {exc}"
        gate["diagnostic_category"] = "generation_contract_failure"
        return {"query": user_query, "answer": _build_evidence_gap_response(gate), "sources": sources,
                "provider": provider, "template": answer_template, "output_mode": output_mode,
                "retrieval_notes": retrieval_notes, "insufficient_evidence": True,
                "evidence_sufficiency": gate, "generation_contract": None, "final_disposition": "evidence_gap"}
    bounded = (f"Only address these supported components: {', '.join(contract['supported_components'])}.\n"
               f"Explicitly state that these are not established: {', '.join(gate['missing_components']) or 'none'}.\n"
               "Do not add background, implications, recommendations, comparisons, numbers, or relationships beyond the approved components.")
    approved_context = "\n\n".join(f"[Source {s['rank']}] paperId: {s['paperId']}\n{s['text']}" for s in approved_sources)
    system_message, prompt = _build_prompt(user_query, bounded + "\n\n" + approved_context,
                                            answer_template, output_mode, approved_sources)

    print(f"Generating answer with {provider}...")
    structured_trace = generate_validated_claims(user_query, contract, approved_sources, llm)
    raw_answer = structured_trace["rendered"]
    if not structured_trace["valid_claims"]:
        technical_failure = bool(structured_trace.get("technical_failure"))
        return {
            "query": user_query, "answer": (
                raw_answer if technical_failure else INSUFFICIENT_EVIDENCE_MESSAGE
            ),
            "sources": approved_sources, "provider": provider, "template": answer_template,
            "output_mode": output_mode, "retrieval_notes": retrieval_notes,
            "retrieval": retrieval_result, "insufficient_evidence": True,
            "evidence_sufficiency": gate, "generation_contract": contract,
            "structured_claim_validation": structured_trace,
            "rejected_generation_output": structured_trace.get("raw_structured_claims", ""),
            "citation_validation": {"valid": True, "citation_numbers": [], "errors": []},
            "quantitative_validation": {"valid": True, "diagnostic_category": "no_validated_claims"},
            "citations": [], "references": [],
            "technical_failure": technical_failure,
            "final_disposition": (
                "technical_failure" if technical_failure else "evidence_gap"
            ),
        }

    answer = raw_answer
    parse_error = None
    if output_mode == "json":
        try:
            answer = json.loads(raw_answer)
        except json.JSONDecodeError as exc:
            parse_error = str(exc)
            answer = {"raw_text": raw_answer}
    else:
        citation_validation = validate_citations_and_references(raw_answer, approved_sources)
        if not citation_validation["valid"]:
            return {
                "query": user_query, "answer": _build_evidence_gap_response(gate),
                "sources": approved_sources, "provider": provider, "template": answer_template,
                "output_mode": output_mode, "retrieval_notes": retrieval_notes,
                "insufficient_evidence": True, "evidence_sufficiency": gate,
                "generation_contract": contract, "citation_validation": citation_validation,
                "rejected_generation_output": raw_answer, "citations": [], "references": [],
                "final_disposition": "evidence_gap",
            }
        answer = _normalize_text_answer(raw_answer, approved_sources)
    quantitative = validate_quantitative_claims(answer, contract)
    if not quantitative["valid"]:
        return {"query": user_query, "answer": _build_evidence_gap_response(gate), "sources": approved_sources,
                "provider": provider, "template": answer_template, "output_mode": output_mode,
                "retrieval_notes": retrieval_notes, "insufficient_evidence": True,
                "evidence_sufficiency": gate, "generation_contract": contract,
                "quantitative_validation": quantitative, "rejected_generation_output": raw_answer,
                "citations": [], "references": [], "final_disposition": "evidence_gap"}

    result = {
        "query": user_query,
        "answer": answer,
        "sources": approved_sources,
        "provider": provider,
        "template": answer_template,
        "output_mode": output_mode,
        "retrieval_notes": retrieval_notes,
        "retrieval": retrieval_result,
        "excerpt_exposure": excerpt_exposure,
        "insufficient_evidence": False,
        "evidence_sufficiency": gate,
        "generation_contract": contract,
        "quantitative_validation": quantitative,
        "citation_validation": citation_validation if output_mode != "json" else None,
        "citations": citation_validation["citation_numbers"] if output_mode != "json" else [],
        "references": [
            {"number": n, "paperId": approved_sources[n - 1]["paperId"],
             "title": approved_sources[n - 1].get("title"), "year": approved_sources[n - 1].get("year")}
            for n in (citation_validation["citation_numbers"] if output_mode != "json" else [])
        ],
        "final_disposition": {
            "answer": "supported_answer", "partial": "bounded_partial",
            "abstention": "evidence_gap",
        }[structured_trace["recomputed_disposition"]],
        "structured_claim_validation": structured_trace,
    }
    if not structured_trace["valid_claims"]:
        result["answer"] = INSUFFICIENT_EVIDENCE_MESSAGE
        result["insufficient_evidence"] = True
        result["final_disposition"] = "evidence_gap"
        result["citations"] = []
        result["references"] = []

    if parse_error:
        result["parse_error"] = parse_error

    return result


def evaluate_single_query(user_query: str, provider: str = "openai", k: int = 5) -> dict:
    """Canonical evaluation entry point; preserves retrieval and generation traceability."""
    return generate_rag_answer(user_query, provider=provider, k=k, answer_template="structured", output_mode="text")


def evaluate_query_batch(queries, provider: str = "openai", k: int = 5, *,
                         llm=None, collection=None, embedding_model=None):
    """Evaluate sequential cases under one explicit resource-ownership scope.

    Injected resources are borrowed and never closed. Resources created here are
    owned by this batch and its LLM transport is closed exactly once after the
    complete batch. Exceptions become per-case technical failures and do not
    invalidate or replace the still-open resources for later cases.
    """
    owned_llm = llm is None
    batch_llm = llm or get_llm_provider(provider, model="gpt-4o-mini")
    batch_collection = collection or get_chroma_collection()
    batch_embedding = embedding_model or get_embedding_model()
    rows = []
    try:
        for query in queries:
            try:
                rows.append(generate_rag_answer(
                    query, provider=provider, k=k, answer_template="structured",
                    output_mode="text", llm=batch_llm, collection=batch_collection,
                    embedding_model=batch_embedding,
                ))
            except Exception as exc:
                rows.append({
                    "query": query, "technical_failure": True,
                    "error": f"{type(exc).__name__}: {exc}",
                })
        return rows
    finally:
        if owned_llm:
            client = getattr(batch_llm, "client", None)
            close = getattr(client, "close", None)
            if callable(close):
                close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate RAG answer with configurable templates")
    parser.add_argument("query", type=str, help="User question")
    parser.add_argument("provider", type=str, choices=["openai", "ollama"], help="LLM provider")
    parser.add_argument("--k", type=int, default=5, help="Number of retrieved papers")
    parser.add_argument(
        "--template",
        type=str,
        choices=["default", "structured"],
        default="structured",
        help="Answer template style",
    )
    parser.add_argument(
        "--output",
        type=str,
        choices=["text", "json"],
        default="text",
        help="Output mode",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Explicit model name. For Ollama, examples: qwen3:14b, gemma3:12b.",
    )

    args = parser.parse_args()

    extra_kwargs = {}
    if args.model:
        extra_kwargs["model"] = args.model

    result = generate_rag_answer(
        args.query,
        provider=args.provider,
        k=args.k,
        answer_template=args.template,
        output_mode=args.output,
        **extra_kwargs,
    )
    dump_json_console(result, ensure_ascii=False, indent=2)
