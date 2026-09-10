"""LLM-assisted title/abstract screening pipeline.

Stage 2 of the HyBreDe pipeline. Performs automated title-abstract screening
of candidate papers against predefined inclusion and exclusion criteria.

Pipeline stages
---------------
1. Load metadata corpus (titles + abstracts)
2. Deduplicate papers using paperId
3. Screen each paper using an LLM
4. Validate the decision with a second, independent LLM call
5. Log all screening decisions for auditability
6. Store INCLUDED + VALID papers as the filtered research corpus

Design intent
-------------
This is a *conservative pre-screening assistant*. It narrows a candidate
evidence set before human review. It deliberately defaults to EXCLUDE on any
malformed or ambiguous model output, so the failure mode is a missed candidate
rather than an unjustified inclusion. Final evaluative authority remains with
the human researcher; the system performs no clinical decision-making.

Sanitization notes for the public release
-----------------------------------------
* Paths come from `src.common.paths` and are environment configurable. The
  original imported a co-authored shared path module, not redistributed here.
* No credential is embedded; the OpenAI client reads OPENAI_API_KEY from the
  environment.
* Script-level execution was moved into `main()`. Prompts, decision logic,
  verification logic and audit logging are unchanged.

Environment variables
---------------------
OPENAI_API_KEY  Required by the OpenAI client.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from openai import OpenAI

from src.common.paths import (
    AUDIT_LOG_PATH,
    FILTERED_PAPERS_PATH,
    METADATA_PATH,
    PROCESSED_DIR,
    SCREENING_LOG_PATH,
)

load_dotenv()

SCREENING_MODEL = os.getenv("HYBREDE_SCREENING_MODEL", "gpt-4o-mini")


# ------------------------------ PROMPTS ------------------------------

SCREENING_PROMPT = """You are an academic assistant performing literature screening for a research project.

The goal of this screening process is to identify literature relevant to
healthcare research, evidence-based practice, and the use of knowledge
or information within professional healthcare contexts.

The system operates as a conservative pre-screening assistant that
applies rule-based inclusion and exclusion criteria before human review.
Its purpose is to narrow the candidate evidence set while preserving
final evaluative authority with the human researcher.

Your task is to decide whether a scientific paper should be INCLUDED
or EXCLUDED based solely on the title and abstract provided.


Inclusion criteria (INCLUDE if MOST apply):

- The paper concerns healthcare, rehabilitation, clinical research,
  public health, or professional healthcare practice.

- The paper relates to healthcare professionals' use, understanding,
  management, or application of knowledge, research evidence,
  digital tools, or information systems in healthcare contexts.

- The paper discusses evidence-based practice, professional education,
  decision-making, digital health technologies, information systems,
  or knowledge-related processes in healthcare.

- Studies involving AI systems, digital platforms, decision-support
  tools, or health technologies are acceptable when they are discussed
  in relation to healthcare professionals, healthcare systems,
  professional practice, or healthcare research contexts.


Exclusion criteria (EXCLUDE if ANY apply):

- The paper is directly addressed to patients or primarily studies
  patient behaviour, engagement, or patient-facing applications.

- The paper describes treatment delivery, therapeutic interventions,
  or clinical procedures performed on patients as actionable care.

- The paper evaluates patient outcomes, treatment effectiveness,
  or clinical efficacy of medical or rehabilitation interventions.

- The paper proposes or evaluates AI systems for diagnosis,
  prediction of clinical outcomes, or autonomous clinical decision-making.

- The paper focuses exclusively on non-healthcare domains
  (e.g., finance, digital currency, general blockchain infrastructure)
  without clear relevance to healthcare practice.


Important constraints:

- Do NOT summarise the paper.
- Do NOT evaluate scientific quality.
- Do NOT provide recommendations.
- Do NOT add extra commentary.

If there is uncertainty, output EXCLUDE.

Your output must follow this exact format:

Decision: INCLUDE or EXCLUDE
Justification: 1-2 sentences explaining which criteria were applied.


Title:
{title}

Abstract:
{abstract}
"""

VERIFICATION_PROMPT = """You are validating a literature screening decision.

A previous AI system screened a paper based on predefined
inclusion and exclusion criteria.

Your task is NOT to rescreen the paper.

Your task is only to verify whether the decision is logically
consistent with the justification and the criteria.

If the justification contradicts the criteria -> INVALID.
If the justification is insufficient or vague -> INVALID.

If the decision is logically supported by the justification,
return VALID.

Output format:

Validation: VALID or INVALID
Reason: one short sentence.


Decision:
{decision}

Justification:
{justification}

Title:
{title}

