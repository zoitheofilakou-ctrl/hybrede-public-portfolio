import streamlit as st
import streamlit.components.v1 as components
import html
import os
from dotenv import load_dotenv
from project_paths import FILTERED_PAPERS_PATH, RAG_STORE_DIR

load_dotenv()

try:
    from llm.rag_generator import generate_rag_answer
except Exception as exc:
    # Presentation-safe: the exception class is enough to diagnose a startup
    # failure, and the message can carry local paths or provider payloads.
    st.error(
        "The evidence pipeline could not be loaded, so the demo cannot start. "
        f"Failure class: {type(exc).__name__}. Full detail is in the server console."
    )
    st.stop()


def load_external_search():
    """Load the optional Semantic Scholar client on demand.

    data_acquisition.scraper raises at import time when SEMANTIC_SCHOLAR_API_KEY is
    unset. That optional tab must never prevent the evidence pipeline from starting,
    so the import is deferred until the feature is actually used.
    """
    try:
        from data_acquisition.scraper import fetch_rehabilitation_papers
    except Exception as exc:
        # Only the exception class is returned: the message can carry local paths
        # or an API-key-related payload, and this string reaches the interface.
        return None, type(exc).__name__
    return fetch_rehabilitation_papers, None


# PUBLICATION REFERENCE FIGURES - NOT LIVE RUNTIME COUNTS
# The constants below are fixed publication-reference figures describing the
# *frozen research evidence base* used for the published evaluation. They are
# historical scientific reference values, not a live count of whatever index the
# application is currently pointed at.
#
# That frozen corpus and its index are not distributed with this repository (see
# DATA_POLICY.md). The figures are kept verbatim so the published interface is
# inspectable exactly as evaluated. If you build your own evidence store its
# composition will differ, and these values will not describe it; the UI labels
# them as publication reference so they cannot be misread as runtime counts.
#
# Authoritative frozen evidence-base composition (data/processed/corpus_source_manifest_v3.json
# and data/processed/run_manifests/retrieval_index.json).
EVIDENCE_BASE_RECORDS = 105
EVIDENCE_BASE_FULLTEXT = 27
EVIDENCE_BASE_ABSTRACT = 78
EVIDENCE_BASE_SEGMENTS = 715

EVIDENCE_BASE_SUMMARY = (
    "Publication reference evidence base: 105 evidence-bearing records "
    "(27 full text · 78 abstract only) across 715 indexed evidence segments. "
    "107 records were retained in total; 2 had no usable text. These are frozen "
    "publication figures for the research corpus, not live counts for the index "
    "currently in use."
)

# Retrieval depth is fixed at the evaluated configuration and is deliberately not a
# user control: k is the number of distinct papers MMR selects after reranking, and
# altering it changes the excerpt set, the evidence-sufficiency assessment and the
# final disposition. The frozen evaluation entry points use k=5
# (llm/rag_generator.py evaluate_single_query / evaluate_query_batch).
EVALUATED_K = 5

# Presentation-only cap for the external Semantic Scholar tab. It is a display limit
# for unscreened discovery results and is intentionally separate from EVALUATED_K so
# that it can never reach the HyBreDe pipeline.
EXTERNAL_RESULT_LIMIT = 5

SUPPORTED_DISPOSITIONS = ("supported_answer", "bounded_partial")

TECHNICAL_FAILURE_MESSAGE = (
    "Technical failure — the response could not be completed safely."
)

CLAIM_VALIDATION_CAPTION = (
    "Claims shown here passed the pipeline's excerpt-identity, citation and "
    "entailment checks. Validation is automated; researcher judgement remains final."
)


def render_disposition(disposition):
    """Display the generator's final_disposition. Never recomputed in the UI."""
    if disposition == "supported_answer":
        st.success(
            "**Supported answer** — each rendered claim was checked against an approved "
            "excerpt (excerpt identity, citation and model-based entailment checks)."
        )
    elif disposition == "bounded_partial":
        st.warning(
            "**Bounded partial response** — only part of this question is supported by "
            "the retrieved evidence. The unsupported propositions are named explicitly "
            "and are deliberately not answered."
        )
    elif disposition == "evidence_gap":
        st.error(
            "**Evidence gap** — substantive generation was withheld because the retrieved "
            "excerpts do not establish the requested proposition(s)."
        )
    elif disposition == "technical_failure":
        st.error(
            "**Technical failure** — a processing or validation failure occurred after "
            "evidence assessment. This is a technical failure, not an evidence gap."
        )
    elif disposition:
        st.info(f"**Disposition:** {disposition}")


def _scope_items(value):
    """Normalise one contract scope field to renderable component identifiers.

    Read-only shaping of what the contract already contains: a bare string is
    treated as a single entry, non-sequence values yield nothing, and blank or
    whitespace-only entries are dropped because they would render as an empty
    line. Nothing is invented, reordered or recomputed.
    """
    if isinstance(value, str):
        value = [value]
    elif not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def render_scope(contract, disposition=None):
    """Show permitted/prohibited proposition scope when a contract is available.

    On a bounded partial the split between what was answered and what was
    deliberately withheld is the substance of the response, so the panel opens
    by default there and stays collapsed on the other dispositions.

    The heading is emitted only once there is something to put under it: if the
    contract carries no renderable scope, the whole section — expander included —
    is suppressed rather than shown empty.
    """
    if not isinstance(contract, dict):
        return
    permitted = _scope_items(contract.get("permitted_answer_scope"))
    prohibited = _scope_items(contract.get("prohibited_answer_scope"))
    labels = contract.get("unsupported_proposition_labels") or {}
    if not isinstance(labels, dict):
        labels = {}
    if not permitted and not prohibited:
        return
    with st.expander(
        "◈ Proposition scope for this response",
        expanded=(disposition == "bounded_partial"),
    ):
        st.markdown(
            "**Supported:** "
            + (", ".join(str(c) for c in permitted) if permitted else "none")
        )
        if prohibited:
            st.markdown("**Withheld — insufficient evidence:**")
            for component_id in prohibited:
                # Fall back to the component id when the contract has no label, or
                # supplies a blank one, so a bullet is never rendered empty.
                st.markdown(f"- {labels.get(component_id) or component_id}")
        st.caption(
            "Scope is taken from the generation contract produced by the pipeline; "
            "it is not recomputed by this interface. No evidence is attached to a "
            "withheld proposition."
        )


def sources_label(disposition, count):
    """Label the excerpt panel using semantics specific to each disposition.

    The approved/retrieved distinction is load-bearing: on the supported and bounded
    paths the pipeline returns the approved excerpt set, while on the evidence-gap
    path it returns excerpts that were retrieved and judged insufficient. These must
    never be given the same label.
    """
    if disposition in SUPPORTED_DISPOSITIONS:
        return f"◈ Approved evidence excerpts · {count}"
    if disposition == "evidence_gap":
        return f"◈ Retrieved literature — insufficient evidence · {count}"
    if disposition == "technical_failure":
        return f"◈ Approved evidence excerpts from this processing attempt · {count}"
    return f"◈ Evidence excerpts · {count}"


