#!/usr/bin/env python3
"""Focused local identity review for seven historical full-text inputs.

Reads only frozen local evidence, verifies expected document-internal markers,
and exclusively creates the three review reports. Pipeline modules are never
imported or executed.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "validation" / "acquisition_corpus_audit" / "manual_identity_review"
SCRIPT = OUT / "review_unresolved_fulltexts.py"
REPORT = OUT / "unresolved_fulltext_manual_review.md"
CSV_REPORT = OUT / "unresolved_fulltext_manual_review.csv"
DECISION_LOG = OUT / "decision_log_update.md"
GENERATED = (REPORT, CSV_REPORT, DECISION_LOG)

METADATA_PATH = ROOT / "data" / "hybrede_metadata_v5.json"
PRIOR_IDENTITY_PATH = ROOT / "validation" / "acquisition_corpus_audit" / "full_text_identity_audit.csv"
PRIOR_MANIFEST_PATH = ROOT / "validation" / "acquisition_corpus_audit" / "acquisition_corpus_manifest.csv"
PRIOR_REPORT_PATH = ROOT / "validation" / "acquisition_corpus_audit" / "acquisition_corpus_audit.md"

TARGET_IDS = [
    "2447a02f940138c22c8858c0e658506ccfc093df",
    "3db0040e40ee57f1f221012553def945c35c853b",
    "3eff0e1187dbd60f12dd06c5f3291b1eb6858c1a",
    "4be46ae53206440cfa6cab48f7523df5a701a65f",
    "67a6f9678537221edffcd02818af9af484944bb0",
    "79c814a7e19670a241d8a991590f944ca6a7db3d",
    "e37bce2e0ce6e176e9afbb96d9b97cd000bf16f7",
]

ALLOWED_CLASSIFICATIONS = {
    "main_published_article", "accepted_manuscript",
    "supplementary_or_appendix", "unrelated_document", "unresolved",
}
ALLOWED_STATUSES = {"SUPPORTED", "MISMATCH", "MANUAL_REVIEW_REQUIRED"}
ALLOWED_REPRESENTATIONS = {
    "retain_full_text", "abstract_fallback_required", "unresolved_pending_manual_check",
}

# Decisions are conservative because the allowed classification vocabulary has
# no "preprint" category. Affirmative correspondence is recorded separately,
# while exact document version remains unresolved.
DECISIONS = {
    TARGET_IDS[0]: {
        "document_title": "Evaluating the Human Safety Net: Observational study of Physician Responses to Unsafe AI Recommendations in high-fidelity Simulation",
        "document_doi": "10.1101/2023.10.03.23296437",
        "document_authors": "Paul Festor; Myura Nagendran; Anthony C. Gordon; A. Aldo Faisal; Matthieu Komorowski",
        "document_year": "2023",
        "journal_or_venue_evidence": "medRxiv; version posted October 3, 2023",
        "explicit_document_type_label": "medRxiv preprint; not certified by peer review",
        "title_correspondence": "Exact substantive title match.",
        "doi_correspondence": "Exact DOI match.",
        "author_correspondence": "All metadata authors correspond; document expands initials/names.",
        "abstract_or_content_correspondence": "Document abstract and simulation study content correspond to the metadata-described work.",
        "confidence": "high",
        "exact_evidence": "First page prints the complete title, the five corresponding authors, DOI 10.1101/2023.10.03.23296437, and the medRxiv preprint notice.",
        "remaining_uncertainty": "Local evidence establishes the correct work but only as an uncertified preprint; no published or accepted-manuscript version is established locally.",
        "required_markers": ["10.1101/2023.10.03.23296437", "Evaluating the Human Safety Net", "preprint"],
    },
    TARGET_IDS[1]: {
        "document_title": "Predictors of Healthcare Practitioners' Intention to Use AI-Enabled Clinical Decision Support Systems (AI-CDSSs): A Meta-Analysis Based on the Unified Theory of Acceptance and Use of Technology (UTAUT)",
        "document_doi": "10.2196/preprints.57224",
        "document_authors": "Julius Dingel; Anne-Kathrin Kleine; Julia Cecil; Anna Sigl; Eva Lermer; Susanne Gaube",
        "document_year": "2024",
        "journal_or_venue_evidence": "JMIR Preprints; submitted to Journal of Medical Internet Research on February 15, 2024",
        "explicit_document_type_label": "unpublished, peer-reviewed preprint; Original Manuscript",
        "title_correspondence": "Substantive exact match; document expands AI-CDSS and UTAUT.",
        "doi_correspondence": "Related but not exact: metadata DOI is 10.2196/57224; document prints 10.2196/preprints.57224.",
        "author_correspondence": "All six metadata authors correspond; document supplies full names.",
        "abstract_or_content_correspondence": "Meta-analysis objective and UTAUT content correspond.",
        "confidence": "high",
        "exact_evidence": "First pages print the matching title and six authors, identify JMIR Preprints, state 'unpublished, peer-reviewed preprint,' and print DOI 10.2196/preprints.57224.",
        "remaining_uncertainty": "The metadata open-access filename suggests 'accepted,' but the document itself calls this an unpublished preprint; published/accepted status cannot be assigned.",
        "required_markers": ["JMIR Preprints", "unpublished, peer-reviewed preprint", "Julius Dingel"],
    },
    TARGET_IDS[2]: {
        "document_title": "Bio-SIEVE: Exploring Instruction Tuning Large Language Models for Systematic Review Automation",
        "document_doi": "",
        "document_authors": "Ambrose Robinson; William Thorne; Ben Wu; Abdullah Pandor; Munira Essat; Mark Stevenson; Xingyi Song",
        "document_year": "2023",
        "journal_or_venue_evidence": "Local document does not establish a published venue; metadata links an arXiv record.",
        "explicit_document_type_label": "Preprint. Under review.",
        "title_correspondence": "Exact title match.",
        "doi_correspondence": "Metadata DOI is 10.48550/arXiv.2308.06610; no DOI is printed in the inspected document.",
        "author_correspondence": "All seven metadata authors correspond; abbreviated metadata names are expanded.",
        "abstract_or_content_correspondence": "Bio-SIEVE abstract and systematic-review screening content correspond.",
        "confidence": "high",
        "exact_evidence": "Document heading prints the exact title and seven corresponding authors; internal footer states 'Preprint. Under review.'",
        "remaining_uncertainty": "The correct work is established, but the local document is explicitly an under-review preprint and no accepted or published version is established.",
        "required_markers": ["Bio-SIEVE", "Ambrose", "Preprint.Underreview"],
    },
    TARGET_IDS[3]: {
        "document_title": "Zero-shot Generative Large Language Models for Systematic Review Screening Automation",
        "document_doi": "",
        "document_authors": "Shuai Wang; Harrisen Scells; Shengyao Zhuang; Martin Potthast; Bevan Koopman; Guido Zuccon",
        "document_year": "2024",
        "journal_or_venue_evidence": "Metadata DOI 10.1007/978-3-031-56027-9_25 identifies a Springer conference chapter; local PDF does not print that DOI or venue.",
        "explicit_document_type_label": "No explicit published/accepted label in inspected local document.",
        "title_correspondence": "Exact title match.",
        "doi_correspondence": "Metadata DOI is absent from the local document.",
        "author_correspondence": "All six metadata authors correspond.",
        "abstract_or_content_correspondence": "Abstract and systematic-review screening study content correspond.",
        "confidence": "high",
        "exact_evidence": "First page prints the exact title, all six authors, February 2, 2024, and the matching abstract.",
        "remaining_uncertainty": "Correspondence to the work is strong, but the local copy does not establish whether it is the published Springer chapter, accepted manuscript, or an earlier author/preprint version.",
        "required_markers": ["Zero-shot Generative Large Language Models", "Shuai Wang", "Guido Zuccon"],
    },
    TARGET_IDS[4]: {
        "document_title": "Explainable AI in Healthcare: Systematic Review of Clinical Decision Support Systems",
        "document_doi": "10.1101/2024.08.10.24311735",
        "document_authors": "Noor A. Aziz; Awais Manzoor; Muhammad Deedahwar Mazhar Qureshi; M. Atif Qureshi; Wael Rashwan",
        "document_year": "2024",
        "journal_or_venue_evidence": "medRxiv; version posted August 10, 2024",
        "explicit_document_type_label": "medRxiv preprint; not certified by peer review",
        "title_correspondence": "Exact title match.",
        "doi_correspondence": "Exact DOI match.",
        "author_correspondence": "Metadata authors correspond, though metadata compresses/omits parts of compound author names.",
        "abstract_or_content_correspondence": "Systematic-review abstract, scope, and CDSS/XAI content correspond.",
        "confidence": "high",
        "exact_evidence": "First page prints the exact title, corresponding author group, DOI 10.1101/2024.08.10.24311735, and medRxiv preprint notice.",
        "remaining_uncertainty": "Local evidence establishes the correct work but only as an uncertified preprint.",
        "required_markers": ["10.1101/2024.08.10.24311735", "Explainable AI in Healthcare", "preprint"],
    },
    TARGET_IDS[5]: {
        "document_title": "Systematic review automation tool use by systematic reviewers, health technology assessors and clinical guideline developers: tools used, abandoned, and desired",
        "document_doi": "10.1101/2021.04.26.21255833",
        "document_authors": "Anna Mae Scott; Connor Forbes; Justin Clark; Matt Carter; Paul Glasziou; Zachary Munn",
        "document_year": "2021",
        "journal_or_venue_evidence": "medRxiv; version posted April 30, 2021",
        "explicit_document_type_label": "medRxiv preprint; not certified by peer review",
        "title_correspondence": "Exact title match apart from terminal punctuation.",
        "doi_correspondence": "Exact DOI match.",
        "author_correspondence": "All six metadata authors correspond; initials/full names reconcile.",
        "abstract_or_content_correspondence": "Survey objective, methods, and tool-use results correspond.",
        "confidence": "high",
        "exact_evidence": "First page prints the complete title, all six authors, DOI 10.1101/2021.04.26.21255833, and medRxiv preprint notice.",
        "remaining_uncertainty": "Local evidence establishes the correct work but only as an uncertified preprint.",
        "required_markers": ["10.1101/2021.04.26.21255833", "Systematic review automation tool use", "preprint"],
    },
    TARGET_IDS[6]: {
        "document_title": "Citation screening using large language models for creating clinical practice guidelines: A protocol for a prospective study",
        "document_doi": "10.1101/2023.12.29.23300652",
        "document_authors": "Takehiko Oami; Yohei Okada; Taka-aki Nakada",
        "document_year": "2023",
        "journal_or_venue_evidence": "medRxiv; version posted December 31, 2023",
        "explicit_document_type_label": "medRxiv preprint; not certified by peer review",
        "title_correspondence": "Exact title match.",
        "doi_correspondence": "Exact DOI match.",
        "author_correspondence": "All three metadata authors correspond; initials/full names reconcile.",
        "abstract_or_content_correspondence": "Protocol abstract and guideline citation-screening objective correspond.",
        "confidence": "high",
        "exact_evidence": "First page prints the exact title, all three authors, DOI 10.1101/2023.12.29.23300652, and medRxiv preprint notice.",
        "remaining_uncertainty": "Local evidence establishes the correct work but only as an uncertified preprint.",
        "required_markers": ["10.1101/2023.12.29.23300652", "Citation screening using large language models", "preprint"],
    },
}


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def pdf_text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def compact(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def main() -> int:
    conflicts = [rel(path) for path in GENERATED if path.exists()]
    if conflicts:
        print("Refusing to overwrite existing output(s):", *conflicts, sep="\n", file=sys.stderr)
        return 2

    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    metadata_by_id = {row["paperId"]: row for row in metadata}
    prior_identity = read_csv(PRIOR_IDENTITY_PATH)
    prior_by_id = {row["paperId"]: row for row in prior_identity}
    prior_manifest = read_csv(PRIOR_MANIFEST_PATH)
    _ = PRIOR_REPORT_PATH.read_text(encoding="utf-8")

    if set(TARGET_IDS) != set(DECISIONS):
        raise RuntimeError("Decision set does not exactly equal the seven approved paperIds")
    if len(prior_manifest) != 107 or len(prior_identity) != 27:
        raise RuntimeError("Frozen prior audit cardinalities do not match 107/27")

    rows = []
    for paper_id in TARGET_IDS:
        metadata_row = metadata_by_id[paper_id]
        prior = prior_by_id[paper_id]
        text_path = ROOT / prior["text_path"]
        document_path = ROOT / prior["pdf_path"]
        if not text_path.is_file() or not document_path.is_file():
            raise FileNotFoundError(f"Missing approved local evidence for {paper_id}")
        evidence = pdf_text(document_path) + "\n" + text_path.read_text(
            encoding="utf-8", errors="replace"
        )
        missing_markers = [
            marker for marker in DECISIONS[paper_id]["required_markers"]
            if compact(marker) not in compact(evidence)
        ]
        if missing_markers:
            raise RuntimeError(f"Internal evidence marker failure for {paper_id}: {missing_markers}")

        decision = DECISIONS[paper_id]
        row = {
            "paperId": paper_id,
            "metadata_title": metadata_row.get("title", ""),
            "document_path": rel(document_path),
            "document_title": decision["document_title"],
            "metadata_doi": metadata_row.get("externalIds", {}).get("DOI", "") or "",
            "document_doi": decision["document_doi"],
            "metadata_authors": "; ".join(a.get("name", "") for a in metadata_row.get("authors", [])),
            "document_authors": decision["document_authors"],
            "metadata_year": metadata_row.get("year", ""),
            "document_year": decision["document_year"],
            "journal_or_venue_evidence": decision["journal_or_venue_evidence"],
            "explicit_document_type_label": decision["explicit_document_type_label"],
            "title_correspondence": decision["title_correspondence"],
            "doi_correspondence": decision["doi_correspondence"],
            "author_correspondence": decision["author_correspondence"],
            "abstract_or_content_correspondence": decision["abstract_or_content_correspondence"],
            "document_classification": "unresolved",
            "identity_status": "MANUAL_REVIEW_REQUIRED",
            "confidence": decision["confidence"],
            "manual_review_required": "true",
            "exact_evidence_supporting_decision": decision["exact_evidence"],
            "remaining_uncertainty": decision["remaining_uncertainty"],
            "recommended_future_source_representation": "unresolved_pending_manual_check",
        }
        if row["document_classification"] not in ALLOWED_CLASSIFICATIONS:
            raise RuntimeError("Invalid classification")
        if row["identity_status"] not in ALLOWED_STATUSES:
            raise RuntimeError("Invalid identity status")
        if row["recommended_future_source_representation"] not in ALLOWED_REPRESENTATIONS:
            raise RuntimeError("Invalid representation")
        rows.append(row)

    fields = list(rows[0])
    with CSV_REPORT.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    combined = []
    for old in prior_identity:
        if old["paperId"] in TARGET_IDS:
            new = next(row for row in rows if row["paperId"] == old["paperId"])
            combined.append({
                "paperId": old["paperId"],
                "document_classification": new["document_classification"],
                "manual_review_required": new["manual_review_required"],
            })
        else:
            combined.append({
                "paperId": old["paperId"],
                "document_classification": old["document_classification"],
                "manual_review_required": old["manual_review_required"],
            })
    class_counts = Counter(row["document_classification"] for row in combined)
    manual_count = sum(row["manual_review_required"].casefold() == "true" for row in combined)
    composition = "UNRESOLVED" if manual_count else "26 full text + 81 abstract only"
    overall = "MANUAL_VERSION_REVIEW_REQUIRED"

    record_sections = []
    for row in rows:
        record_sections.append(f"""### `{row['paperId']}`

