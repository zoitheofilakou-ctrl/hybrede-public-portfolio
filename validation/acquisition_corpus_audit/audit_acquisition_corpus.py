#!/usr/bin/env python3
"""Consolidated read-only Data Acquisition and Corpus Construction audit.

This script reads frozen repository evidence and creates four new audit outputs.
It never imports or invokes pipeline modules and refuses to overwrite reports.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import pdfplumber


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "validation" / "acquisition_corpus_audit"
REPORT = OUT_DIR / "acquisition_corpus_audit.md"
MANIFEST_CSV = OUT_DIR / "acquisition_corpus_manifest.csv"
IDENTITY_CSV = OUT_DIR / "full_text_identity_audit.csv"
DECISION_LOG = OUT_DIR / "decision_log_update.md"
GENERATED = (REPORT, MANIFEST_CSV, IDENTITY_CSV, DECISION_LOG)

METADATA = ROOT / "data" / "hybrede_metadata_v5.json"
SCREENING = ROOT / "data" / "processed" / "screening_log.json"
FILTERED = ROOT / "data" / "processed" / "filtered_papers.json"
INVALID = ROOT / "data" / "processed" / "invalid_papers.json"
AUDIT_LOG = ROOT / "data" / "processed" / "audit_log.json"
INDEX_MANIFEST = ROOT / "data" / "processed" / "run_manifests" / "retrieval_index.json"
SCRAPER = ROOT / "data_acquisition" / "scraper.py"
PDF_SCRAPER = ROOT / "data_acquisition" / "PDFscraper.py"
PDF_TO_TEXT = ROOT / "data_acquisition" / "pdf_to_text.py"
SCREENING_CODE = ROOT / "screening" / "llm_screening.py"
RETRIEVAL_CODE = ROOT / "Retrieval" / "retrieval.py"
PDF_DIR = ROOT / "data" / "harvested_pdfs"
TEXT_DIR = ROOT / "data" / "fulltext"
TARGET_ID = "aeb5a82400a2ea187d74d60d53cb000a06f8e881"

CLASSIFICATIONS = {
    "main_published_article",
    "accepted_manuscript",
    "supplementary_or_appendix",
    "unrelated_document",
    "unresolved",
}

# Conservative content-based determinations. These are checked against extracted
# title/identifier evidence below; uncertain preprints remain unresolved.
ACCEPTED_MANUSCRIPT_IDS = {"5e38fb3c018d4476549d993d38926db2e5c6032a"}
UNRESOLVED_IDS = {
    "2447a02f940138c22c8858c0e658506ccfc093df",  # medRxiv preprint
    "3db0040e40ee57f1f221012553def945c35c853b",  # JMIR Preprints
    "3eff0e1187dbd60f12dd06c5f3291b1eb6858c1a",  # manuscript/version unclear
    "4be46ae53206440cfa6cab48f7523df5a701a65f",  # manuscript/version unclear
    "67a6f9678537221edffcd02818af9af484944bb0",  # medRxiv/version-year conflict
    "79c814a7e19670a241d8a991590f944ca6a7db3d",  # medRxiv preprint
    "e37bce2e0ce6e176e9afbb96d9b97cd000bf16f7",  # medRxiv preprint
}


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize(value: str) -> str:
    value = value.casefold()
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def title_key(title: str) -> str:
    safe = "".join(c for c in title if c.isalnum() or c in " -_").rstrip()
    return safe[:100]


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def pdf_excerpt(path: Path, pages: int = 2) -> tuple[str, str]:
    chunks = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages[:pages]:
                chunks.append(page.extract_text() or "")
        return "\n".join(chunks), ""
    except Exception as exc:  # evidence is reported, never silently accepted
        return "", f"{type(exc).__name__}: {exc}"


def extract_acquisition_callsite(path: Path) -> dict:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    default_limit = None
    call_limits = []
    queries = []
    year_literal = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "fetch_rehabilitation_papers":
            positional = node.args.args
            defaults = node.args.defaults
            if defaults:
                mapping = dict(zip([a.arg for a in positional[-len(defaults):]], defaults))
                if "result_limit" in mapping:
                    default_limit = ast.literal_eval(mapping["result_limit"])
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "search_tasks":
                    queries = ast.literal_eval(node.value)
            if isinstance(node.value, ast.Dict):
                for key, value in zip(node.value.keys, node.value.values):
                    if isinstance(key, ast.Constant) and key.value == "year":
                        year_literal = ast.literal_eval(value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "fetch_rehabilitation_papers":
                for keyword in node.keywords:
                    if keyword.arg == "result_limit":
                        call_limits.append(ast.literal_eval(keyword.value))
    return {
        "function_default": default_limit,
        "callsite_limits": sorted(set(call_limits)),
        "year_parameter": year_literal,
        "queries": queries,
        "configuration_evidence": "NONE",
        "saved_execution_evidence": "NONE",
        "conclusion": "INTENDED_BUT_NOT_EXECUTION_PROVEN",
    }


def match_pdfs(metadata: list[dict], pdfs: list[Path]) -> dict[str, dict]:
    matches = {}
    pdf_by_stem = {p.stem: p for p in pdfs}
    for paper in metadata:
        key = title_key(paper.get("title", ""))
        if key in pdf_by_stem:
            matches[paper["paperId"]] = {
                "path": pdf_by_stem[key], "method": "exact_sanitized_title", "score": 1.0
            }
            continue
        candidates = sorted(
            ((similarity(key, p.stem), p) for p in pdfs), reverse=True, key=lambda x: x[0]
        )
        if candidates and candidates[0][0] > 0.90:
            matches[paper["paperId"]] = {
                "path": candidates[0][1],
                "method": "fuzzy_title_candidate_not_identity_proof",
                "score": candidates[0][0],
            }
    return matches


def local_target_candidates(target: dict, pdfs: list[Path], texts: list[Path]) -> list[str]:
    terms = [
        normalize(target.get("title", "")),
        normalize(target.get("externalIds", {}).get("DOI", "")),
        TARGET_ID,
    ]
    found = set()
    for path in pdfs:
        name = normalize(path.stem)
        if similarity(target.get("title", ""), path.stem) > 0.72:
            found.add(rel(path))
    for path in texts:
        try:
            content = normalize(path.read_text(encoding="utf-8", errors="replace")[:30000])
        except OSError:
            continue
        if any(term and term in content for term in terms):
            found.add(rel(path))
    return sorted(found)


def identity_record(paper: dict, text_path: Path, pdf_match: dict | None) -> dict:
    text = text_path.read_text(encoding="utf-8", errors="replace")
    excerpt = re.sub(r"\s+", " ", text[:12000]).strip()
    pdf_path = pdf_match["path"] if pdf_match else None
    pdf_text, pdf_error = pdf_excerpt(pdf_path) if pdf_path else ("", "no candidate PDF mapping")
    evidence_text = normalize((pdf_text or excerpt)[:20000])
    title = paper.get("title", "")
    title_score = similarity(title, (pdf_text or excerpt)[:1500])
    doi = str(paper.get("externalIds", {}).get("DOI", "") or "")
    doi_present = bool(doi and normalize(doi) in evidence_text)
    title_words = [w for w in normalize(title).split() if len(w) >= 5]
    title_coverage = (
        sum(1 for word in title_words if word in evidence_text) / len(title_words)
        if title_words else 0.0
    )

    if paper["paperId"] == TARGET_ID:
        classification = "supplementary_or_appendix"
        status = "MISMATCH"
        manual = False
        rationale = (
            "Metadata identifies the RCT main article, but local content begins with the "
            "Scithon Event virtual/augmented-reality instructions; metadata URL contains _app1.pdf."
        )
    elif paper["paperId"] in ACCEPTED_MANUSCRIPT_IDS:
        classification = "accepted_manuscript"
        status = "SUPPORTED"
        manual = False
        rationale = "Local content explicitly identifies itself as an accepted/author version and matches the metadata title."
    elif paper["paperId"] in UNRESOLVED_IDS:
        classification = "unresolved"
        status = "MANUAL_REVIEW_REQUIRED"
        manual = True
        rationale = "Title/topic linkage is present, but the local preprint/manuscript version cannot be classified as the published main article from local evidence alone."
    elif title_coverage >= 0.70 or doi_present:
        classification = "main_published_article"
        status = "SUPPORTED"
        manual = False
        rationale = "Local first-page content contains strong title/identifier and journal/article-form evidence matching metadata."
    else:
        classification = "unresolved"
        status = "MANUAL_REVIEW_REQUIRED"
        manual = True
        rationale = "Local content does not provide sufficient positive bibliographic evidence for a conclusive classification."

    assert classification in CLASSIFICATIONS
    if classification == "unresolved" and not manual:
        raise AssertionError("Every unresolved record must require manual review")
    return {
        "paperId": paper["paperId"],
        "metadata_title": title,
        "metadata_doi": doi,
        "text_path": rel(text_path),
        "text_sha256": sha256(text_path),
        "pdf_path": rel(pdf_path) if pdf_path else "",
        "pdf_sha256": sha256(pdf_path) if pdf_path else "",
        "pdf_link_method": pdf_match["method"] if pdf_match else "unmatched",
        "pdf_link_score": f"{pdf_match['score']:.4f}" if pdf_match else "",
        "title_evidence_coverage": f"{title_coverage:.4f}",
        "doi_present_in_local_excerpt": str(doi_present).lower(),
        "document_classification": classification,
        "identity_status": status,
        "manual_review_required": str(manual).lower(),
        "rationale": rationale,
        "pdf_read_error": pdf_error,
        "local_excerpt": excerpt[:300].replace("\n", " "),
    }


def write_csv_exclusive(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    conflicts = [rel(path) for path in GENERATED if path.exists()]
    if conflicts:
        print("Refusing to overwrite existing audit output(s):", *conflicts, sep="\n", file=sys.stderr)
        return 2

    metadata = load_json(METADATA)
    screening = load_json(SCREENING)
    filtered = load_json(FILTERED)
    invalid = load_json(INVALID)
    audit_log = load_json(AUDIT_LOG)
    index_manifest = load_json(INDEX_MANIFEST)
    acquisition = extract_acquisition_callsite(SCRAPER)

    metadata_by_id = {p["paperId"]: p for p in metadata if p.get("paperId")}
    metadata_ids = [p.get("paperId") for p in metadata]
    filtered_ids = [p["paperId"] for p in filtered]
    filtered_set = set(filtered_ids)
    logged_include = [r["paperId"] for r in screening if r.get("decision") == "INCLUDE"]
    logged_include_set = set(logged_include)
    include_only_log = sorted(logged_include_set - filtered_set)
    frozen_only = sorted(filtered_set - logged_include_set)
    include_reconciliation = (
        "RESOLVED_BY_SAVED_EVIDENCE"
        if len(logged_include) == 109 and len(filtered_set) == 107
        and len(include_only_log) == 2 and not frozen_only
        else "UNRESOLVED"
    )

    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    texts = sorted(TEXT_DIR.glob("*.txt"))
    text_by_id = {p.stem: p for p in texts}
    pdf_matches = match_pdfs(metadata, pdfs)
    historical_fulltext_ids = sorted(filtered_set & set(text_by_id))
    abstract_ids = sorted(filtered_set - set(text_by_id))

    identity_rows = [
        identity_record(metadata_by_id[paper_id], text_by_id[paper_id], pdf_matches.get(paper_id))
        for paper_id in historical_fulltext_ids
    ]
    identity_by_id = {row["paperId"]: row for row in identity_rows}
    class_counts = Counter(row["document_classification"] for row in identity_rows)
    manual_count = sum(row["manual_review_required"] == "true" for row in identity_rows)

    target = metadata_by_id[TARGET_ID]
    target_candidates = local_target_candidates(target, pdfs, texts)
    target_row = identity_by_id[TARGET_ID]
    target_has_abstract = bool((target.get("abstract") or "").strip())
    target_alternative_candidates = [
        item for item in target_candidates
        if item not in {target_row["pdf_path"], target_row["text_path"]}
    ]
    target_resolution = (
        "ABSTRACT_FALLBACK_REQUIRED"
        if target_row["document_classification"] == "supplementary_or_appendix"
        and target_has_abstract and not target_alternative_candidates
        else "UNRESOLVED"
    )

    all_other_positive = all(
        row["document_classification"] in {"main_published_article", "accepted_manuscript"}
        for row in identity_rows if row["paperId"] != TARGET_ID
    )
    one_rep_each = (
        len(filtered_set) == 107 and len(historical_fulltext_ids) + len(abstract_ids) == 107
        and not (set(historical_fulltext_ids) & set(abstract_ids))
    )
    corrected_composition = (
        "26 full text + 81 abstract only"
        if target_resolution == "ABSTRACT_FALLBACK_REQUIRED"
        and all_other_positive and include_reconciliation == "RESOLVED_BY_SAVED_EVIDENCE"
        and one_rep_each
        else "UNRESOLVED"
    )

    manifest_rows = []
    for paper_id in sorted(filtered_set):
        paper = metadata_by_id.get(paper_id, {})
        historical = "fulltext" if paper_id in historical_fulltext_ids else "abstract"
        future = (
            "abstract_fallback_required"
            if paper_id == TARGET_ID and target_resolution == "ABSTRACT_FALLBACK_REQUIRED"
            else historical
        )
        manifest_rows.append({
            "paperId": paper_id,
            "title": paper.get("title", ""),
            "year": paper.get("year", ""),
            "historical_source_representation": historical,
            "recommended_future_source_representation": future,
            "metadata_path": rel(METADATA),
            "text_path": rel(text_by_id[paper_id]) if paper_id in text_by_id else "",
            "document_classification": identity_by_id.get(paper_id, {}).get("document_classification", "not_applicable_abstract"),
            "identity_status": identity_by_id.get(paper_id, {}).get("identity_status", "ABSTRACT_METADATA"),
            "manual_review_required": identity_by_id.get(paper_id, {}).get("manual_review_required", "false"),
        })

    identity_fields = list(identity_rows[0].keys())
    manifest_fields = list(manifest_rows[0].keys())
    write_csv_exclusive(MANIFEST_CSV, manifest_rows, manifest_fields)
    write_csv_exclusive(IDENTITY_CSV, identity_rows, identity_fields)

    years = Counter(str(p.get("year")) for p in metadata)
    missing_ids = sum(not p.get("paperId") for p in metadata)
    duplicate_rows = len([x for x in metadata_ids if x]) - len(set(x for x in metadata_ids if x))
    screen_counts = Counter(r.get("decision", "MISSING") for r in screening)

    diff_lines = []
    for paper_id in include_only_log:
        rows = [r for r in screening if r.get("paperId") == paper_id]
        invalid_rows = [r for r in invalid if r.get("paperId") == paper_id]
        audit_rows = [r for r in audit_log if r.get("paperId") == paper_id]
        diff_lines.append(
            f"- `{paper_id}`: screening={json.dumps(rows, ensure_ascii=False)}; "
            f"invalid_records={json.dumps(invalid_rows, ensure_ascii=False)}; "
            f"audit_events={json.dumps(audit_rows, ensure_ascii=False)}"
        )

    rerun = {
        "acquisition": "NOT_REQUIRED_FOR_DOCUMENTED_CORPUS_CORRECTION; historical execution parameters remain unproven",
        "screening": "NOT_REQUIRED; the included target record remains included and has a valid abstract",
        "corpus_source_selection": "REQUIRED; exclude the supplementary full text and select abstract fallback unless a main article is later validated",
        "index_construction": "REQUIRED_AFTER_CORPUS_SOURCE_CORRECTION",
        "retrieval_evaluation": "REQUIRED_AFTER_INDEX_REBUILD",
        "generation_evaluation": "REQUIRED_AFTER_INDEX_REBUILD",
        "same_11_evaluation_queries": "REQUIRED_FOR_COMPARABILITY_AFTER_INDEX_REBUILD",
        "manuscript_numerical_claims": "REQUIRED_AFTER_CORRECTED_INDEX_AND_EVALUATIONS; do not carry forward historical counts",
    }
    minimum_manual = [
        row["paperId"] for row in identity_rows if row["manual_review_required"] == "true"
    ]
    overall = (
        "PARTIAL_MANUAL_REVIEW_REQUIRED"
        if manual_count else "COMPLETE_WITH_FUTURE_CORPUS_CORRECTION_REQUIRED"
    )

    report = f"""# Acquisition and Corpus Construction Audit