def sources_caption(disposition):
    """Caption matching the disposition-specific semantics of sources_label()."""
    if disposition in SUPPORTED_DISPOSITIONS:
        return (
            "These are the approved excerpts the validated claims were generated "
            "from — not the full retrieval set."
        )
    if disposition == "evidence_gap":
        return (
            "Retrieved from the screened evidence base and shown for transparency. "
            "None were judged sufficient to support the requested proposition(s), "
            "so no substantive answer was generated."
        )
    if disposition == "technical_failure":
        return (
            "Shown for transparency. Evidence assessment completed, but the response "
            "could not be produced and validated."
        )
    return "Shown for transparency."


def render_sources(sources, disposition):
    """Render evidence excerpts using only fields the generator actually supplies.

    Per-excerpt full-text/abstract provenance is deliberately not shown: text_source
    is absent from the live sources contract, and it is not reconstructed here. The
    corpus-level split for the publication reference corpus is stated in
    EVIDENCE_BASE_SUMMARY instead.
    Retrieval and reranking scores are also deliberately withheld — they are ranking
    signals, not measures of evidential strength.
    """
    if not sources:
        return
    with st.expander(sources_label(disposition, len(sources))):
        st.caption(sources_caption(disposition))
        st.caption(
            "Ordering follows the pipeline's returned order and should not be "
            "interpreted as evidence quality, methodological rigour or clinical validity."
        )
        st.caption(EVIDENCE_BASE_SUMMARY)
        st.markdown("---")

        for idx, source in enumerate(sources, start=1):
            if not isinstance(source, dict):
                continue
            rank = source.get("rank", idx)
            title_s = source.get("title") or "Unknown"
            st.markdown(f"**[{rank}] {title_s}**")

            meta_bits = []
            if source.get("year"):
                meta_bits.append(str(source.get("year")))
            if source.get("section"):
                meta_bits.append(f"section: {source.get('section')}")
            if meta_bits:
                st.caption(" · ".join(meta_bits))

            text = (source.get("text") or "").strip()
            if text:
                st.markdown(text)
            else:
                st.caption("No excerpt text available for this result.")

            if source.get("excerpt_id"):
                st.caption(f"Excerpt ID: {source.get('excerpt_id')}")
            if source.get("paperId"):
                st.caption(f"Paper ID: {source.get('paperId')}")
            url_s = source.get("url")
            if url_s and url_s != "N/A":
                st.link_button("↗ Open", url_s)
            st.markdown("---")


def _evidence_block_html(source, excerpt_id):
    """Render one approved excerpt together with the paper it came from."""
    if not isinstance(source, dict):
        return (
            '<div class="ev-item ev-item-missing">Approved excerpt '
            f'<code>{html.escape(str(excerpt_id))}</code> is not present in the '
            "returned source set, so no excerpt text is shown for it.</div>"
        )

    text = (source.get("text") or "").strip()
    quote = (
        f'<div class="ev-quote">{html.escape(text)}</div>'
        if text
        else '<div class="ev-quote ev-quote-empty">No excerpt text available.</div>'
    )

    rank = source.get("rank")
    rank_html = (
        f'<span class="ev-rank">[{html.escape(str(rank))}]</span>' if rank else ""
    )
    title = html.escape(str(source.get("title") or "Unknown"))

    meta_bits = []
    if source.get("year"):
        meta_bits.append(html.escape(str(source.get("year"))))
    if source.get("section"):
        meta_bits.append(html.escape(str(source.get("section"))))
    meta_html = (
        f'<div class="ev-meta">{" · ".join(meta_bits)}</div>' if meta_bits else ""
    )

    url = source.get("url")
    link_html = ""
    if url and url != "N/A" and str(url).startswith(("http://", "https://")):
        link_html = (
            f'<a class="ev-open" href="{html.escape(str(url), quote=True)}" '
            'target="_blank" rel="noopener noreferrer">↗ Open paper</a>'
        )

    ids_bits = []
    if source.get("paperId"):
        ids_bits.append("Paper ID " + html.escape(str(source.get("paperId"))))
    if source.get("excerpt_id"):
        ids_bits.append("Excerpt ID " + html.escape(str(source.get("excerpt_id"))))
    ids_html = f'<div class="ev-ids">{" · ".join(ids_bits)}</div>' if ids_bits else ""

    # Provenance stays visible; the excerpt itself sits behind a native <details>
    # control. The stored text is passed through unchanged (escaped only, never
    # summarised, rewritten, normalised or reconstructed).
    return (
        '<div class="ev-item">'
        '<div class="ev-src">'
        f'<div class="ev-src-main">{rank_html}<span class="ev-title">{title}</span></div>'
        f"{meta_html}{ids_html}{link_html}"
        "</div>"
        '<details class="ev-details">'
        '<summary class="ev-summary">View exact excerpt</summary>'
        f"{quote}"
        "</details>"
        "</div>"
    )


def render_claim_evidence(result):
    """Render each validated claim beside the approved excerpt(s) it was checked against.

    The claim → excerpt link is the pipeline's own validated mapping: every entry of
    structured_claim_validation["valid_claims"] declares excerpt_ids, and the generator
    has already rejected any claim whose excerpt IDs fail to resolve or whose declared
    paper_ids disagree with those excerpts. Resolution here is by exact excerpt_id
    equality only — never by title, citation text, ordering or fuzzy text matching.
    An unresolvable excerpt_id is reported as missing rather than paired with a guess.

    Returns the set of excerpt_ids actually rendered under a claim, so the caller
    can list only the approved excerpts that no rendered claim referenced.
    """
    if not isinstance(result, dict):
        return set()
    if result.get("final_disposition") not in SUPPORTED_DISPOSITIONS:
        return set()

    validation = result.get("structured_claim_validation")
    if not isinstance(validation, dict):
        return set()

    claims = validation.get("valid_claims")
    if not isinstance(claims, list):
        return set()
    claims = [claim for claim in claims if isinstance(claim, dict)]
    if not claims:
        return set()

    by_excerpt_id = {
        source.get("excerpt_id"): source
        for source in (result.get("sources") or [])
        if isinstance(source, dict) and source.get("excerpt_id")
    }

    st.markdown(
        '<div class="ev-section-head">Claims and the evidence they were checked against</div>',
        unsafe_allow_html=True,
    )

    used_excerpt_ids = set()
    total = len(claims)
    for index, claim in enumerate(claims, start=1):
        excerpt_ids = claim.get("excerpt_ids")
        excerpt_ids = excerpt_ids if isinstance(excerpt_ids, list) else []
        used_excerpt_ids.update(e for e in excerpt_ids if e in by_excerpt_id)

        blocks = "".join(
            _evidence_block_html(by_excerpt_id.get(excerpt_id), excerpt_id)
            for excerpt_id in excerpt_ids
        )
        if not blocks:
            blocks = (
                '<div class="ev-item ev-item-missing">No approved excerpt was '
                "declared for this claim.</div>"
            )

        tag_bits = [
            html.escape(str(claim.get(field)))
            for field in ("component_id", "evidence_strength")
            if claim.get(field)
        ]
        tags_html = (
            f'<div class="ev-tags">{" · ".join(tag_bits)}</div>' if tag_bits else ""
        )

        st.markdown(
            '<div class="ev-card">'
            '<div class="ev-head">'
            '<span class="ev-kicker">Validated claim</span>'
            f'<span class="ev-index">{index} / {total}</span>'
            "</div>"
            f'<div class="ev-claim">{html.escape(str(claim.get("claim_text") or ""))}</div>'
            f"{tags_html}"
            '<div class="ev-sub-kicker">Supporting evidence</div>'
            f"{blocks}"
            "</div>",
            unsafe_allow_html=True,
        )

    st.caption(CLAIM_VALIDATION_CAPTION)
    return used_excerpt_ids


