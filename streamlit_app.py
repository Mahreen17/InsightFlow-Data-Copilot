"""
UI: restyled with a real visual identity instead of default widgets.

DESIGN CONCEPT:
TrailPeak sells outdoor gear -- so instead of looking like a generic AI
chat demo, this borrows from actual trail signage: painted "blazes" (the
colored marks hikers follow on trees) stand in for the Orchestrator's
routing decision. A question routed to SQL, RAG, and/or MCP shows as
blazes of those colors -- the UI structure directly encodes what the
system actually did, rather than decorating it.

WHY CUSTOM HTML INSTEAD OF st.chat_message():
Streamlit's built-in chat bubbles work, but their visual style is fixed
and their internal CSS classes aren't meant to be overridden reliably.
Building our own message bubbles with st.markdown(html) gives full control
over color, shape, and the blaze badges -- at the cost of writing a little
more code ourselves.
"""

import os
import streamlit as st


try:
    if "GOOGLE_API_KEY" in st.secrets:
        os.environ["GOOGLE_API_KEY"] = st.secrets["GOOGLE_API_KEY"]
except Exception:
    pass  # no secrets.toml present locally -- expected, not an error

from orchestrator import ask_orchestrator

st.set_page_config(page_title="InsightFlow Data Copilot", page_icon="🧭", layout="centered")

# =============================================================================
# Design tokens + custom CSS.
# =============================================================================

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Fjalla+One&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap');

:root {
    --coral: #FF9D9D;      /* header, MCP blaze */
    --peach: #FFC5AA;      /* assistant bubble accent, RAG blaze */
    --lime: #EEF8CD;       /* page background */
    --mint: #BBF1D2;       /* user bubble, SQL blaze */
    --card: #FFFDF7;       /* light card surface for assistant bubbles */
    --ink: #3A3230;        /* body text -- dark neutral for readability against pastels */
}

/* Overall app background -- soft diagonal gradient across the full palette */
[data-testid="stAppViewContainer"], .stApp {
    background: linear-gradient(135deg, var(--lime) 0%, var(--mint) 38%, var(--peach) 72%, var(--coral) 100%);
    background-attachment: fixed;
}
[data-testid="stHeader"] { background-color: transparent; }
[data-testid="stBottomBlockContainer"] { background: transparent; }

/* Kill Streamlit's default top padding so our header sits flush */
.block-container { padding-top: 1.5rem; max-width: 720px; }

body, p, div, span, li { font-family: 'Inter', sans-serif; color: var(--ink); }

/* ---- Header ---- */
.tp-header {
    background: var(--coral);
    border-radius: 14px;
    padding: 28px 32px 20px 32px;
    margin-bottom: 0;
}
.tp-title {
    font-family: 'Fjalla One', sans-serif;
    font-size: 2.1rem;
    letter-spacing: 0.02em;
    color: var(--ink);
    margin: 0;
    text-transform: uppercase;
}
.tp-caption {
    color: #5C4A45;
    font-size: 0.95rem;
    margin-top: 6px;
    max-width: 480px;
}
/* Signature element: a torn horizon line under the header, like a ridge */
.tp-horizon {
    height: 14px;
    margin: 0 0 22px 0;
    background: linear-gradient(115deg, var(--coral) 48%, transparent 48.5%),
                linear-gradient(245deg, var(--coral) 48%, transparent 48.5%);
    background-size: 22px 100%;
    background-repeat: repeat-x;
}

/* ---- Chat bubbles ---- */
.tp-row { display: flex; margin: 14px 0; }
.tp-row.user { justify-content: flex-end; }
.tp-row.assistant { justify-content: flex-start; }

.tp-bubble {
    max-width: 82%;
    padding: 14px 18px;
    border-radius: 12px;
    font-size: 0.97rem;
    line-height: 1.55;
}
.tp-bubble.user {
    background: var(--mint);
    color: var(--ink);
    border-bottom-right-radius: 3px;
}
.tp-bubble.assistant {
    background: var(--card);
    border-left: 4px solid var(--peach);
    border-bottom-left-radius: 3px;
    box-shadow: 0 1px 3px rgba(58,50,48,0.08);
}

/* ---- Trail blazes: the routing indicator ---- */
.tp-blazes { display: flex; gap: 6px; margin-top: 10px; flex-wrap: wrap; }
.tp-blaze {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    font-weight: 500;
    padding: 3px 9px;
    border-radius: 4px;
    color: var(--ink);
    letter-spacing: 0.03em;
}
.tp-blaze.sql { background: var(--mint); }
.tp-blaze.rag { background: var(--peach); }
.tp-blaze.mcp { background: var(--coral); }