- Metadata title: {row['metadata_title']}
- Document path: `{row['document_path']}`
- Document title: {row['document_title']}
- Metadata DOI: `{row['metadata_doi'] or 'not recorded'}`
- Document DOI: `{row['document_doi'] or 'not printed'}`
- Metadata authors: {row['metadata_authors']}
- Document authors: {row['document_authors']}
- Metadata year: {row['metadata_year']}
- Document year: {row['document_year']}
- Venue evidence: {row['journal_or_venue_evidence']}
- Explicit document-type label: {row['explicit_document_type_label']}
- Title correspondence: {row['title_correspondence']}
- DOI correspondence: {row['doi_correspondence']}
- Author correspondence: {row['author_correspondence']}
- Abstract/content correspondence: {row['abstract_or_content_correspondence']}
- Document classification: `{row['document_classification']}`
- Identity status: `{row['identity_status']}`
- Confidence: `{row['confidence']}`
- Manual review required: `{row['manual_review_required']}`
- Exact evidence: {row['exact_evidence_supporting_decision']}
- Remaining uncertainty: {row['remaining_uncertainty']}
- Recommended future representation: `{row['recommended_future_source_representation']}`
""")

    report = f"""# Focused Manual Identity Review

Generated: {datetime.now(timezone.utc).isoformat()}

