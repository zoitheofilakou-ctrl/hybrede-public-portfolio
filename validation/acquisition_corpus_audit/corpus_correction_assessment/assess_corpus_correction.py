#!/usr/bin/env python3
"""Focused prospective corpus-correction assessment for one paperId."""

from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "validation" / "acquisition_corpus_audit" / "corpus_correction_assessment"
SCRIPT = OUT / "assess_corpus_correction.py"
REPORT = OUT / "corpus_correction_assessment.md"
MANIFEST = OUT / "corpus_correction_manifest.csv"
DECISION_LOG = OUT / "decision_log_update.md"
GENERATED = (REPORT, MANIFEST, DECISION_LOG)

PAPER_ID = "aeb5a82400a2ea187d74d60d53cb000a06f8e881"
DOI = "10.2196/16606"
PUBMED = "32224481"
PMC = "7154940"
PDF_REL = "data/harvested_pdfs/Use of Artificial Intelligence for Medical Literature Search Randomized Controlled Trial Using the H.pdf"
TEXT_REL = f"data/fulltext/{PAPER_ID}.txt"

METADATA = ROOT / "data" / "hybrede_metadata_v5.json"
SCREENING = ROOT / "data" / "processed" / "screening_log.json"
FILTERED = ROOT / "data" / "processed" / "filtered_papers.json"
AUDIT_LOG = ROOT / "data" / "processed" / "audit_log.json"
SCREENING_CODE = ROOT / "screening" / "llm_screening.py"
PRIOR_REPORT = ROOT / "validation" / "acquisition_corpus_audit" / "acquisition_corpus_audit.md"
PRIOR_IDENTITY = ROOT / "validation" / "acquisition_corpus_audit" / "full_text_identity_audit.csv"
PRIOR_MANIFEST = ROOT / "validation" / "acquisition_corpus_audit" / "acquisition_corpus_manifest.csv"
MANUAL_REVIEW = ROOT / "validation" / "acquisition_corpus_audit" / "manual_identity_review" / "unresolved_fulltext_manual_review.csv"


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def select(rows: list[dict], paper_id: str) -> list[dict]:
    return [row for row in rows if row.get("paperId") == paper_id]


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).casefold().strip()