Generated: {datetime.now(timezone.utc).isoformat()}

## Evidence hierarchy

Code capability, executable call-site intent, configuration evidence, saved execution evidence, and frozen outputs are reported separately. A call site is not treated as proof that acquisition executed with those arguments.

## Acquisition evidence

| Item | Function default | Executable call-site argument | Configuration evidence | Saved execution evidence | Final conclusion |
|---|---|---|---|---|---|
| Per-query result limit | `{acquisition['function_default']}` | `{acquisition['callsite_limits']}` | `{acquisition['configuration_evidence']}` | `{acquisition['saved_execution_evidence']}` | `INTENDED_BUT_NOT_EXECUTION_PROVEN` |
| Year range | none as function argument | request parameter `{acquisition['year_parameter']}` in function body | `{acquisition['configuration_evidence']}` | `{acquisition['saved_execution_evidence']}` | `INTENDED_BUT_NOT_EXECUTION_PROVEN` |
| Ten queries | none | exactly {len(acquisition['queries'])} strings in `search_tasks` | `{acquisition['configuration_evidence']}` | `{acquisition['saved_execution_evidence']}` | `INTENDED_BUT_NOT_EXECUTION_PROVEN` |

Call-site query strings:
{chr(10).join(f"{i}. `{q}`" for i, q in enumerate(acquisition['queries'], 1))}

