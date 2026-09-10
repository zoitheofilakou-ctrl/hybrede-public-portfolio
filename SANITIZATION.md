# Sanitization record

Every difference between the code in this repository and the private research
implementation it was taken from. The private source was **not modified**: it was
copied, and the copy was changed.

**Source of record:** the frozen presentation implementation, branch
`presentation/demo-release-v1`, commit `ed3692054b327313d7a8092513c49672c7c70d98`,
verified clean before and after the copy.

## Summary

There were **no secrets to remove**. Every credential in the source already came from
an environment variable, and no hardcoded key, token, password, private key,
collaborator email address, internal university URL or absolute machine path was found
anywhere in the copied code. The historical Semantic Scholar credential that once
existed in the private repository is not present in this frozen state and is not in any
file published here.

The changes below are therefore about **decoupling the code from data that is not
distributed**, not about redacting secrets.

## Code changes

### 1. `project_paths.py` — configurable corpus root

`DATA_DIR` was fixed at `<repo>/data`, because in the research checkout the corpus
lived inside the repository. It now resolves from `HYBREDE_DATA_DIR` and falls back to
`<repo>/data`.

`RAG_STORE_DIR` already honoured `HYBREDE_RAG_STORE_DIR` upstream and is unchanged; only
its comment was updated to state that the frozen index is not distributed.

*Behavioural effect:* none when the variable is unset. Path layout below the roots is
unchanged, so an evidence store built by this code is compatible with the original.

### 2. `Retrieval/retrieval.py` — resolvable source-manifest paths

Full-text paths in the corpus source manifest were resolved with
`os.path.join(BASE_DIR, selected)` at two sites — always relative to the repository
root. A user-supplied corpus can live anywhere, so both sites now call a new
`resolve_manifest_path()`: absolute paths are honoured, otherwise the repository root is
tried first and the configured data root second.

*Behavioural effect:* none for a repository-relative manifest, which still resolves at
the first candidate exactly as before. A frozen manifest is unaffected.

### 3. `app.py` — evidence-base figures annotated

The interface displays the composition of the frozen research evidence base (105
records, 715 segments). Those constants are **unchanged**, so the published interface is
inspectable exactly as evaluated, but a comment now states that they describe a corpus
which is not distributed and will not describe a store you build yourself.

*Behavioural effect:* none. Comment only. See [Known caveat](#known-caveat).

### 4. `requirements-lock.txt` — re-encoded

See the packaging table below. Content unchanged; encoding only.

### 5. Nothing else

`llm/rag_generator.py`, `llm/interface.py`, `screening/llm_screening.py`,
`console_utils.py`, `run_manifest.py`, `immutable_index.py`, `data_acquisition/*` and
`tests/*` are **byte-identical to the frozen source**. No retrieval, ranking, gating,
verification or generation logic was altered.

## Configuration and packaging changes

| File | Change |
|---|---|
| `.env.example` | Expanded to document every variable the code reads, including `HYBREDE_DATA_DIR`, `HYBREDE_RAG_STORE_DIR` and `HF_HOME`. No real value. |
| `.gitignore` | Hardened: explicit rules for `DEMO_RUNTIME/`, `FREEZE_BACKUPS/`, `corrected_sources/`, `*.bundle`, `*.zip`, `*.docx`, `chroma.sqlite3`, model binaries and the HF cache, on top of the existing `data/`, `rag_store/` and `*.pdf` rules. |
| `requirements.txt` | Replaced the acquisition-only subset with the real dependency set from the source. |
| `environment.yml` | Added from the source, unmodified. It contained no local path and no conda `prefix:`. |
| `requirements-lock.txt` | Added from the source and **re-encoded UTF-16 LE → UTF-8**. It was a Windows `pip freeze` artifact, which git and GitHub treat as binary; as UTF-16 it could not be diffed, rendered or content-scanned. Package list and ordering are unchanged, and the decoded content was scanned clean (no path, credential or `file://` local install). |
| `src/` | **Removed.** It held re-layouts of four modules from the first portfolio commit. The repository now uses the project's real layout so imports work as written. |

## Model loading

Retrieval loads `all-MiniLM-L6-v2` and `cross-encoder/ms-marco-MiniLM-L-6-v2` with
`local_files_only=True`. This is upstream behaviour and is unchanged. No cache path is
hardcoded: the models are resolved through the standard Hugging Face cache, whose
location is chosen with `HF_HOME`. Nothing here refers to any author's cache directory.

## What was excluded, not sanitized

Some things could not be made safe by editing and were simply not copied. The full list
is in [DATA_POLICY.md](DATA_POLICY.md); in short: the corpus (metadata, abstracts,
extracted full text, corrected sources), the frozen Chroma store and lexical index,
publisher PDFs, evaluation result payloads containing corpus excerpts, the university
capstone deliverable document, `FREEZE_BACKUPS/`, `DEMO_RUNTIME/`, caches and logs.

## Known caveat

The interface reports the frozen evidence base as 105 records / 715 segments. If you
build your own index, those figures in the sidebar will not describe it. They are kept
so the evaluated interface is faithfully reproduced; edit `EVIDENCE_BASE_*` in `app.py`
if you point the system at your own corpus.

## Verification

- `python examples/smoke_test.py` — 17 checks, all passing, with no corpus, no evidence
  store and no API key.
- `python examples/smoke_test.py --build-index` — 19 checks, all passing: builds a real
  hybrid index from the synthetic corpus (7 segments across 3 records) and queries it.
- Test suite status is recorded in [tests/README.md](tests/README.md).
