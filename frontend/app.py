"""
ShopSense AI - entrypoint.

This file only wires the pieces together: bootstrap session state, draw
the sidebar, show the welcome screen or the active conversation, and
route the chat input / card clicks / follow-up clicks through one `_send`
handler. All real logic lives in:

    services/session_service.py  - conversation/session bookkeeping
    services/adk_service.py      - the one integration point with ADK
    ui/*                          - rendering

Run: streamlit run app.py   (from the frontend/ directory)
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from config.settings import PAGE_ICON, PRODUCT_NAME
from services import adk_service
from services import session_service as sessions
from services.session_service import Message
from ui import chat, sidebar, styles, welcome

st.set_page_config(
    page_title=f"{PRODUCT_NAME} · Analytics", page_icon=PAGE_ICON, layout="wide"
)

sessions.init_state()
styles.inject()


def _now() -> str:
    return datetime.now().strftime("%I:%M %p").lstrip("0")


def _send(question: str) -> None:
    question = question.strip()
    if not question:
        return

    conv = sessions.get_or_create_current()
    sessions.add_message(conv, Message(role="user", content=question, timestamp=_now()))

    with chat.loading_spinner():
        response = adk_service.send_message(
            question, session_id=conv.session_id, user_id=st.session_state.user_id
        )

    if response.get("error"):
        sessions.add_message(
            conv,
            Message(role="assistant", content=response["error"], timestamp=_now(), error=True),
        )
    else:
        sessions.add_message(
            conv,
            Message(
                role="assistant",
                content=response["answer"],
                timestamp=_now(),
                sql=response.get("sql"),
                rows=response.get("rows"),
                row_count=response.get("row_count"),
            ),
        )
    st.rerun()


sidebar.render()

current = sessions.current_conversation()

if current is None:
    welcome.render(on_ask=_send)
else:
    st.caption(PRODUCT_NAME)

    for msg in current.messages:
        chat.render_message(msg)

    last = current.messages[-1] if current.messages else None
    if last and last.role == "assistant" and not last.error:
        last_user = next(
            (m.content for m in reversed(current.messages) if m.role == "user"), ""
        )
        chat.render_followups(
            last_user,
            last.content,
            seed=f"{current.conversation_id}:{len(current.messages)}",
            on_click=_send,
        )

typed_question = st.chat_input("Ask ShopSense anything about your data...")
if typed_question:
    _send(typed_question)