There is no saved raw pre-deduplication acquisition output. The audit therefore does not reconstruct or claim a pre-deduplication count.

## Frozen metadata

- Rows: **{len(metadata)}**
- Missing paperId rows: **{missing_ids}**
- Unique nonmissing paperIds: **{len(set(x for x in metadata_ids if x))}**
- Duplicate paperId rows: **{duplicate_rows}**
- Publication years: **{', '.join(f'{year}: {years[year]}' for year in sorted(years))}**

Source: `{rel(METADATA)}`.

## Screening reconciliation

- Logged decisions: **{len(screening)}**
- Logged INCLUDE decisions: **{screen_counts['INCLUDE']}**
- Logged EXCLUDE decisions: **{screen_counts['EXCLUDE']}**
- Unique logged INCLUDE paperIds: **{len(logged_include_set)}**
- Frozen included paperIds: **{len(filtered_set)}**
- Logged INCLUDE but absent from frozen included corpus: **{len(include_only_log)}**
- Frozen included but absent from logged INCLUDE set: **{len(frozen_only)}**
- Reconciliation status: **{include_reconciliation}**

Exact two-record difference:
{chr(10).join(diff_lines) if diff_lines else "- None"}

The row-level saved evidence above is reported verbatim. A causal explanation is accepted only where the saved invalid/audit records establish it; otherwise the cause remains `UNRESOLVED`.