def pdf_text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def main() -> int:
    conflicts = [rel(path) for path in GENERATED if path.exists()]
    if conflicts:
        print("Refusing to overwrite existing output(s):", *conflicts, sep="\n", file=sys.stderr)
        return 2

    metadata_rows = select(load_json(METADATA), PAPER_ID)
    screening_rows = select(load_json(SCREENING), PAPER_ID)
    filtered_rows = select(load_json(FILTERED), PAPER_ID)
    audit_rows = select(load_json(AUDIT_LOG), PAPER_ID)
    identity_rows = select(read_csv(PRIOR_IDENTITY), PAPER_ID)
    corpus_rows = read_csv(PRIOR_MANIFEST)
    target_corpus_rows = select(corpus_rows, PAPER_ID)
    manual_rows = read_csv(MANUAL_REVIEW)
    screening_code = SCREENING_CODE.read_text(encoding="utf-8")
    prior_report = PRIOR_REPORT.read_text(encoding="utf-8")

    cardinalities = [
        len(metadata_rows), len(screening_rows), len(filtered_rows),
        len(audit_rows), len(identity_rows), len(target_corpus_rows),
    ]
    if cardinalities != [1, 1, 1, 1, 1, 1]:
        raise RuntimeError(f"Target evidence cardinality failure: {cardinalities}")
    if len(corpus_rows) != 107 or len(manual_rows) != 7:
        raise RuntimeError("Prior audit corpus/version-policy evidence has unexpected cardinality")

    metadata = metadata_rows[0]
    screening = screening_rows[0]
    identity = identity_rows[0]
    pdf_path = ROOT / PDF_REL
    text_path = ROOT / TEXT_REL
    if not pdf_path.is_file() or not text_path.is_file():
        raise FileNotFoundError("Target PDF or extracted text is missing")

    local_content = pdf_text(pdf_path) + "\n" + text_path.read_text(
        encoding="utf-8", errors="replace"
    )
    local_norm = normalized(local_content)
    invitation_markers = [
        "dear ladies and gentleman",
        "we are very happy to welcome you",
        "with your help",
        "we are looking forward to a very productive event",
        "virtual and augmented reality in surgical education",
    ]
    if not all(marker in local_norm for marker in invitation_markers):
        raise RuntimeError("Required internal invitation evidence was not found")
    if DOI in local_norm:
        raise RuntimeError("Unexpected main-article DOI found in invitation asset")

    external = metadata.get("externalIds", {})
    authors = metadata.get("authors", [])
    abstract = (metadata.get("abstract") or "").strip()
    required_abstract_sections = ["background", "objective", "methods", "results", "conclusions"]
    structured_abstract = all(
        re.search(rf"\b{label}\b", abstract, re.IGNORECASE)
        for label in required_abstract_sections
    )
    identifiers_valid = (
        external.get("DOI") == DOI
        and str(external.get("PubMed")) == PUBMED
        and str(external.get("PubMedCentral")) == PMC
    )
    metadata_article_evidence = (
        identifiers_valid
        and len(authors) == 7
        and "randomized controlled trial" in metadata.get("title", "").casefold()
        and structured_abstract
        and all(term in abstract.casefold() for term in ["three groups", "results", "conclusions"])
    )
    criteria_present = all(term in screening_code for term in [
        "healthcare research", "application of knowledge", "digital tools",
        "healthcare research contexts",
    ])
    screening_consistent = (
        screening.get("decision") == "INCLUDE"
        and screening.get("validation") == "VALID"
        and "AI search engine" in screening.get("justification", "")
        and criteria_present
    )
    prior_reconciliation_closed = (
        "Reconciliation status: **RESOLVED_BY_SAVED_EVIDENCE**" in prior_report
        and len({row["paperId"] for row in corpus_rows}) == 107
    )
    version_policy_evidence = all(
        row.get("title_correspondence")
        and row.get("author_correspondence")
        and row.get("abstract_or_content_correspondence")
        for row in manual_rows
    )

    local_document_classification = "event_invitation_or_participation_document"
    local_fulltext_eligible = False
    metadata_eligibility = (
        "eligible_scientific_article" if metadata_article_evidence and screening_consistent
        else "unresolved"
    )
    abstract_validity = (
        "valid_substantive_scientific_abstract"
        if metadata_article_evidence and structured_abstract
        else "unresolved"
    )
    recommended_representation = (
        "abstract_only"
        if metadata_eligibility == "eligible_scientific_article"
        and abstract_validity == "valid_substantive_scientific_abstract"
        else "unresolved"
    )
    composition = (
        "26 full text + 81 abstract only = 107"
        if recommended_representation == "abstract_only"
        and prior_reconciliation_closed and version_policy_evidence
        else "UNRESOLVED"
    )
    historical_screening_effect = (
        "NO_CHANGE_TO_INCLUDE_DECISION; correct only the erroneous full-text source classification"
        if recommended_representation == "abstract_only" else "UNRESOLVED"
    )
    overall = (
        "CORPUS_SOURCE_CORRECTION_REQUIRED"
        if composition != "UNRESOLVED" else "UNRESOLVED"
    )

    manifest_row = {
        "paperId": PAPER_ID,
        "metadata_title": metadata.get("title", ""),
        "metadata_doi": external.get("DOI", ""),
        "metadata_pubmed": external.get("PubMed", ""),
        "metadata_pmc": external.get("PubMedCentral", ""),
        "metadata_author_count": len(authors),
        "metadata_abstract_structure": "Background; Objective; Methods; Results; Conclusions" if structured_abstract else "unresolved",
        "local_pdf_path": PDF_REL,
        "local_text_path": TEXT_REL,
        "local_document_classification": local_document_classification,
        "local_fulltext_eligible": str(local_fulltext_eligible).lower(),
        "metadata_record_eligibility": metadata_eligibility,
        "abstract_validity": abstract_validity,
        "historical_representation": identity.get("document_classification", ""),
        "recommended_source_representation": recommended_representation,
        "historical_screening_effect": historical_screening_effect,
        "corrected_composition": composition,
        "prospective_only": "true",
    }
    with MANIFEST.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest_row))
        writer.writeheader()
        writer.writerow(manifest_row)

    report = f"""# Focused Corpus-Correction Assessment

Generated: {datetime.now(timezone.utc).isoformat()}

## Scope

This assessment concerns only `{PAPER_ID}` and keeps two evidentiary objects separate:

1. the locally stored event invitation/participation document; and
2. the metadata-described randomized controlled trial.

## Local document

- PDF: `{PDF_REL}`
- Extracted text: `{TEXT_REL}`
- Classification: **{local_document_classification}**
- Eligible full-text representation: **false**

Document-internal evidence includes “Dear Ladies and Gentleman,” “we are very happy to welcome you,” “with your help,” and “we are looking forward to a very productive event.” It is headed “Virtual and Augmented Reality in Surgical Education.” It does not print the metadata article title, DOI, seven-author byline, research abstract, methods, results, or conclusions. The metadata acquisition URL contains `_app1.pdf`.

The asset is therefore an event invitation/participation document associated with the hackathon, not the substantive main RCT manuscript. It must be preserved as historical audit evidence but excluded from future indexing.

## Metadata-described record

- Title: {metadata.get('title', '')}
- DOI: `{external.get('DOI', '')}`
- PubMed: `{external.get('PubMed', '')}`
- PMC: `{external.get('PubMedCentral', '')}`
- Authors: **{len(authors)}**
- Year: **{metadata.get('year', '')}**
- Eligibility decision: **{metadata_eligibility}**

The metadata has mutually consistent article-level identifiers, seven authors, an RCT title, and a substantive structured research abstract. The abstract states Background, Objective, Methods, Results, and Conclusions; describes three study groups, the IRIS.AI intervention, scoring results, and a scientific conclusion. It is not invitation, promotional, editorial, or call-for-participation prose.

The subject—evaluation of an AI literature-search tool in medical research—matches the original inclusion concepts for healthcare research, digital tools, knowledge use, and healthcare research contexts. The saved screening row records `INCLUDE` with `VALID` validation on that basis. No new eligibility criterion is introduced.

## Abstract validity and representation

- Abstract decision: **{abstract_validity}**
- Recommended future representation: **{recommended_representation}**
- Effect on historical screening: **{historical_screening_effect}**

This is a prospective correction of an erroneous acquired full-text/source-classification outcome. It is not a new screening decision. The RCT record remains included, while the invitation asset must not supply its indexed text.

## Approved version policy

The seven separately reviewed documents have affirmative scientific-work correspondence and substantive main-manuscript content. Under the approved policy, identifiable preprints or author manuscripts are eligible full-text representations. They remain retained and their identity assessment is not reopened.

## Corrected pre-index composition

**{composition}**

Basis: the other 26 historical full-text inputs remain eligible; the target moves from erroneous full text to its valid abstract; the 80 other historical abstract-only records remain unchanged; and the 109/107 screening reconciliation remains closed. No corrected segment count is calculated.

## Minimum future rerun boundary

- Corpus-selection manifest: **CORRECTION_REQUIRED**
- Selected source representations: **REGENERATION_REQUIRED**
- ChromaDB: **REBUILD_REQUIRED**
- BM25: **REBUILD_REQUIRED**
- Retrieval: **RERUN_REQUIRED**
- Generation: **RERUN_REQUIRED**
- Same 11 evaluation queries: **RERUN_REQUIRED_FOR_COMPARABILITY**
- Manuscript counts and numerical claims: **UPDATE_REQUIRED_AFTER_CORRECTED_RUNS**
- Acquisition: **NOT_REQUIRED**
- Screening: **NOT_REQUIRED**

No correction or rerun was performed.

## Overall status

**{overall}**

## Safety

Only the four approved assessment files were created. No source evidence, prior audit, corpus file, index, evaluation output, or manuscript was modified. No pipeline stage or external service was used.
"""
    REPORT.write_text(report, encoding="utf-8")

    decision = f"""# Corpus-Correction Decision Log

## Record

- paperId: `{PAPER_ID}`
- Metadata title: {metadata.get('title', '')}

## Decisions

- Local-document classification: `{local_document_classification}`
- Local document eligible as full text: `false`
- Metadata-record eligibility: `{metadata_eligibility}`
- Abstract validity: `{abstract_validity}`
- Recommended source representation: `{recommended_representation}`
- Corrected composition: `{composition}`
- Historical screening effect: `{historical_screening_effect}`

## Scientific rationale

The acquired `_app1.pdf` asset is internally an event invitation/participation document, whereas the metadata describes a seven-author RCT with DOI `{DOI}`, PubMed `{PUBMED}`, PMC `{PMC}`, and a structured scientific abstract. The source error is confined to full-text acquisition/classification. Correcting it does not introduce a new screening criterion and does not reverse the supported INCLUDE decision.

## Prospective action

Preserve the invitation PDF and extracted text as audit evidence. In a future controlled corpus correction, prevent them from being indexed for this paperId and select the validated metadata title and abstract instead. Then regenerate corpus representations, rebuild both indexes, repeat retrieval and generation evaluation using the same 11 queries, and update manuscript numerical claims from the corrected artifacts.

No action was implemented by this assessment.
"""
    DECISION_LOG.write_text(decision, encoding="utf-8")

    print(json.dumps({
        "status": "success",
        "files": [rel(SCRIPT), rel(REPORT), rel(MANIFEST), rel(DECISION_LOG)],
        "paperId": PAPER_ID,
        "local_document_classification": local_document_classification,
        "metadata_record_eligibility": metadata_eligibility,
        "abstract_validity": abstract_validity,
        "recommended_source_representation": recommended_representation,
        "corrected_composition": composition,
        "historical_screening_effect": historical_screening_effect,
        "overall_status": overall,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