def render_additional_evidence(sources, used_excerpt_ids):
    """List approved excerpts that no rendered claim referenced.

    Ordering, ranks and IDs are those returned by the pipeline; this only filters
    out the excerpts already shown under a claim so the same evidence is not
    rendered twice.
    """
    extras = [
        source for source in sources
        if isinstance(source, dict)
        and source.get("excerpt_id") not in used_excerpt_ids
    ]
    if not extras:
        return
    blocks = "".join(
        _evidence_block_html(source, source.get("excerpt_id")) for source in extras
    )
    st.markdown(
        '<details class="ev-extra">'
        '<summary class="ev-summary ev-extra-summary">Additional approved evidence '
        f"({len(extras)})</summary>"
        f'<div class="ev-extra-body">{blocks}</div>'
        "</details>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Approved excerpts that no rendered claim cited. Shown for completeness; "
        "ordering follows the pipeline and is not an evidence-quality ranking."
    )


def render_result(result):
    """Render one assistant response, branching on the generator's final_disposition.

    final_disposition is taken verbatim from the pipeline and is never recomputed
    here. Every field is accessed defensively: the generator has seven return paths
    and path-specific fields such as structured_claim_validation, generation_contract
    and citations are absent on several of them.
    """
    if not isinstance(result, dict):
        return

    disposition = result.get("final_disposition")
    sources = result.get("sources") or []

    render_disposition(disposition)

    answer = result.get("answer")
    if isinstance(answer, str) and answer.strip():
        st.markdown(answer)
    elif disposition == "technical_failure":
        st.markdown(TECHNICAL_FAILURE_MESSAGE)

    # Proposition scope names the supported and the deliberately withheld components.
    render_scope(result.get("generation_contract"), disposition)

    # Claim cards are gated on a supported disposition, so no evidence is ever
    # attached to a withheld proposition or shown on an evidence-gap response.
    used_excerpt_ids = render_claim_evidence(result)

    if used_excerpt_ids:
        # Claim-linked excerpts are already rendered above; only the remainder of
        # the approved set is listed, so no excerpt appears twice.
        render_additional_evidence(sources, used_excerpt_ids)
    else:
        render_sources(sources, disposition)


st.set_page_config(
    page_title="HyBreDe — Evidence Retrieval System",
    page_icon="⬡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── GLOBAL CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=Inter:wght@400;500;600&display=swap');

:root {
    --bg:      #f4efe8;
    --surface: #faf7f2;
    --surface2:#f0ece4;
    --surface3:#ede8df;
    --ink:     #0d1b2a;
    --ink2:    #1e3448;
    --muted:   #4a6377;
    --pale:    #e8f2f9;
    --cyan:    #0077aa;
    --teal:    #007c6e;
    --gold:    #c08000;
    --red:     #c0392b;
    --green:   #1a7a4a;
    --border:  rgba(13,27,42,0.12);
    --border2: rgba(13,27,42,0.22);
    --mono:    'DM Mono', monospace;
    --sans:    'Inter', sans-serif;
    --serif:   'DM Serif Display', serif;
}

*, *::before, *::after { box-sizing: border-box; }

html, body, [class*="css"],
.stApp, .main, [data-testid="stAppViewContainer"],
[data-testid="stMain"], [data-testid="block-container"] {
    font-family: var(--sans) !important;
    background-color: #f4efe8 !important;
    color: #0d1b2a !important;
}
.main .block-container {
    padding-top: 0 !important;
    padding-left: 2.2rem !important;
    padding-right: 2.2rem !important;
    padding-bottom: 3rem !important;
    max-width: 100% !important;
    background-color: #f4efe8 !important;
}

/* ── Hide Streamlit chrome, but keep header/toolbar in the DOM ──
   The sidebar expand control (stExpandSidebarButton) is rendered inside
   stToolbar, which is inside stHeader. display:none on either ancestor
   removes it, leaving no way to reopen a collapsed sidebar. */
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
#MainMenu,
.stDeployButton,
[data-testid="stAppDeployButton"] {
    display: none !important;
    visibility: hidden !important;
}

/* Header/toolbar retained but visually inert and click-through, so the
   custom HyBreDe header still sits flush against the top of the page. */
header[data-testid="stHeader"],
[data-testid="stToolbar"] {
    background: transparent !important;
    box-shadow: none !important;
    height: 0 !important;
    min-height: 0 !important;
    overflow: visible !important;
    pointer-events: none !important;
}

/* Restore the one control needed to reopen an accidentally collapsed
   sidebar. Streamlit renders it only while the sidebar is collapsed, so it
   is invisible during normal use. Pinned to the dark header's empty
   top-left corner and styled light-on-dark to stay legible. */
[data-testid="stExpandSidebarButton"] {
    pointer-events: auto !important;
    position: fixed !important;
    top: 0.55rem !important;
    left: 0.55rem !important;
    z-index: 1000 !important;
    width: 2rem !important;
    height: 2rem !important;
    min-width: 2rem !important;
    min-height: 2rem !important;
    padding: 0 !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    background: rgba(250, 247, 242, 0.10) !important;
    border: 1px solid rgba(250, 247, 242, 0.28) !important;
    border-radius: 2px !important;
}

/* Restore the Material Symbols icon font for the two sidebar controls only.
   Streamlit renders these icons as a text node ("keyboard_double_arrow_right")
   that a font ligature folds into a glyph. The broad app rules above
   ([class*="css"] and section[data-testid="stSidebar"] *) override
   font-family on those spans, so the ligature never forms and the raw icon
   name shows. These selectors are deliberately more specific than the rules
   they must beat. The font is served locally by Streamlit
   (static/media/MaterialSymbols-Rounded.woff2), so this needs no network. */
[data-testid="stExpandSidebarButton"] *,
header[data-testid="stHeader"] [data-testid="stExpandSidebarButton"] *,
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] * {
    font-family: "Material Symbols Rounded" !important;
    font-weight: 400 !important;
    font-style: normal !important;
    font-feature-settings: "liga" !important;
    -webkit-font-feature-settings: "liga" !important;
    -moz-font-feature-settings: "liga" !important;
    letter-spacing: normal !important;
    text-transform: none !important;
    white-space: nowrap !important;
    direction: ltr !important;
    background: transparent !important;
}