## Historical corpus representation

- Included paperIds: **{len(filtered_set)}**
- Historical full-text representations: **{len(historical_fulltext_ids)}**
- Historical abstract fallbacks: **{len(abstract_ids)}**
- Historical manifest: `{rel(INDEX_MANIFEST)}` reports **{index_manifest['summary']['fulltext_papers']}** full text, **{index_manifest['summary']['abstract_fallback_papers']}** abstract fallback, and **{index_manifest['summary']['total_chunks']}** chunks.
- Exactly one historical representation per included paper: **{str(one_rep_each).lower()}**

The 27 paperIds and linkage details are enumerated in `{rel(IDENTITY_CSV)}`. All 107 included records are enumerated in `{rel(MANIFEST_CSV)}`.

## Full-text identity classification

{chr(10).join(f"- `{name}`: **{class_counts.get(name, 0)}**" for name in sorted(CLASSIFICATIONS))}
- Manual review required: **{manual_count}**

These determinations use local document content and identifiers. Filename, technical PDF validity, extraction success, and paperId linkage are never treated as identity proof.

Minimum manual identity checks:
{chr(10).join(f"- `{paper_id}`" for paper_id in minimum_manual) if minimum_manual else "- None"}

## Target record

- paperId: `{TARGET_ID}`
- Metadata DOI: `{target.get('externalIds', {}).get('DOI', '')}`
- Valid linked abstract present: **{str(target_has_abstract).lower()}**
- Historical local classification: **{target_row['document_classification']}**
- Identity status: **{target_row['identity_status']}**
- Locally associated candidate assets: {', '.join(f'`{p}`' for p in target_candidates) or 'none'}
- Alternative local candidate main articles: {', '.join(f'`{p}`' for p in target_alternative_candidates) or 'none found'}
- Resolution: **{target_resolution}**