Abstract:
{abstract}"""


# ------------------------------ HELPERS ------------------------------

def extract_screening_text(paper: dict) -> tuple[str, str]:
    """Return (title, abstract), substituting a placeholder for empty abstracts."""
    title = paper.get("title", "").strip()
    abstract = paper.get("abstract")
    if not abstract or not abstract.strip():
        abstract = "No abstract provided"
    return title, abstract


def screen_paper_with_llm(title: str, abstract: str, client: OpenAI) -> str:
    response = client.chat.completions.create(
        model=SCREENING_MODEL,
        messages=[
            {"role": "system", "content": "You are a strict academic screening assistant."},
            {
                "role": "user",
                "content": SCREENING_PROMPT.format(title=title, abstract=abstract),
            },
        ],
        temperature=0,
        top_p=1,
    )
    return response.choices[0].message.content.strip()


def parse_llm_response(response_text: str) -> tuple[str, str]:
    """Extract (decision, justification) from the model response.

    Conservative decision logic: if the response does not follow the expected
    format, default to EXCLUDE to avoid accidental inclusion.
    """
    decision = None
    justification = None

    for line in response_text.splitlines():
        line = line.strip()
        if line.startswith("Decision:"):
            decision = line.replace("Decision:", "").strip()
        elif line.startswith("Justification:"):
            justification = line.replace("Justification:", "").strip()

    if decision:
        decision = decision.strip().upper()

    if decision not in {"INCLUDE", "EXCLUDE"}:
        decision = "EXCLUDE"
        justification = "Invalid or missing decision format."

    if not justification:
        justification = "No valid justification provided."

    return decision, justification


def verify_screening(
    decision: str, justification: str, title: str, abstract: str, client: OpenAI
) -> str:
    """Independent second-pass consistency check on the screening decision."""
    response = client.chat.completions.create(
        model=SCREENING_MODEL,
        messages=[
            {"role": "system", "content": "You are a verification assistant."},
            {
                "role": "user",
                "content": VERIFICATION_PROMPT.format(
                    decision=decision,
                    justification=justification,
                    title=title,
                    abstract=abstract,
                ),
            },
        ],
        temperature=0,
        top_p=1,
    )
    return response.choices[0].message.content.strip()


def write_audit_entry(paper_id: str, decision: str, validation_status: str) -> None:
    """Append one traceability record to the audit log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "paperId": paper_id,
        "decision": decision,
        "validation": validation_status,
    }
    if os.path.exists(AUDIT_LOG_PATH):
        with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as handle:
            audit_data = json.load(handle)
    else:
        audit_data = []
    audit_data.append(entry)
    with open(AUDIT_LOG_PATH, "w", encoding="utf-8") as handle:
        json.dump(audit_data, handle, ensure_ascii=False, indent=4)


def _load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    return default


# ------------------------------ MAIN LOOP ------------------------------

def main() -> None:
    print("=== START SCREENING RUN ===")

    included_papers = _load_json(FILTERED_PAPERS_PATH, [])
    all_screening_results = _load_json(SCREENING_LOG_PATH, [])
    screened_ids = {p["paperId"] for p in all_screening_results}

    with open(METADATA_PATH, "r", encoding="utf-8") as handle:
        papers = json.load(handle)

    # Deduplicate on paperId so each paper is screened exactly once.
    unique_papers = {p["paperId"]: p for p in papers if p.get("paperId")}
    papers = list(unique_papers.values())
    print(f"Loaded {len(papers)} unique papers after deduplication.")

    client = OpenAI()
    invalid_cases = 0

    for idx, paper in enumerate(papers, start=1):
        if paper.get("paperId") in screened_ids:
            print(f"[{idx}] already screened - skipping")
            continue

        title, abstract = extract_screening_text(paper)

        try:
            result = screen_paper_with_llm(title, abstract, client)
            decision, justification = parse_llm_response(result)
            validation = verify_screening(decision, justification, title, abstract, client)
        except Exception as error:  # noqa: BLE001 - stage is a standalone script
            print(f"[{idx}] API error: {error}")
            decision = "EXCLUDE"
            justification = "Screening failed due to API error."
            validation = "Validation: INVALID\nReason: Screening error."

        print(f"[{idx}] {decision} - {justification}")

        if "INVALID" in validation:
            invalid_cases += 1
            validation_status = "INVALID"
            print(f"[{idx}] INVALID screening detected")
        else:
            validation_status = "VALID"
            write_audit_entry(paper.get("paperId"), decision, validation_status)

        all_screening_results.append(
            {
                "paperId": paper.get("paperId"),
                "paper_index": idx,
                "title": title,
                "decision": decision,
                "justification": justification,
                "validation": validation_status,
                "validation_raw": validation,
            }
        )

        # Only papers that are both INCLUDED and VALIDATED enter the filtered
        # corpus that the retrieval stage later indexes.
        if decision == "INCLUDE" and validation_status == "VALID":
            included_papers.append(
                {
                    "paperId": paper.get("paperId"),
                    "title": title,
                    "decision": decision,
                    "justification": justification,
                }
            )

    os.makedirs(PROCESSED_DIR, exist_ok=True)
    with open(FILTERED_PAPERS_PATH, "w", encoding="utf-8") as handle:
        json.dump(included_papers, handle, ensure_ascii=False, indent=4)
    with open(SCREENING_LOG_PATH, "w", encoding="utf-8") as handle:
        json.dump(all_screening_results, handle, ensure_ascii=False, indent=4)

    included = sum(1 for r in all_screening_results if r["decision"] == "INCLUDE")
    excluded = sum(1 for r in all_screening_results if r["decision"] == "EXCLUDE")

    print("=== END SCREENING RUN ===")
    print("\n=== Screening Statistics ===")
    print("Total papers:", len(all_screening_results))
    print("Included:", included)
    print("Excluded:", excluded)
    print("Invalid:", invalid_cases)
    print("\nFiltered corpus ready for retrieval indexing.")


if __name__ == "__main__":
    main()
