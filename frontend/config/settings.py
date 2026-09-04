"""
Centralized, environment-based configuration for the ShopSense frontend.

Nothing here is a secret - real credentials live in `frontend/.env`
(gitignored) and are read directly by the existing ADK agent
(genai/shopsense_agent), not redefined here. This module only loads that
file and holds the small set of cosmetic/product constants the UI needs.
"""

from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

FRONTEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = FRONTEND_DIR.parent

# Loaded once, at first import, before any UI or service module runs -
# so GOOGLE_CLOUD_PROJECT / SHOPSENSE_* are set before adk_service ever
# imports genai/shopsense_agent/agent.py (which reads them at import time).
load_dotenv(FRONTEND_DIR / ".env")

# Every module in this app logs under the "shopsense" namespace
# (logging.getLogger("shopsense.<module>")) and relies on this handler by
# propagation - configuring it here, once, means every module's log lines
# actually reach the terminal running `streamlit run app.py`, regardless
# of whatever Streamlit's own logging setup does to the root logger.
_shopsense_logger = logging.getLogger("shopsense")
if not _shopsense_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s | %(name)s | %(message)s"))
    _shopsense_logger.addHandler(_handler)
    _shopsense_logger.setLevel(logging.INFO)
    _shopsense_logger.propagate = False

APP_NAME = "shopsense"
PRODUCT_NAME = "ShopSense AI"
PRODUCT_TAGLINE = "Your intelligent e-commerce analytics assistant"
PAGE_ICON = "🛍️"

# (icon, card title, question) shown on the welcome screen.
EXAMPLE_QUESTIONS: list[tuple[str, str, str]] = [
    ("📊", "Business Overview", "How many users and sessions do we have?"),
    ("💰", "Revenue", "Which categories generated the most revenue?"),
    ("🛒", "Funnel Analysis", "Where are customers dropping off?"),
    ("🎯", "Customer Intent", "Which users added products to cart but never purchased?"),
    ("📈", "Conversion", "What is the conversion rate by category?"),
    ("🏆", "Products", "Which products generated the highest revenue?"),
]