## Scope and method

This review is restricted to the seven approved historical full-text inputs. It compares complete metadata with internal PDF and extracted-text evidence: printed title, authors, DOI, year, venue, explicit version labels, abstract, and substantive structure. Filenames, paperIds, technical readability, extraction success, and topic similarity are linkage evidence only.

The local documents affirmatively correspond to their linked scientific works. However, the permitted classification vocabulary has no preprint category, and internal evidence does not establish any of the seven as the main published article or an accepted manuscript. Their exact usable document version therefore remains unresolved.

## Record-level decisions

{chr(10).join(record_sections)}

## Combined classification across all 27 historical full-text inputs

- `main_published_article`: **{class_counts.get('main_published_article', 0)}**
- `accepted_manuscript`: **{class_counts.get('accepted_manuscript', 0)}**
- `supplementary_or_appendix`: **{class_counts.get('supplementary_or_appendix', 0)}**
- `unrelated_document`: **{class_counts.get('unrelated_document', 0)}**
- `unresolved`: **{class_counts.get('unresolved', 0)}**
- Records requiring manual review: **{manual_count}**

## Corrected composition

**{composition}**

The known supplementary target remains designated for abstract fallback, but all other 26 historical full texts have not yet been positively classified as published articles or accepted manuscripts. The exact remaining action is to establish, from authoritative bibliographic/version evidence, whether each of these seven local preprint/author copies is an acceptable corpus full-text version or to obtain and validate the published/accepted version later. No corrected segment count is calculated.

