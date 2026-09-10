# Examples

This directory intentionally contains **no corpus data**.

## Why it is empty of data

The original research corpus is copyrighted journal literature and cannot be
redistributed. See [DATA_POLICY.md](../DATA_POLICY.md). Shipping a "small sample" of
publisher PDFs would be the same copyright problem at smaller scale, so nothing is
shipped.

## What a compliant sample corpus would look like

If you want to add one — for your own fork, or as a contribution — every item must be
individually verified as redistributable. "It was freely downloadable" is not a licence.

A compliant sample would be:

```
examples/sample_corpus/
  LICENSES.md              # per-item: DOI, title, licence, source URL, verified date
  <doi-or-id>.pdf          # only if that item's licence permits redistribution
  <doi-or-id>.txt          # extracted text, same licence constraint
```

`LICENSES.md` must record, for every item:

| Field | Example |
|---|---|
| DOI / identifier | `10.2196/12345` |
| Title | … |
| Licence | CC BY 4.0 / CC0 / public domain |
| Source URL | canonical publisher or repository URL |
| Verified on | date the licence was checked |

Acceptable licences: **CC0**, **CC BY**, **CC BY-SA**, or unambiguous public domain.
Anything else — including "free to read", "open access" without a stated licence, or
publisher-hosted PDFs with no licence statement — does not qualify.

## Trying the pipeline without a corpus

You do not need a full-text corpus to exercise the included stages:

1. **Acquisition** (`python -m src.acquisition.scraper`) retrieves bibliographic
   metadata only — titles and abstracts. No publisher content is downloaded, so there
   is no redistribution question for the metadata you generate locally.
2. **Screening** (`python -m src.screening.llm_screening`) runs entirely on those
   titles and abstracts.

Together those two stages demonstrate the acquisition and screening design end to end
using only metadata you fetched yourself under your own API key.

Full-text acquisition, indexing, retrieval and generation are described in
[`docs/architecture.md`](../docs/architecture.md) but are not included here — partly
for copyright reasons, partly because the retrieval and generation modules were
principally authored by capstone collaborators. See
[CONTRIBUTIONS.md](../CONTRIBUTIONS.md).
