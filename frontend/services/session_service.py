"""
Conversation / session bookkeeping for the ShopSense UI.

Owns the shape of `st.session_state.conversations` and the small rules
around it: creating a conversation, generating its title, renaming,
deleting, clearing. This module never talks to ADK - adk_service.py does
that; this one only decides which `session_id` a message belongs to and
keeps the message list the UI renders.

Conversations (and their messages) live only in `st.session_state`, i.e.
only for the life of this browser tab's session - there is no database
behind this, matching "lightweight persistence that doesn't interfere
with ADK" rather than a competing storage layer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

import streamlit as st


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str
    timestamp: str
    error: bool = False
    sql: str | None = None
    rows: list[dict] | None = None
    row_count: int | None = None


@dataclass
class Conversation:
    conversation_id: str
    session_id: str  # the id passed to the ADK agent
    title: str = "New conversation"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    messages: list[Message] = field(default_factory=list)


def init_state() -> None:
    if "user_id" not in st.session_state:
        st.session_state.user_id = str(uuid.uuid4())
    if "conversations" not in st.session_state:
        st.session_state.conversations = {}  # conversation_id -> Conversation
    if "current_id" not in st.session_state:
        st.session_state.current_id = None


def start_new_chat() -> None:
    """"+ New Chat": go to the welcome screen. The conversation itself is
    created lazily by get_or_create_current() once the first question is
    actually sent, so an unused "New Chat" never litters the sidebar."""
    st.session_state.current_id = None


def current_conversation() -> Conversation | None:
    conv_id = st.session_state.current_id
    return st.session_state.conversations.get(conv_id) if conv_id else None


def get_or_create_current() -> Conversation:
    conv = current_conversation()
    if conv is not None:
        return conv
    conv_id = str(uuid.uuid4())
    conv = Conversation(conversation_id=conv_id, session_id=str(uuid.uuid4()))
    st.session_state.conversations[conv_id] = conv
    st.session_state.current_id = conv_id
    return conv


def add_message(conv: Conversation, message: Message) -> None:
    conv.messages.append(message)
    if message.role == "user" and conv.title == "New conversation":
        conv.title = make_title(message.content)


def make_title(question: str) -> str:
    """Simple deterministic title - no extra model call spent on this."""
    text = " ".join(question.strip().split()).rstrip("?").strip()
    if not text:
        return "New conversation"
    return text[:38] + "…" if len(text) > 38 else text


def select_conversation(conv_id: str) -> None:
    st.session_state.current_id = conv_id


def rename_conversation(conv_id: str, new_title: str) -> None:
    new_title = new_title.strip()
    if new_title and conv_id in st.session_state.conversations:
        st.session_state.conversations[conv_id].title = new_title


def delete_conversation(conv_id: str) -> None:
    st.session_state.conversations.pop(conv_id, None)
    if st.session_state.current_id == conv_id:
        st.session_state.current_id = None


def clear_current_conversation() -> None:
    conv = current_conversation()
    if conv is not None:
        conv.messages.clear()
        conv.title = "New conversation"


def clear_all_conversations() -> None:
    st.session_state.conversations.clear()
    st.session_state.current_id = None


def recent_conversations() -> list[Conversation]:
    """Most-recently-created first."""
    return list(reversed(list(st.session_state.conversations.values())))
