"""Configurable filesystem layout for the sanitized HyBreDe pipeline.

The original group project used a shared path module that is co-authored and is
therefore not redistributed in this public repository. This module is a fresh,
self-contained replacement written for the portfolio release.

Every location is environment-configurable, so nothing is tied to a particular
machine or user account.

Environment variables
---------------------
HYBREDE_DATA_DIR       Root data directory (default: ./data)
HYBREDE_METADATA_PATH  Metadata corpus JSON produced by the acquisition stage
"""

from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.getenv("HYBREDE_DATA_DIR", "data")).resolve()
PROCESSED_DIR = DATA_DIR / "processed"

METADATA_PATH = Path(
    os.getenv("HYBREDE_METADATA_PATH", str(PROCESSED_DIR / "metadata.json"))
)
FILTERED_PAPERS_PATH = PROCESSED_DIR / "filtered_papers.json"
SCREENING_LOG_PATH = PROCESSED_DIR / "screening_log.json"
AUDIT_LOG_PATH = PROCESSED_DIR / "audit_log.json"


def ensure_parent_dir(path: os.PathLike | str) -> None:
    """Create the parent directory of *path* if it does not yet exist."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