/* Icon colour: dark ink for both sidebar controls on the light background. */
[data-testid="stExpandSidebarButton"] *,
header[data-testid="stHeader"] [data-testid="stExpandSidebarButton"] * {
    color: var(--ink2) !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] * {
    color: var(--ink2) !important;
}

[data-testid="stExpandSidebarButton"]:hover {
    background: rgba(250, 247, 242, 0.20) !important;
}

/* iframe fix */
iframe { background: transparent !important; color-scheme: light !important; }
[data-testid="stCustomComponentV1"],
[data-testid="stCustomComponentV1"] > div,
[data-testid="stCustomComponentV1"] iframe { background: transparent !important; }
.element-container iframe { background-color: #f4efe8 !important; }

/* Scrollbar */
::-webkit-scrollbar { width: 3px; height: 3px; }
::-webkit-scrollbar-track { background: var(--surface2); }
::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 2px; }

/* Sidebar */
section[data-testid="stSidebar"] {
    background: var(--surface) !important;
    border-right: 1px solid var(--border) !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    padding: 1rem 1.1rem 1rem !important;
}
section[data-testid="stSidebar"] * { color: var(--muted) !important; font-family: var(--sans) !important; }
section[data-testid="stSidebar"] h3 {
    font-family: var(--mono) !important;
    font-size: 0.6rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.2em !important;
    text-transform: uppercase !important;
    color: var(--ink) !important;
    border-bottom: 1px solid var(--border) !important;
    padding-bottom: 0.5rem !important;
    margin: 1.2rem 0 0.8rem !important;
}
section[data-testid="stSidebar"] label { font-size: 0.78rem !important; font-weight: 500 !important; color: var(--ink2) !important; }
section[data-testid="stSidebar"] iframe { background-color: #faf7f2 !important; }
section[data-testid="stSidebar"] hr { margin: 0.9rem 0 !important; }
section[data-testid="stSidebar"] .stSuccess,
section[data-testid="stSidebar"] .stWarning,
section[data-testid="stSidebar"] .stError {
    padding: 0.5rem 0.8rem !important;
    font-size: 0.68rem !important;
    margin-bottom: 0.5rem !important;
}

/* Tabs */
.stTabs { margin-left: 0 !important; margin-right: 0 !important; }
.stTabs [data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 2px solid var(--border) !important;
    gap: 0 !important; padding: 0 !important;
    width: 100% !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
    overflow: hidden !important;
}
.stTabs [data-baseweb="tab"] {
    font-family: var(--mono) !important;
    font-size: 0.62rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.14em !important;
    text-transform: uppercase !important;
    color: var(--muted) !important;
    background: transparent !important;
    border: none !important;
    padding: 1rem 2rem !important;
    border-bottom: 2px solid transparent !important;
    transition: color 0.2s !important;
}
.stTabs [aria-selected="true"] { color: var(--ink) !important; border-bottom: 2px solid var(--ink) !important; background: transparent !important; }
.stTabs [data-baseweb="tab"]:hover { color: var(--ink2) !important; }
.stTabs [data-baseweb="tab-panel"] { padding-top: 2rem !important; padding-bottom: 2.5rem !important; }

/* Text inputs */
.stTextInput > div > div > input {
    background: var(--surface) !important;
    border: 1px solid var(--border2) !important;
    border-radius: 2px !important;
    color: var(--ink) !important;
    font-family: var(--sans) !important;
    font-size: 0.92rem !important;
    padding: 0.7rem 1rem !important;
    transition: border-color 0.2s, box-shadow 0.2s !important;
}
.stTextInput > div > div > input::placeholder { color: var(--muted) !important; font-style: italic !important; opacity: 1 !important; }
.stTextInput > div > div > input:focus { border-color: var(--cyan) !important; box-shadow: 0 0 0 3px rgba(0,119,170,0.1) !important; outline: none !important; }

/* Chat input */
[data-testid="stBottom"] {
    background: #f4efe8 !important;
    padding-left: 2.2rem !important;
    padding-right: 2.2rem !important;
    padding-top: 0.75rem !important;
    padding-bottom: 0.75rem !important;
    border-top: 1px solid var(--border) !important;
    box-sizing: border-box !important;
}
.stChatInputContainer { background: var(--surface2) !important; border: 1px solid var(--border) !important; border-radius: 2px !important; padding: 0.5rem 0.8rem !important; }
.stChatInputContainer textarea { background: var(--surface) !important; border: 1px solid var(--border2) !important; border-radius: 2px !important; color: var(--ink) !important; font-family: var(--sans) !important; font-size: 0.9rem !important; }
.stChatInputContainer textarea:focus { border-color: var(--cyan) !important; box-shadow: 0 0 0 3px rgba(0,119,170,0.1) !important; }

/* Buttons */
.stButton > button {
    background: var(--ink) !important;
    border: 1px solid var(--ink) !important;
    border-radius: 2px !important;
    color: #faf7f2 !important;
    font-family: var(--mono) !important;
    font-size: 0.62rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.14em !important;
    text-transform: uppercase !important;
    padding: 0.65rem 1.5rem !important;
    transition: all 0.15s !important;
    cursor: pointer !important;
}
.stButton > button:hover { background: var(--ink2) !important; border-color: var(--ink2) !important; box-shadow: 0 2px 8px rgba(13,27,42,0.18) !important; transform: translateY(-1px) !important; }
.stButton > button:active { transform: translateY(0) !important; }

/* Link buttons */
.stLinkButton > a {
    background: transparent !important;
    border: 1px solid var(--border2) !important;
    border-radius: 2px !important;
    color: var(--cyan) !important;
    font-family: var(--mono) !important;
    font-size: 0.6rem !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
    padding: 0.35rem 0.8rem !important;
    text-decoration: none !important;
    transition: all 0.15s !important;
}
.stLinkButton > a:hover { background: rgba(0,119,170,0.06) !important; border-color: var(--cyan) !important; }

/* Chat messages */
[data-testid="stChatMessage"] { background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: 2px !important; margin-bottom: 1.2rem !important; padding: 1rem 1.3rem !important; }
[data-testid="stChatMessage"] p { color: var(--ink) !important; font-family: var(--sans) !important; font-size: 0.9rem !important; line-height: 1.75 !important; }
[data-testid="stChatMessage"] li { color: var(--ink2) !important; font-size: 0.88rem !important; line-height: 1.7 !important; }
[data-testid="stChatMessage"] strong { color: var(--ink) !important; font-weight: 600 !important; }
[data-testid="stChatMessage"] h1,
[data-testid="stChatMessage"] h2,
[data-testid="stChatMessage"] h3 { font-family: var(--mono) !important; font-size: 0.62rem !important; font-weight: 500 !important; letter-spacing: 0.16em !important; text-transform: uppercase !important; color: var(--muted) !important; margin-top: 1.4rem !important; margin-bottom: 0.6rem !important; border-bottom: 1px solid var(--border) !important; padding-bottom: 0.4rem !important; }

/* Markdown */
.stMarkdown p { color: var(--ink) !important; font-size: 0.9rem !important; line-height: 1.75 !important; margin-bottom: 0.5rem !important; }
.stMarkdown li { color: var(--ink2) !important; font-size: 0.88rem !important; line-height: 1.7 !important; margin-bottom: 0.2rem !important; }
.stMarkdown strong { color: var(--ink) !important; font-weight: 600 !important; }
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3 { font-family: var(--mono) !important; font-size: 0.62rem !important; letter-spacing: 0.16em !important; text-transform: uppercase !important; color: var(--muted) !important; border-bottom: 1px solid var(--border) !important; padding-bottom: 0.4rem !important; margin-top: 1.4rem !important; }

/* Metrics */
[data-testid="stMetric"] { background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: 2px !important; padding: 1.1rem 1.4rem !important; transition: border-color 0.2s, box-shadow 0.2s !important; }
[data-testid="stMetric"]:hover { border-color: var(--border2) !important; box-shadow: 0 2px 12px rgba(13,27,42,0.08) !important; }
[data-testid="stMetricLabel"],
[data-testid="stMetricLabel"] p,
[data-testid="stMetricLabel"] div,
[data-testid="stMetricLabel"] span { font-family: var(--mono) !important; font-size: 0.58rem !important; font-weight: 500 !important; letter-spacing: 0.16em !important; text-transform: uppercase !important; color: var(--muted) !important; }
[data-testid="stMetricValue"],
[data-testid="stMetricValue"] div,
[data-testid="stMetricValue"] span,
[data-testid="stMetricValue"] > div { font-family: var(--mono) !important; font-size: 1.8rem !important; font-weight: 500 !important; color: var(--cyan) !important; letter-spacing: -0.02em !important; }

/* Expander */
.streamlit-expanderHeader { background: var(--surface2) !important; border: 1px solid var(--border) !important; border-radius: 2px !important; color: var(--ink2) !important; font-family: var(--mono) !important; font-size: 0.62rem !important; font-weight: 500 !important; letter-spacing: 0.12em !important; text-transform: uppercase !important; padding: 0.95rem 1.3rem !important; transition: background 0.2s !important; }
.streamlit-expanderHeader:hover { background: var(--surface3) !important; }
.streamlit-expanderContent { background: var(--surface) !important; border: 1px solid var(--border) !important; border-top: none !important; border-radius: 0 0 2px 2px !important; padding: 1.5rem 1.6rem 1.6rem !important; }

/* Containers — scoped to tabs only to avoid polluting sidebar/page wrappers */
.stTabs [data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: 2px !important;
    transition: border-color 0.2s, box-shadow 0.15s !important;
}
.stTabs [data-testid="stVerticalBlockBorderWrapper"]:hover {
    border-color: var(--border2) !important;
    box-shadow: 0 2px 12px rgba(13,27,42,0.08) !important;
}

/* Selectbox */
.stSelectbox > div > div { background: var(--surface) !important; border: 1px solid var(--border2) !important; border-radius: 2px !important; color: var(--ink) !important; font-family: var(--sans) !important; font-size: 0.88rem !important; }

/* Slider */
.stSlider > div > div > div > div { background: var(--cyan) !important; }
[data-testid="stSlider"] [data-testid="stTickBarMin"],
[data-testid="stSlider"] [data-testid="stTickBarMax"] { font-family: var(--mono) !important; font-size: 0.6rem !important; color: var(--muted) !important; }

/* Status */
.stSuccess { background: rgba(26,122,74,0.07) !important; border: 1px solid rgba(26,122,74,0.25) !important; border-radius: 2px !important; color: #1a7a4a !important; font-family: var(--mono) !important; font-size: 0.72rem !important; padding: 0.65rem 1rem !important; }
.stWarning { background: rgba(192,128,0,0.07) !important; border: 1px solid rgba(192,128,0,0.25) !important; border-radius: 2px !important; color: var(--gold) !important; font-family: var(--mono) !important; font-size: 0.72rem !important; padding: 0.65rem 1rem !important; }
.stError { background: rgba(192,57,43,0.07) !important; border: 1px solid rgba(192,57,43,0.25) !important; border-radius: 2px !important; color: var(--red) !important; padding: 0.65rem 1rem !important; }
.stInfo { padding: 0.65rem 1rem !important; border-radius: 2px !important; }

/* Caption */
.stCaption, small { font-family: var(--mono) !important; font-size: 0.62rem !important; font-weight: 400 !important; color: var(--muted) !important; letter-spacing: 0.04em !important; line-height: 1.65 !important; margin-bottom: 0.25rem !important; }

/* HR / Spinner */
hr { border-color: var(--border) !important; margin: 2rem 0 !important; }
.stSpinner > div { border-top-color: var(--cyan) !important; }

/* Checkbox */
.stCheckbox > label > span { color: var(--ink2) !important; font-size: 0.82rem !important; }

/* ── Claim → evidence cards ──────────────────────────────────────────────
   Evidence objects, not chat bubbles: flat surface, one hairline rule, a cyan
   spine marking the claim, and the excerpt set indented beneath it. Divs are
   used rather than <p>/<blockquote> so the broad .stMarkdown and chat-message
   typography rules do not capture them. */
.ev-section-head {
    font-family: var(--mono); font-size: 0.58rem; font-weight: 500;
    letter-spacing: 0.2em; text-transform: uppercase; color: var(--muted);
    margin: 2rem 0 0.9rem; padding-bottom: 0.45rem;
    border-bottom: 1px solid var(--border);
}
.ev-card {
    background: var(--surface); border: 1px solid var(--border);
    border-left: 2px solid var(--cyan); border-radius: 2px;
    padding: 1.15rem 1.35rem 1.25rem; margin-bottom: 1rem;
}
.ev-head {
    display: flex; align-items: baseline; justify-content: space-between;
    gap: 1rem; margin-bottom: 0.6rem;
}
.ev-kicker {
    font-family: var(--mono); font-size: 0.56rem; font-weight: 500;
    letter-spacing: 0.18em; text-transform: uppercase; color: var(--cyan);
}
.ev-index {
    font-family: var(--mono); font-size: 0.56rem; letter-spacing: 0.12em;
    color: rgba(13,27,42,0.3);
}
.ev-claim {
    font-family: var(--sans); font-size: 0.93rem; line-height: 1.7;
    color: var(--ink); margin-bottom: 0.55rem;
}
.ev-tags {
    font-family: var(--mono); font-size: 0.56rem; letter-spacing: 0.1em;
    text-transform: uppercase; color: rgba(13,27,42,0.35); margin-bottom: 1rem;
}
.ev-sub-kicker {
    font-family: var(--mono); font-size: 0.55rem; font-weight: 500;
    letter-spacing: 0.18em; text-transform: uppercase; color: var(--muted);
    padding-top: 0.85rem; border-top: 1px solid var(--border); margin-bottom: 0.75rem;
}
.ev-item { margin-bottom: 1.1rem; }
.ev-item:last-child { margin-bottom: 0; }
.ev-quote {
    font-family: var(--sans); font-size: 0.85rem; line-height: 1.75;
    color: var(--ink2); background: var(--surface2);
    border-left: 2px solid var(--border2); border-radius: 0 2px 2px 0;
    padding: 0.75rem 1rem; margin-bottom: 0.55rem; white-space: pre-wrap;
}
.ev-quote-empty { color: var(--muted); font-style: italic; }
.ev-src { padding-left: 0.1rem; }
.ev-src-main {
    display: flex; align-items: baseline; gap: 0.5rem;
    font-family: var(--sans); font-size: 0.82rem; line-height: 1.5;
}
.ev-rank { font-family: var(--mono); font-size: 0.72rem; color: var(--cyan); flex-shrink: 0; }
.ev-title { color: var(--ink); font-weight: 600; }
.ev-meta {
    font-family: var(--mono); font-size: 0.58rem; letter-spacing: 0.08em;
    color: var(--muted); margin-top: 0.2rem;
}
.ev-open {
    display: inline-block; margin-top: 0.5rem;
    font-family: var(--mono); font-size: 0.56rem; letter-spacing: 0.1em;
    text-transform: uppercase; color: var(--cyan); text-decoration: none;
    border: 1px solid var(--border2); border-radius: 2px; padding: 0.28rem 0.7rem;
    transition: background 0.15s, border-color 0.15s;
}
.ev-open:hover { background: rgba(0,119,170,0.06); border-color: var(--cyan); }
.ev-details { margin-top: 0.55rem; }
.ev-summary {
    cursor: pointer; list-style: none; display: inline-block;
    font-family: var(--mono); font-size: 0.56rem; letter-spacing: 0.1em;
    text-transform: uppercase; color: var(--cyan);
    border: 1px solid var(--border2); border-radius: 2px; padding: 0.28rem 0.7rem;
    transition: background 0.15s, border-color 0.15s;
}
.ev-summary::-webkit-details-marker { display: none; }
.ev-summary:hover { background: rgba(0,119,170,0.06); border-color: var(--cyan); }
.ev-details[open] .ev-summary { margin-bottom: 0.55rem; }
.ev-ids {
    font-family: var(--mono); font-size: 0.55rem; letter-spacing: 0.04em;
    color: rgba(13,27,42,0.38); margin-top: 0.25rem; word-break: break-all;
}
.ev-extra { margin-top: 1.4rem; }
.ev-extra-summary { color: var(--muted); border-color: var(--border); }
.ev-extra-body {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 2px; padding: 1.1rem 1.3rem; margin-top: 0.6rem;
}
.ev-item-missing {
    font-family: var(--mono); font-size: 0.62rem; line-height: 1.6;
    color: var(--gold);
}

/* ── Sidebar evidence panel ──────────────────────────────────────────────
   Beats the broad `section[data-testid="stSidebar"] *` colour rule on
   specificity so the panel can use the full ink/cyan scale. */
section[data-testid="stSidebar"] .sb-block { margin-bottom: 0.35rem; }
section[data-testid="stSidebar"] .sb-head {
    font-family: var(--mono) !important; font-size: 0.55rem !important;
    font-weight: 500 !important; letter-spacing: 0.2em !important;
    text-transform: uppercase !important; color: var(--ink) !important;
    border-bottom: 1px solid var(--border); padding-bottom: 0.45rem;
    margin: 1.35rem 0 0.75rem;
}
section[data-testid="stSidebar"] .sb-figure {
    font-family: var(--mono) !important; font-size: 1.45rem !important;
    font-weight: 500 !important; color: var(--cyan) !important;
    letter-spacing: -0.02em !important; line-height: 1.1;
}
section[data-testid="stSidebar"] .sb-figure-label {
    font-family: var(--sans) !important; font-size: 0.74rem !important;
    color: var(--ink2) !important; line-height: 1.5; margin-bottom: 0.55rem;
}
section[data-testid="stSidebar"] .sb-split {
    font-family: var(--mono) !important; font-size: 0.6rem !important;
    letter-spacing: 0.06em !important; color: var(--muted) !important;
    line-height: 1.9;
}
section[data-testid="stSidebar"] .sb-list {
    font-family: var(--sans) !important; font-size: 0.76rem !important;
    color: var(--ink2) !important; line-height: 1.95;
}
section[data-testid="stSidebar"] .sb-list .sb-dot { color: var(--teal) !important; margin-right: 0.4rem; }
section[data-testid="stSidebar"] .sb-status {
    font-family: var(--mono) !important; font-size: 0.66rem !important;
    letter-spacing: 0.08em !important; line-height: 1.6;
}
section[data-testid="stSidebar"] .sb-status-ok { color: var(--green) !important; }
section[data-testid="stSidebar"] .sb-status-warn { color: var(--gold) !important; }
section[data-testid="stSidebar"] .sb-note {
    font-family: var(--mono) !important; font-size: 0.55rem !important;
    color: rgba(13,27,42,0.38) !important; line-height: 1.65; margin-top: 0.35rem;
}

/* Footer */
footer, [data-testid="stFooter"] { background: transparent !important; color: var(--muted) !important; }
</style>
""", unsafe_allow_html=True)

# ── Session state
if "search_results" not in st.session_state:
    st.session_state.search_results = []
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# ════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════════════════════
# Presentation build is OpenAI-only; the Ollama control is intentionally absent.
provider = "openai"

# Retrieval depth is pinned to the evaluated configuration. There is deliberately no
# UI control for it — see EVALUATED_K.
k_articles = EVALUATED_K

with st.sidebar:
    st.markdown(
        '<div class="sb-block">'
        '<div class="sb-head">Publication reference evidence base</div>'
        f'<div class="sb-figure">{EVIDENCE_BASE_RECORDS}</div>'
        '<div class="sb-figure-label">evidence-bearing papers</div>'
        '<div class="sb-split">'
        f"{EVIDENCE_BASE_FULLTEXT} full text · {EVIDENCE_BASE_ABSTRACT} abstract-only<br>"
        f"{EVIDENCE_BASE_SEGMENTS} indexed evidence segments<br>"
        "frozen research corpus · not live index counts"
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="sb-block">'
        '<div class="sb-head">Governed response</div>'
        '<div class="sb-list">'
        '<span class="sb-dot">▸</span>Evidence-sufficiency gate<br>'
        '<span class="sb-dot">▸</span>Claim-level excerpt validation<br>'
        '<span class="sb-dot">▸</span>Human judgement remains final'
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    # The sidebar carries no system, status or diagnostic panel: the presentation
    # surface stays on the evidence base and the governance model. Provider and
    # retrieval depth are fixed build constants (provider, EVALUATED_K) and need no
    # runtime display. The pre-query index guard remains in the Ask tab.

    st.markdown("---")
    components.html("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&display=swap');
    html, body { margin:0; padding:0.2rem 0.8rem 0 0.8rem; background:#faf7f2 !important; background-color:#faf7f2 !important; }
    .sb-footer { font-family:'DM Mono',monospace; font-size:0.62rem; color:#4a6377; line-height:2.3; padding:0.6rem 0.2rem 0.4rem; }
    .sb-footer .divider { height:1px; background:rgba(13,27,42,0.12); margin-bottom:0.7rem; }
    .sb-footer .brand { color:#0d1b2a; font-weight:500; }
    .sb-footer .hl    { color:#0077aa; }
    .sb-footer .warn  { color:#c08000; font-size:0.58rem; }
    </style>
    <div class="sb-footer">
        <div class="divider"></div>
        <span class="brand">HyBreDe</span> · Turku UAS ICT · 2026<br>
        Governance-Aware RAG Pipeline<br>
        <span class="hl">Evidence-grounded</span> · <span class="warn">No clinical use</span>
    </div>
    """, height=100)

# ════════════════════════════════════════════════════════════════════════════
# HEADER
# ════════════════════════════════════════════════════════════════════════════
components.html("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=Inter:wght@400;500;600&display=swap');
*, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
html, body { background:#0d1b2a !important; background-color:#0d1b2a !important; overflow:hidden; }
body { padding:2.2rem 2.5rem 1.8rem; }

.header { position:relative; padding-bottom:1.8rem; }
.header::after { content:''; position:absolute; bottom:0; left:0; right:0; height:1px; background:rgba(250,247,242,0.12); }

.project-label {
    font-family:'DM Mono',monospace; font-size:0.62rem; letter-spacing:0.24em;
    text-transform:uppercase; color:rgba(250,247,242,0.35); margin-bottom:1rem;
    opacity:0; animation:fadeUp 0.5s 0.05s forwards;
}

.title {
    font-family:'DM Serif Display',serif; font-size:4.8rem; font-weight:400;
    color:#faf7f2; letter-spacing:-0.02em; line-height:1;
    opacity:0; animation:fadeUp 0.6s 0.15s forwards;
}
.title em { font-style:italic; color:#7ecfea; }

.header-bottom {
    display:flex; justify-content:space-between; align-items:center;
    margin-top:1rem;
}

.subtitle {
    font-family:'Inter',sans-serif; font-size:0.78rem; color:rgba(250,247,242,0.5);
    letter-spacing:0.04em; display:flex; gap:1.6rem; flex-wrap:wrap;
    opacity:0; animation:fadeUp 0.6s 0.25s forwards;
}
.subtitle-item { display:flex; align-items:center; gap:0.45rem; transition:color 0.2s; cursor:default; }
.subtitle-item::before { content:'·'; color:rgba(126,207,234,0.5); }
.subtitle-item:hover { color:rgba(250,247,242,0.8); }

.logo-wrap {
    opacity:0; animation:fadeUp 0.6s 0.3s forwards;
    flex-shrink:0;
}
.logo-wrap img {
    height:44px; width:auto;
    display:block;
}

@keyframes fadeUp {
    from { opacity:0; transform:translateY(10px); }
    to   { opacity:1; transform:translateY(0); }
}
</style>
<div class="header">
    <div class="project-label">Governance-Aware Healthcare Evidence Retrieval &amp; Synthesis &nbsp;·&nbsp; v2026</div>
    <div class="title">Hyb<em>Re</em>De</div>
    <div class="header-bottom">
        <div class="subtitle">
            <div class="subtitle-item">Governance-Aware RAG Pipeline</div>
            <div class="subtitle-item">AI-Assisted Evidence Synthesis</div>
            <div class="subtitle-item">Human Oversight Preserved</div>
            <div class="subtitle-item">Turku UAS · ICT 2026</div>
        </div>
    </div>
</div>
""", height=235)


# ════════════════════════════════════════════════════════════════════════════
# TABS
# ════════════════════════════════════════════════════════════════════════════
tab_ask, tab_search = st.tabs(
    ["◉  Ask the Evidence Base", "◇  Explore External Literature"]
)


def section_header(tag, desc):
    st.markdown(f"""
    <div style="padding-top:0.5rem;margin-bottom:2rem;">
        <div style="font-family:'DM Mono',monospace;font-size:0.58rem;font-weight:500;
        letter-spacing:0.2em;text-transform:uppercase;color:#4a6377;margin-bottom:0.65rem;
        display:flex;align-items:center;gap:0.5rem;">
            <span style="display:inline-block;width:16px;height:1px;background:rgba(13,27,42,0.2);"></span>
            {tag}
        </div>
        <div style="font-family:'Inter',sans-serif;font-size:0.88rem;color:#4a6377;line-height:1.8;max-width:72ch;">{desc}</div>
    </div>
    """, unsafe_allow_html=True)


# ─── TAB 1 ───────────────────────────────────────────────────────────────────
with tab_ask:

    section_header(
        "Governed Response Model",
        # Short scannable lines rather than a paragraph. section_header() renders
        # desc as HTML, so no helper or CSS change is needed; the inline styles
        # reuse the header's own mono/sans scale.
        '<div style="margin-bottom:1.1rem;">Retrieves evidence only from the '
        "pre-screened corpus.</div>"
        '<div style="font-family:\'DM Mono\',monospace;font-size:0.58rem;'
        "letter-spacing:0.18em;text-transform:uppercase;color:rgba(13,27,42,0.4);"
        'margin-bottom:0.55rem;">Returns an explicit outcome</div>'
        '<div style="display:inline-block;font-family:\'DM Mono\',monospace;'
        "font-size:0.66rem;letter-spacing:0.06em;color:#1e3448;background:#faf7f2;"
        "border:1px solid rgba(13,27,42,0.12);border-radius:2px;"
        'padding:0.45rem 0.9rem;margin-bottom:1.2rem;">'
        # Presentation-only: technical_failure is still a live disposition and is
        # still rendered by render_disposition()/render_result() when it occurs. It
        # is simply not advertised in the intro as an expected outcome.
        "Supported <span style=\"color:rgba(13,27,42,0.25);\">·</span> "
        "Bounded partial <span style=\"color:rgba(13,27,42,0.25);\">·</span> "
        "Evidence gap</div>"
        '<div style="margin-bottom:0.3rem;">Claims are linked to approved '
        "evidence excerpts.</div>"
        '<div style="margin-bottom:1.1rem;">If evidence is insufficient, the '
        "system withholds the unsupported part.</div>"
        '<div style="color:#1e3448;">Researcher judgement remains final.</div>'
    )

    if not os.path.exists(RAG_STORE_DIR):
        st.warning("No vector index found. Build the index before asking questions.")

    user_input = st.chat_input("Ask a research question about the pre-screened corpus...")

    for msg in st.session_state.chat_history:
        with st.chat_message(msg.get("role", "assistant")):
            if msg.get("role") == "assistant":
                # History stores the generator's result object verbatim, so an
                # earlier response replays with the same disposition, scope and
                # claim → evidence mapping as when it was first shown.
                stored = msg.get("result")
                if isinstance(stored, dict):
                    render_result(stored)
                else:
                    st.markdown(msg.get("content") or "")
            else:
                st.markdown(msg.get("content") or "")

    if user_input:

        st.session_state.chat_history.append({"role": "user", "content": user_input})

        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Retrieving evidence · Generating response..."):
                try:
                    result = generate_rag_answer(
                        user_input,
                        provider=provider,
                        k=k_articles,
                        answer_template="structured",
                        output_mode="text",
                    )

                    # Disposition is reported by the generator and never recomputed here.
                    render_result(result)

                    # Every outcome is retained, including evidence gaps and failures.
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": result.get("answer") or "No answer generated.",
                        "result": result,
                    })

                except Exception as exc:
                    # Presentation-safe failure. The raw exception message is never
                    # rendered: it can carry internal paths or provider payloads. Only
                    # the exception class is surfaced, behind a collapsed control; the
                    # full detail remains in the server console.
                    st.error(TECHNICAL_FAILURE_MESSAGE)
                    with st.expander("Technical details"):
                        st.caption(
                            "The response was not produced. Failure class: "
                            f"{type(exc).__name__}."
                        )
                        st.caption(
                            "Full diagnostics are written to the server console and "
                            "are deliberately not shown in the interface."
                        )

    if st.session_state.chat_history:
        if st.button("Clear conversation"):
            st.session_state.chat_history = []
            st.rerun()


# ─── TAB 2 ───────────────────────────────────────────────────────────────────
with tab_search:

    st.warning(
        "**Outside the evaluated pipeline.** These results come from live Semantic "
        "Scholar discovery. They are unscreened and not part of the HyBreDe "
        "evidence base."
    )

    section_header(
        "External Literature Discovery · Semantic Scholar API",
        "Use this tab for background reading and article discovery only. Results "
        "shown here are not screened, not indexed in the HyBreDe evidence base, "
        "and are not used to generate governed answers."
    )

    col_input, col_btn = st.columns([5, 1])

    with col_input:
        search_query = st.text_input("", key="search_query", placeholder="Search external literature...", label_visibility="collapsed")

    with col_btn:
        search_clicked = st.button("Search", use_container_width=True)

    if search_clicked:
        if not search_query.strip():
            st.warning("Enter a search topic first.")
        else:
            fetch_papers, load_error = load_external_search()
            if fetch_papers is None:
                st.info("Semantic Scholar search is unavailable in this demo session.")
                with st.expander("Technical details"):
                    st.caption(f"External client unavailable. Failure class: {load_error}.")
            else:
                with st.spinner("Querying Semantic Scholar..."):
                    try:
                        # Presentation-only display cap for unscreened external
                        # results. Kept separate from the pipeline's evaluated k so
                        # that this tab can never influence retrieval depth.
                        st.session_state.search_results = fetch_papers(
                            search_query, result_limit=EXTERNAL_RESULT_LIMIT
                        )
                    except Exception as exc:
                        st.session_state.search_results = []
                        st.error("External search could not be completed.")
                        with st.expander("Technical details"):
                            st.caption(f"Failure class: {type(exc).__name__}.")

    if st.session_state.search_results:
        st.markdown(f"""
        <div style="display:inline-flex;align-items:center;gap:0.6rem;
        font-family:'DM Mono',monospace;font-size:0.62rem;letter-spacing:0.1em;
        text-transform:uppercase;color:#4a6377;padding:0.4rem 0.9rem;
        background:#faf7f2;border:1px solid rgba(13,27,42,0.12);border-radius:2px;margin:0.8rem 0;">
            <span style="color:#0077aa;font-size:0.9rem;font-weight:500;">{len(st.session_state.search_results)}</span>
            external results · unscreened
        </div>
        """, unsafe_allow_html=True)

        for i, paper in enumerate(st.session_state.search_results):
            title      = paper.get("title", "No title")
            abstract   = paper.get("abstract", "No abstract available.")
            year       = paper.get("year", "N/A")
            url        = paper.get("url", "")
            authors    = paper.get("authors", [])
            author_str = ", ".join([a.get("name", "") for a in authors[:3]])
            if len(authors) > 3:
                author_str += " et al."

            with st.container(border=True):
                st.markdown(f"**{title}**")
                st.caption(f"{year}  ·  {author_str if author_str else 'Unknown authors'}")
                with st.expander("Abstract"):
                    st.write(abstract)
                if url:
                    st.link_button("↗ Open paper", url)

    else:
        st.markdown("""
        <div style="text-align:center;padding:5rem 2rem;">
            <div style="font-family:'DM Mono',monospace;font-size:0.65rem;
            letter-spacing:0.2em;color:rgba(13,27,42,0.2);margin-bottom:0.6rem;">NO RESULTS</div>
            <div style="font-family:'Inter',sans-serif;font-size:0.85rem;color:#4a6377;">
            Enter a research topic above and click Search</div>
        </div>
        """, unsafe_allow_html=True)


# ── Footer
st.markdown("""
<div style="display:flex;justify-content:space-between;align-items:center;
padding:1rem 1.5rem;margin-top:2.5rem;
border-top:1px solid rgba(13,27,42,0.12);
font-family:'DM Mono',monospace;font-size:0.6rem;color:#4a6377;letter-spacing:0.06em;">
    <div style="color:#1e3448;">HyBreDe · Turku University of Applied Sciences · ICT 2026</div>
    <div>
        <span style="color:#0077aa;">Evidence-grounded</span>
        <span style="color:rgba(13,27,42,0.3);">&nbsp;·&nbsp; No clinical recommendations &nbsp;·&nbsp;</span>
        <span style="color:#007c6e;">Human oversight preserved</span>
    </div>
</div>
""", unsafe_allow_html=True)