/* ---- Trail marker (details/summary) panel for sources & reasoning ---- */
.tp-panel { margin-top: 10px; }
.tp-panel summary {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.78rem;
    color: #7A6B5D;
    cursor: pointer;
    list-style: none;
}
.tp-panel summary::-webkit-details-marker { display: none; }
.tp-panel summary:before { content: "\\25B8  "; }
.tp-panel[open] summary:before { content: "\\25BE  "; }
.tp-panel .tp-source {
    margin-top: 8px;
    padding: 10px 12px;
    background: rgba(187,241,210,0.35);
    border-radius: 8px;
    font-size: 0.87rem;
}
.tp-panel .tp-source-label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    color: #7A6B5D;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    display: block;
    margin-bottom: 4px;
}

/* ---- Suggested question chips for the empty state ---- */
div[data-testid="stButton"] button {
    background: var(--card);
    border: 1.5px solid var(--coral);
    color: var(--ink);
    border-radius: 999px;
    font-family: 'Inter', sans-serif;
    font-size: 0.85rem;
    padding: 6px 16px;
}
div[data-testid="stButton"] button:hover {
    background: var(--coral);
    color: var(--ink);
    border-color: var(--coral);
}

/* ---- Chat input ---- */
[data-testid="stChatInput"] {
    border-radius: 12px;
    border: 1.5px solid var(--coral);
    background-color: var(--card) !important;
}
[data-testid="stChatInput"] textarea {
    background-color: var(--card) !important;
    color: var(--ink) !important;
}
</style>
""", unsafe_allow_html=True)


# =============================================================================
# Header
# =============================================================================
st.markdown("""
<div class="tp-header">
    <p class="tp-title">🧭 InsightFlow Data Copilot</p>
    <p class="tp-caption">Ask about orders, customers, products, or company policy.
    Every answer shows which trail it followed -- database, documents, or live tools.</p>
</div>
<div class="tp-horizon"></div>
""", unsafe_allow_html=True)


# =============================================================================
# Session state
# =============================================================================
if "history" not in st.session_state:
    st.session_state.history = []


# =============================================================================
# Helper: render one full turn (question + answer + blazes + source panel).
# =============================================================================
def render_turn(turn):
    st.markdown(f'<div class="tp-row user"><div class="tp-bubble user">{turn["question"]}</div></div>',
                unsafe_allow_html=True)

    r = turn["routing"]
    blazes_html = ""
    if r.needs_sql:
        blazes_html += '<span class="tp-blaze sql">■ SQL · DATABASE</span>'
    if r.needs_rag:
        blazes_html += '<span class="tp-blaze rag">■ RAG · DOCUMENTS</span>'
    if r.needs_mcp:
        blazes_html += '<span class="tp-blaze mcp">■ MCP · LIVE TOOL</span>'

    sources_html = ""
    for label, text in turn["sources"].items():
        sources_html += (
            f'<div class="tp-source"><span class="tp-source-label">{label}</span>{text}</div>'
        )

    st.markdown(f"""
    <div class="tp-row assistant">
        <div class="tp-bubble assistant">
            {turn["final_answer"]}
            <div class="tp-blazes">{blazes_html}</div>
            <details class="tp-panel">
                <summary>Why this trail ({r.reasoning})</summary>
                {sources_html}
            </details>
        </div>
    </div>
    """, unsafe_allow_html=True)


# =============================================================================
# Empty state: suggested questions as chips, styled to match the theme.
# =============================================================================

EXAMPLES = [
    "How many customers are in the West region?",
    "What is the warranty on the TrailBlazer 65L Backpack?",
    "Pacific Northwest customers had delayed orders — how many, and what counts as delayed per our SLA?",
]

if "pending_question" not in st.session_state:
    st.session_state.pending_question = None

if not st.session_state.history:
    st.markdown('<p style="color:#5C6B60; font-size:0.85rem; margin-bottom:6px;">TRY A TRAIL:</p>',
                unsafe_allow_html=True)
    cols = st.columns(len(EXAMPLES))
    for col, example in zip(cols, EXAMPLES):
        with col:
            if st.button(example, key=example):
                st.session_state.pending_question = example

# Render conversation so far
for turn in st.session_state.history:
    render_turn(turn)


# =============================================================================
# Input handling -- either a typed question or a clicked example chip.
# =============================================================================
typed_question = st.chat_input("Ask a question about TrailPeak...")
question = typed_question or st.session_state.pending_question
st.session_state.pending_question = None  

if question:
    with st.spinner("Following the trail..."):
        result = ask_orchestrator(question, verbose=False, return_details=True)
    st.session_state.history.append(result)
    st.rerun()