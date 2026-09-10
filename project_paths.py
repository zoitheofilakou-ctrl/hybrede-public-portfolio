import os


BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# PUBLIC RELEASE SANITIZATION
# ---------------------------
# In the private research checkout every path below resolved underneath the
# repository itself, because the corpus and the frozen runtime lived there.
# Neither is distributed with this public release, so each root is resolved
# from an environment variable first and only falls back to the in-repo
# location. No machine-specific path is baked into this file: a user who sets
# nothing gets repository-relative paths, and a user who keeps their corpus or
# evidence store elsewhere points these variables at it.
#
#   HYBREDE_DATA_DIR       corpus / metadata root      (default: <repo>/data)
#   HYBREDE_RAG_STORE_DIR  Chroma + lexical index root (default: <repo>/rag_store)
#
# Path *layout* below the roots is unchanged from the research implementation,
# so an evidence store built by this code is byte-for-byte compatible.
DATA_DIR = os.path.abspath(os.environ.get("HYBREDE_DATA_DIR", os.path.join(BASE_DIR, "data")))
PROCESSED_DIR = os.path.join(DATA_DIR, "processed")

# Canonical project files and directories
METADATA_PATH = os.path.join(DATA_DIR, "hybrede_metadata_v5.json")
FILTERED_PAPERS_PATH = os.path.join(PROCESSED_DIR, "filtered_papers.json")
SCREENING_LOG_PATH = os.path.join(PROCESSED_DIR, "screening_log.json")
AUDIT_LOG_PATH = os.path.join(PROCESSED_DIR, "audit_log.json")
HARVESTED_PDFS_DIR = os.path.join(DATA_DIR, "harvested_pdfs")
FULLTEXT_DIR = os.path.join(DATA_DIR, "fulltext")
CORRECTED_SOURCES_DIR = os.path.join(DATA_DIR, "corrected_sources")
CORPUS_SOURCE_MANIFEST_PATH = os.path.join(PROCESSED_DIR, "corpus_source_manifest_v3.json")
# Evaluation runs may point retrieval at a prospectively verified disposable
# copy. The frozen research index is NOT distributed with this repository:
# supply your own compatible evidence store via HYBREDE_RAG_STORE_DIR, or build
# one with `python Retrieval/retrieval.py index` (see README, "Running the system").
RAG_STORE_DIR = os.path.abspath(
    os.environ.get("HYBREDE_RAG_STORE_DIR", os.path.join(BASE_DIR, "rag_store"))
)
RUN_MANIFEST_DIR = os.path.join(PROCESSED_DIR, "run_manifests")


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def ensure_parent_dir(path: str) -> str:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path
