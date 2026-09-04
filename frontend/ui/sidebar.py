"""Sidebar: brand header, + New Chat, Recent Chats (rename/delete), Settings."""

from __future__ import annotations

import streamlit as st

from config.settings import PAGE_ICON, PRODUCT_NAME
from services import session_service as sessions
from services.session_service import Conversation


def render() -> None:
    with st.sidebar:
        st.markdown(f"### {PAGE_ICON} {PRODUCT_NAME}")
        st.caption("AI Analytics Assistant")
        st.write("")

        if st.button("+ New Chat", type="primary", use_container_width=True):
            sessions.start_new_chat()
            st.rerun()

        conversations = sessions.recent_conversations()
        if conversations:
            st.write("")
            st.caption("RECENT CHATS")
            for conv in conversations:
                _render_conversation_row(conv)

        st.divider()
        _render_settings()


def _render_conversation_row(conv: Conversation) -> None:
    is_active = conv.conversation_id == st.session_state.current_id
    col_select, col_menu = st.columns([5, 1])

    with col_select:
        if st.button(
            conv.title,
            key=f"select_{conv.conversation_id}",
            type="primary" if is_active else "secondary",
            use_container_width=True,
        ):
            sessions.select_conversation(conv.conversation_id)
            st.rerun()

    with col_menu:
        with st.popover("⋮"):
            st.caption("Rename conversation")
            new_title = st.text_input(
                "Rename",
                value=conv.title,
                key=f"rename_input_{conv.conversation_id}",
                label_visibility="collapsed",
                placeholder="Conversation name",
            )
            r1, r2 = st.columns(2)
            with r1:
                if st.button(
                    "Save", key=f"rename_save_{conv.conversation_id}", use_container_width=True
                ):
                    sessions.rename_conversation(conv.conversation_id, new_title)
                    st.rerun()
            with r2:
                if st.button(
                    "Delete", key=f"delete_{conv.conversation_id}", use_container_width=True
                ):
                    sessions.delete_conversation(conv.conversation_id)
                    st.rerun()


def _render_settings() -> None:
    with st.popover("⚙️ Settings", use_container_width=True):
        if st.button("Clear current conversation", use_container_width=True):
            sessions.clear_current_conversation()
            st.rerun()
        if st.button("Clear all conversations", use_container_width=True):
            sessions.clear_all_conversations()
            st.rerun()

        st.divider()
        st.caption("About ShopSense")
        st.caption(
            "ShopSense AI answers questions about e-commerce events "
            "(views, carts, purchases) by querying the ShopSense BigQuery "
            "Gold layer through a Google ADK analyst agent. Conversations "
            "live only in this browser tab."
        )
