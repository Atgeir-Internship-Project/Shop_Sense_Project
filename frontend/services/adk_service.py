"""
The ONLY integration point between this Streamlit UI and the existing
ShopSense chatbot (genai/shopsense_agent).

`send_message(question, session_id, user_id)` sends a question to the
existing Google ADK agent and returns a plain dict the UI can render.
This module contains no analytics logic, no SQL generation, and no
BigQuery code - all of that already lives in genai/shopsense_agent/*.

There is no `chat.py` in the existing project to call into - a Google ADK
agent (`root_agent` in genai/shopsense_agent/agent.py) has no callable
"ask" method of its own. It must be driven through ADK's `Runner`, which
needs a session and speaks in an async event stream. This module is the
minimum code required to do that; nothing here reimplements anything the
agent or its tools already do.

Follow-up context ("its conversion rate", "why?") comes for free from ADK
itself: reusing the SAME `session_id` across a conversation's messages
makes ADK's session service replay every prior turn to the agent
automatically - this module never builds a transcript by hand.
"""

from __future__ import annotations

import logging
import re
import sys
import time
from typing import Any

import streamlit as st

from config.settings import APP_NAME, REPO_ROOT

_log = logging.getLogger("shopsense.adk_service")

# Make the existing backend packages importable without installing them -
# repo root (for the `semantic` package) and genai/ (for `shopsense_agent`).
for _path in (REPO_ROOT, REPO_ROOT / "genai"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

GENERIC_ERROR = "Something went wrong while analyzing your data. Please try again."

# The agent occasionally names the underlying dimension/column it grouped
# by (e.g. "top-level category (`category_l1`)"). This UI wants plain
# language, so strip backtick-wrapped identifier tokens from its answer.
# Scoped narrowly to single-backtick `snake_case` spans so a real fenced
# ```sql block (returned separately as `sql`, see below) is untouched.
_COLUMN_TOKEN = r"`[a-zA-Z_][a-zA-Z0-9_]*`"
_PAREN_WITH_TOKEN = re.compile(rf"\s*\(\s*{_COLUMN_TOKEN}\s*\)")
_BARE_TOKEN = re.compile(_COLUMN_TOKEN)


def _strip_column_names(text: str) -> str:
    cleaned = _PAREN_WITH_TOKEN.sub("", text)
    cleaned = _BARE_TOKEN.sub("", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+([,.:;])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    return cleaned.strip()


# The source `price` column has no documented currency unit - it's just a
# float in the raw dataset - so a "$" the agent adds is an assumption this
# data never actually supports. Strip it (frontend-only cleanup, plain
# numbers only).
#
# This also fixes a real Streamlit rendering bug: st.markdown() treats a
# *pair* of `$` as inline LaTeX math (KaTeX). An answer with two or more
# dollar amounts had everything between the 1st and 2nd `$` silently
# rendered as one garbled math expression (italic, no spaces). No `$` left
# means no pair for Streamlit to misread.
_CURRENCY_SIGN = re.compile(r"\$(?=\d)")


def _strip_currency_symbols(text: str) -> str:
    return _CURRENCY_SIGN.sub("", text)


def send_message(
    question: str,
    session_id: str,
    user_id: str = "streamlit-user",
) -> dict[str, Any]:
    """
    Send `question` to the existing ShopSense ADK agent and return its answer.

    `session_id` identifies one conversation - reuse the same value across
    a conversation's turns to keep follow-up context working ("its",
    "why?", "compare it with..."); use a fresh uuid4() for a new chat.

    Returns:
        {"answer": str, "sql": str | None, "rows": list[dict] | None,
         "row_count": int | None, "error": str | None}
    """
    question = (question or "").strip()
    if not question:
        return _empty("Please type a question.")

    started = time.perf_counter()
    try:
        result = _run_agent(question, session_id, user_id)
    except Exception:  # noqa: BLE001 - never let this crash the UI
        _log.exception(
            "agent call failed after %.1fs (session=%s)",
            time.perf_counter() - started,
            session_id,
        )
        return _empty(GENERIC_ERROR)

    _log.info(
        "answer ready in %.1fs (session=%s, sql=%s)",
        time.perf_counter() - started,
        session_id[:8],
        bool(result.get("sql")),
    )
    return result


def _empty(error: str) -> dict[str, Any]:
    return {"answer": "", "sql": None, "rows": None, "row_count": None, "error": error}


# ---------------------------------------------------------------------------
# <<< YOUR EXISTING ADK AGENT IS CONNECTED HERE >>>
#
# `root_agent` is imported straight from genai/shopsense_agent/agent.py -
# nothing about the agent, its tools, or the semantic layer is redefined.
# If you ever move or rename the agent, this import is the only line to
# change in this whole module.
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def _get_runner():
    """
    Build the ADK Runner once per server process and reuse it (and its
    session store) for every rerun and every user. `st.cache_resource` is
    Streamlit's mechanism for exactly this kind of long-lived resource -
    rebuilding it per message would also throw away every conversation's
    history.
    """
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    from shopsense_agent.agent import root_agent  # <-- your existing ADK agent

    session_service = InMemorySessionService()
    runner = Runner(
        agent=root_agent, app_name=APP_NAME, session_service=session_service
    )
    return runner, session_service


def _run_agent(question: str, session_id: str, user_id: str) -> dict[str, Any]:
    from google.genai import types

    runner, sessions = _get_runner()

    async def _drive() -> list[Any]:
        # Create the session the first time this conversation sends a
        # message; reuse it (and its accumulated history) after that.
        try:
            existing = await sessions.get_session(
                app_name=APP_NAME, user_id=user_id, session_id=session_id
            )
        except Exception:  # noqa: BLE001
            existing = None
        if existing is None:
            await sessions.create_session(
                app_name=APP_NAME, user_id=user_id, session_id=session_id
            )

        message = types.Content(role="user", parts=[types.Part(text=question)])
        events: list[Any] = []
        async for event in runner.run_async(
            user_id=user_id, session_id=session_id, new_message=message
        ):
            events.append(event)
        return events

    events = _run_coroutine(_drive())
    return _extract_response(events)


def _run_coroutine(coro):
    """Run an async coroutine from Streamlit's synchronous script context."""
    import asyncio

    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is not None and running.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(coro)).result()
    return asyncio.run(coro)


def _extract_response(events: list[Any]) -> dict[str, Any]:
    """Read the agent's event stream: final text -> answer, tool result -> sql/rows."""

    answer_parts: list[str] = []
    sql: str | None = None
    rows: list[dict] | None = None
    row_count: int | None = None
    tool_error: str | None = None

    for event in events:
        for response in _tool_responses(event):
            if not isinstance(response, dict):
                continue
            if response.get("sql"):
                sql = response["sql"]
            if response.get("rows") is not None:
                rows = list(response["rows"])
                row_count = response.get("row_count", len(rows))
            if response.get("error"):
                tool_error = response["error"]

        is_final = getattr(event, "is_final_response", None)
        if callable(is_final) and is_final():
            content = getattr(event, "content", None)
            for part in getattr(content, "parts", None) or []:
                text = getattr(part, "text", None)
                if text:
                    answer_parts.append(text)

    answer = "\n".join(chunk for chunk in answer_parts if chunk).strip()

    if not answer:
        return _empty(tool_error or GENERIC_ERROR)

    answer = _strip_currency_symbols(_strip_column_names(answer))

    return {
        "answer": answer,
        "sql": sql,
        "rows": rows,
        "row_count": row_count,
        "error": None,
    }


def _tool_responses(event: Any) -> list[Any]:
    """Pull the {"sql", "rows", ...} dict(s) a tool call returned, if any."""
    getter = getattr(event, "get_function_responses", None)
    if not callable(getter):
        return []
    try:
        return [getattr(item, "response", item) for item in (getter() or [])]
    except Exception:  # noqa: BLE001
        return []
