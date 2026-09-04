"""
Chat-area rendering: message bubbles, the SQL viewer, data table / KPI
cards, follow-up suggestion chips, and the loading state.

Pure presentation - every function here takes plain data in (a Message,
or plain strings) and either renders it or hands a clicked question back
via a callback. Nothing here talks to ADK or BigQuery.
"""

from __future__ import annotations

import html
import random
from typing import Callable

import streamlit as st

from services.session_service import Message

# ---------------------------------------------------------------------------
# messages
# ---------------------------------------------------------------------------

def render_message(msg: Message) -> None:
    if msg.role == "user":
        st.markdown(
            f"""
            <div class="ss-user-msg">
                <div class="ss-user-bubble">{html.escape(msg.content)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="ss-msg-time" style="text-align:right;">{msg.timestamp}</div>',
            unsafe_allow_html=True,
        )
        return

    with st.chat_message("assistant", avatar="🛍️"):
        if msg.error:
            st.error(msg.content)
        else:
            # Only the agent's natural-language answer is shown - no raw
            # column names or generated SQL, even if the tool call behind
            # it returned rows/sql (still kept on `msg` for later use).
            st.markdown(msg.content)
    st.markdown(f'<div class="ss-msg-time">{msg.timestamp}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# loading state
# ---------------------------------------------------------------------------

def loading_spinner():
    """Single honest loading message - see ui/styles.py docstring for why
    this isn't a multi-stage fake-progress indicator."""
    return st.spinner("ShopSense is analyzing your data...")


# ---------------------------------------------------------------------------
# follow-up suggestions
# ---------------------------------------------------------------------------

# The agent does not return suggestions of its own - adding that would
# mean changing the backend. This is a simple keyword-matched pool, not
# model-generated, shuffled per turn (deterministically, via `seed`) so
# the same 4 chips don't repeat identically every time.
_KEYWORD_FOLLOWUPS: dict[str, list[str]] = {
    "revenue": [
        "What is the conversion rate for this?",
        "Which products drove this revenue?",
        "How does this compare to last month?",
    ],
    "conversion": [
        "Which category has the lowest conversion?",
        "What does the drop-off funnel look like?",
        "Show this trend over time.",
    ],
    "cart": [
        "Which categories have the most cart abandonment?",
        "What is the average cart value?",
        "Show the view-to-cart drop-off rate.",
    ],
    "user": [
        "How many of these are repeat users?",
        "Which users never completed a purchase?",
        "What is their average order value?",
    ],
    "categor": [
        "Which category has the highest revenue?",
        "Compare the top 3 categories.",
        "Show conversion rate by category.",
    ],
    "product": [
        "Which products have the highest cart abandonment?",
        "Show the top 5 products by revenue.",
        "What about their conversion rate?",
    ],
    "purchase": [
        "What is the average order value?",
        "How does this trend over time?",
        "Which category drives the most purchases?",
    ],
}
_GENERIC_FOLLOWUPS = [
    "How does this compare to last month?",
    "Break this down by category.",
    "Show me the trend over time.",
    "What about cart abandonment?",
]


def _suggest_followups(question: str, answer: str, seed: str) -> list[str]:
    text = f"{question} {answer}".lower()
    pool: list[str] = []
    for keyword, options in _KEYWORD_FOLLOWUPS.items():
        if keyword in text:
            pool.extend(options)
    pool.extend(_GENERIC_FOLLOWUPS)

    seen: set[str] = set()
    unique = [q for q in pool if not (q in seen or seen.add(q))]
    random.Random(seed).shuffle(unique)
    return unique[:4]


def render_followups(
    question: str, answer: str, seed: str, on_click: Callable[[str], None]
) -> None:
    suggestions = _suggest_followups(question, answer, seed)
    if not suggestions:
        return

    st.markdown('<p class="ss-followup-heading">Suggested follow-ups</p>', unsafe_allow_html=True)
    cols = st.columns(len(suggestions))
    for col, suggestion in zip(cols, suggestions):
        with col:
            st.markdown('<div class="ss-chip">', unsafe_allow_html=True)
            if st.button(suggestion, key=f"fu_{seed}_{suggestion}", use_container_width=True):
                on_click(suggestion)
            st.markdown("</div>", unsafe_allow_html=True)