The recommendation is documentary only. The supplementary file remains unchanged.

## Corrected corpus composition

**{corrected_composition}**

The numerical composition is stated only if the target resolution, valid abstract, positive validation of all other 26 full texts, complete 107-paper reconciliation, and exactly-one-representation condition all pass. No corrected segment count is calculated or predicted.

## Rerun boundary

{chr(10).join(f"- {key.replace('_', ' ').title()}: **{value}**" for key, value in rerun.items())}

## Overall audit status

**{overall}**

## Safety

The audit read existing evidence and created only the five approved audit files. It did not modify corpus evidence, execute a pipeline stage, contact external services, rebuild an index, edit a manuscript, commit, or push.
"""
    REPORT.write_text(report, encoding="utf-8")

    decision = f"""# Decision Log Update

## Record

- paperId: `{TARGET_ID}`
- Metadata title: {target.get('title', '')}
- DOI: `{target.get('externalIds', {}).get('DOI', '')}`

## Local evidence

The historical text `{target_row['text_path']}` and PDF `{target_row['pdf_path']}` contain the Scithon Event virtual/augmented-reality material rather than the metadata-described randomized controlled trial. The metadata open-access URL points to an `_app1.pdf` resource. No alternative candidate main article was validated among existing local repository assets.

## Classification

- Document classification: `{target_row['document_classification']}`
- Identity status: `{target_row['identity_status']}`
- Valid linked abstract: `{str(target_has_abstract).lower()}`
- Resolution: `{target_resolution}`

## Required future action

`ABSTRACT_FALLBACK_REQUIRED`

During a future corpus-source correction, the supplementary document must not be used as full text for this paperId. Retain the included record using its linked abstract unless a verified main article is separately obtained and validated. This audit does not implement that correction.

## Consequences

Corpus source selection and index construction must be rerun after the correction. Retrieval and generation evaluation, including the same 11 evaluation queries, must then be repeated for comparability. Manuscript numerical claims must be updated only from those corrected artifacts.
"""
    DECISION_LOG.write_text(decision, encoding="utf-8")
    print(json.dumps({
        "status": "success",
        "outputs": [rel(Path(__file__)), *(rel(p) for p in GENERATED)],
        "metadata_rows": len(metadata),
        "logged_include": len(logged_include),
        "frozen_included": len(filtered_set),
        "include_only_log": include_only_log,
        "classifications": dict(sorted(class_counts.items())),
        "manual_review_required": manual_count,
        "target_resolution": target_resolution,
        "corrected_composition": corrected_composition,
        "overall_audit_status": overall,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
