"""Welcome / empty-state screen: hero header + suggestion cards."""

from __future__ import annotations

from typing import Callable

import streamlit as st

from config.settings import EXAMPLE_QUESTIONS, PAGE_ICON, PRODUCT_NAME, PRODUCT_TAGLINE


def render(on_ask: Callable[[str], None]) -> None:
    st.markdown(
        f"""
        <div class="ss-hero">
            <div class="ss-hero-icon">{PAGE_ICON}</div>
            <h1>{PRODUCT_NAME}</h1>
            <p class="ss-subtitle">{PRODUCT_TAGLINE}</p>
            <p class="ss-tagline">
                Ask questions about users, sessions, products, categories,
                brands, views, carts, purchases, revenue, conversion and
                customer behavior.
            </p>
        </div>
        <p class="ss-section-heading">What would you like to know?</p>
        """,
        unsafe_allow_html=True,
    )

    cols = st.columns(2)
    for i, (icon, title, question) in enumerate(EXAMPLE_QUESTIONS):
        with cols[i % 2]:
            label = f"{icon}  **{title}**\n{question}"
            if st.button(label, key=f"example_{i}", use_container_width=True):
                on_ask(question)