## Rerun boundary

- Corpus source selection: **REQUIRED**, after the known supplementary record is changed to abstract fallback and the seven version decisions are closed.
- Index construction: **REQUIRED_AFTER_CORPUS_SOURCE_SELECTION**.
- Retrieval evaluation: **REQUIRED_AFTER_INDEX_REBUILD**.
- Generation evaluation: **REQUIRED_AFTER_INDEX_REBUILD**.
- Same 11 evaluation queries: **REQUIRED_FOR_COMPARABILITY**.
- Manuscript numerical claims: **REQUIRED_AFTER_CORRECTED_INDEX_AND_EVALUATIONS**.

The new evidence does not move the rerun boundary earlier than corpus source selection. Acquisition and screening remain outside the minimum rerun boundary.

## Overall review status

**{overall}**

## Safety

Only the four approved review files were created. No prior audit, corpus source, metadata, screening record, PDF, extracted text, index, evaluation output, or manuscript was modified. No pipeline stage or external service was used.
"""
    REPORT.write_text(report, encoding="utf-8")

    decision_lines = [
        "# Focused Identity Review Decision Log",
        "",
        "All seven records have affirmative title/author/content correspondence, but their exact document version remains unresolved:",
        "",
    ]
    for row in rows:
        decision_lines.extend([
            f"## `{row['paperId']}`",
            "",
            f"- Classification: `{row['document_classification']}`",
            f"- Identity status: `{row['identity_status']}`",
            f"- Confidence: `{row['confidence']}`",
            f"- Recommended representation: `{row['recommended_future_source_representation']}`",
            f"- Reason: {row['remaining_uncertainty']}",
            "",
        ])
    decision_lines.extend([
        "## Combined conclusion",
        "",
        f"- Corrected composition: **{composition}**",
        f"- Records requiring manual review: **{manual_count}**",
        f"- Overall status: **{overall}**",
        "- No corrected segment count was calculated.",
        "",
    ])
    DECISION_LOG.write_text("\n".join(decision_lines), encoding="utf-8")

    print(json.dumps({
        "status": "success",
        "files": [rel(SCRIPT), rel(REPORT), rel(CSV_REPORT), rel(DECISION_LOG)],
        "reviewed": [{
            "paperId": row["paperId"],
            "classification": row["document_classification"],
            "identity_status": row["identity_status"],
            "confidence": row["confidence"],
            "recommended_representation": row["recommended_future_source_representation"],
        } for row in rows],
        "combined_27_classifications": dict(sorted(class_counts.items())),
        "manual_review_required": manual_count,
        "corrected_composition": composition,
        "overall_review_status": overall,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
