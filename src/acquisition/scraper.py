"""Automated metadata acquisition from the Semantic Scholar Graph API.

Stage 1 of the HyBreDe pipeline. Collects bibliographic *metadata only*
(title, abstract, year, identifiers, citation count) for a set of topical
queries, deduplicates by paper identifier, and writes a metadata corpus for
the downstream LLM screening stage.

No full-text or publisher content is downloaded by this module.

Sanitization notes for the public release
-----------------------------------------
* The API key is read from the environment. No credential is embedded.
* Output locations come from `src.common.paths` and are environment
  configurable; no machine-specific path is present.
* The original file imported a co-authored shared path module, which is not
  redistributed here; that import was replaced.

Environment variables
---------------------
SEMANTIC_SCHOLAR_API_KEY  Required. Obtain your own key from Semantic Scholar.
"""

from __future__ import annotations

import json
import os
import time

import requests

from src.common.paths import METADATA_PATH, ensure_parent_dir

API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
BASE_URL = "https://api.semanticscholar.org/graph/v1"

# Semantic Scholar rate limit for an approved key is 1 request/second.
# A slightly longer delay avoids sporadic 429 responses.
REQUEST_DELAY_SECONDS = 1.1

if API_KEY is None:
    raise ValueError(
        "SEMANTIC_SCHOLAR_API_KEY is not set. Copy .env.example to .env and "
        "provide your own key."
    )


def fetch_papers(search_query: str, result_limit: int = 10) -> list[dict]:
    """Retrieve paper metadata for one query.

    Restricted to 2020-2024 and to the specific fields required by the
    screening and retrieval stages.
    """
    search_endpoint = f"{BASE_URL}/paper/search"
    params = {
        "query": search_query,
        "limit": result_limit,
        "year": "2020-2024",
        "fields": "title,abstract,year,externalIds,url,citationCount",
    }
    headers = {"x-api-key": API_KEY}

    print(f"[*] Initializing search for query: '{search_query}'")
    try:
        response = requests.get(search_endpoint, params=params, headers=headers)
        time.sleep(REQUEST_DELAY_SECONDS)

        if response.status_code == 200:
            papers_found = response.json().get("data", [])
            print(f"[+] Successfully retrieved {len(papers_found)} papers.")
            return papers_found

        print(f"[!] API request failed. Status code: {response.status_code}")
        return []
    except Exception as error:  # noqa: BLE001 - stage is a standalone script
        print(f"[!] An unexpected system error occurred: {error}")
        return []


def deduplicate(papers: list[dict]) -> list[dict]:
    """Remove repeated records, keyed on the Semantic Scholar paperId."""
    seen_ids: set[str] = set()
    unique: list[dict] = []
    for paper in papers:
        pid = paper.get("paperId")
        if pid and pid not in seen_ids:
            seen_ids.add(pid)
            unique.append(paper)
    return unique


# Topical queries defining the review scope. Each contributes result_limit
# records before deduplication.
SEARCH_TASKS = [
    "AI assistant healthcare professionals",
    "large language model clinical practice",
    "RAG system medical literature",
    "LLM clinical decision support",
    "evidence-based practice AI researchers",
    "clinical decision support systems",
    "systematic review automation",
    "retrieval augmented generation medical",
    "human oversight AI healthcare",
    "information overload healthcare",
]


def main() -> None:
    all_papers: list[dict] = []
    print("=== STARTING MULTI-TOPIC METADATA HARVESTING ===")

    for keyword in SEARCH_TASKS:
        all_papers.extend(fetch_papers(keyword, result_limit=20))

    unique_papers = deduplicate(all_papers)
    print(
        f"[*] After dedup: {len(unique_papers)} unique papers "
        f"(from {len(all_papers)} total)"
    )

    if not unique_papers:
        print("[!] No data collected. Please check API status or network.")
        return

    ensure_parent_dir(METADATA_PATH)
    with open(METADATA_PATH, "w", encoding="utf-8") as json_file:
        json.dump(unique_papers, json_file, ensure_ascii=False, indent=4)

    print("-" * 50)
    print(f"SUCCESS: {len(unique_papers)} papers exported to '{METADATA_PATH}'")
    print("ACTION: ready for the LLM screening stage.")
    print("-" * 50)


if __name__ == "__main__":
    main()
