"""ShopSense conversational analyst agent (Google ADK)."""

import os
import sys

# The semantic layer package lives at the repo root - make it importable
# before anything in this package tries to `from semantic import ...`.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# `adk web` imports `agent.root_agent` from here. Guarded so the package is
# still importable (for the tools + tests) in an environment without google-adk.
try:  # pragma: no cover - exercised only with google-adk installed
    from . import agent
except ImportError:  # pragma: no cover
    agent = None  # type: ignore[assignment]

__all__ = ["agent"]
