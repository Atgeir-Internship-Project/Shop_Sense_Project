"""
Design tokens (CSS custom properties) + the single CSS injection point for
the ShopSense UI. Keeping every custom style here means the rest of the
UI code never embeds raw CSS inline.

Note on theming: this only styles elements ShopSense itself draws (hero,
sidebar, buttons, message bubbles) via CSS custom properties. Streamlit's
*own* native widgets (st.error, st.metric, st.dataframe, markdown text)
use Streamlit's internal theme, which is only switchable via
`.streamlit/config.toml` before the server starts - there is no supported
way to flip it at runtime from injected CSS without risking illegible
dark-on-dark text in those native widgets. So there is no dark-mode
toggle here; a real one would need a page reload against a config file,
which is a reasonable follow-up but out of scope for a CSS-only pass.

Note on animation: Streamlit re-executes the whole script on every
interaction, so a "message fade-in" effect would replay for *every*
message on *every* rerun, not just a newly-added one - that looks worse,
not premium. Kept animation to hover/press transitions on buttons and
cards, which are reliable pure-CSS pseudo-states, and left message
appearance un-animated.
"""

from __future__ import annotations

import streamlit as st

_TOKENS = {
    "--ss-bg": "#FFFFFF",
    "--ss-sidebar-bg": "#F3F4F6",
    "--ss-border": "#E5E7EB",
    "--ss-text": "#1F2933",
    "--ss-text-muted": "#6B7280",
    "--ss-primary": "#4F46E5",
    "--ss-primary-soft": "#EEF0FF",
}


def inject() -> None:
    variables = "\n".join(f"{k}: {v};" for k, v in _TOKENS.items())

    st.markdown(
        f"""
        <style>
        :root {{ {variables} }}

        #MainMenu, [data-testid="stMainMenu"] {{ visibility: hidden; }}
        footer, [data-testid="stStatusWidget"] {{ visibility: hidden; }}

        .main .block-container {{
            max-width: 860px;
            padding-top: 1.2rem;
            padding-bottom: 6rem;
        }}

        [data-testid="stSidebar"] {{
            background-color: var(--ss-sidebar-bg);
            border-right: 1px solid var(--ss-border);
        }}
        [data-testid="stSidebar"] .stButton > button {{ width: 100%; }}

        button[kind="secondary"] {{
            border-radius: 12px !important;
            text-align: left !important;
            white-space: pre-wrap !important;
            border: 1px solid var(--ss-border) !important;
            transition: box-shadow .15s ease, border-color .15s ease, transform .15s ease;
        }}
        button[kind="secondary"]:hover {{
            border-color: var(--ss-primary) !important;
            box-shadow: 0 3px 10px rgba(79, 70, 229, 0.15);
            transform: translateY(-1px);
        }}
        button[kind="primary"] {{
            border-radius: 12px !important;
            text-align: left !important;
            background-color: var(--ss-primary) !important;
            border-color: var(--ss-primary) !important;
            transition: transform .15s ease;
        }}
        button[kind="primary"]:hover {{ transform: translateY(-1px); }}

        .ss-chip button {{
            border-radius: 999px !important;
            font-size: 0.85rem !important;
            padding: 0.35rem 0.9rem !important;
            text-align: center !important;
            white-space: normal !important;
        }}

        [data-testid="stChatMessage"] {{
            background-color: transparent;
            border: none;
            padding: 0.2rem 0;
        }}

        .ss-msg-time {{
            font-size: 0.72rem;
            color: var(--ss-text-muted);
            margin: -0.3rem 0 0.5rem 0.3rem;
        }}

        .ss-user-msg {{
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            margin: 0.6rem 0 0.1rem 0;
        }}
        .ss-user-bubble {{
            background-color: var(--ss-primary-soft);
            color: var(--ss-text);
            border-radius: 14px;
            padding: 0.55rem 0.95rem;
            max-width: 78%;
            font-size: 0.95rem;
            line-height: 1.45;
            white-space: pre-wrap;
        }}

        .ss-hero {{ text-align: center; padding: 1.8rem 0 0.4rem 0; }}
        .ss-hero-icon {{ font-size: 2.6rem; line-height: 1; margin-bottom: 0.2rem; }}
        .ss-hero h1 {{
            color: var(--ss-text);
            font-size: 2rem;
            font-weight: 800;
            margin: 0.1rem 0;
        }}
        .ss-hero .ss-subtitle {{
            font-size: 1.02rem; font-weight: 600; color: var(--ss-primary); margin: 0.1rem 0;
        }}
        .ss-hero .ss-tagline {{
            font-size: 0.9rem; color: var(--ss-text-muted); max-width: 480px;
            margin: 0.5rem auto 0.2rem auto; line-height: 1.4;
        }}
        .ss-section-heading {{
            font-weight: 700; color: var(--ss-text); margin: 1.3rem 0 0.6rem 0;
            text-align: center; font-size: 1rem;
        }}
        .ss-followup-heading {{
            font-weight: 600; color: var(--ss-text-muted); margin: 1rem 0 0.5rem 0;
            font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.02em;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
