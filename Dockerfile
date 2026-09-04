# =============================================================================
# ShopSense chatbot - Streamlit frontend + existing Google ADK agent, for
# Cloud Run.
#
# This file only packages the existing application; it contains no
# application logic. It expects the exact repo layout: frontend/, genai/
# shopsense_agent/, and semantic/ as sibling folders, because their own
# import path logic (frontend/config/settings.py's REPO_ROOT, and
# genai/shopsense_agent/__init__.py's two-levels-up REPO_ROOT) resolves
# `import semantic` / `from shopsense_agent...` relative to that layout,
# not relative to any Docker-specific PYTHONPATH trick.
# =============================================================================

FROM python:3.12-slim

# Cloud Run injects PORT at runtime (default 8080); this only matters for a
# local `docker run` that doesn't pass -e PORT.
ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so this layer is cached across code-only rebuilds.
# requirements.txt (repo root) is the pinned superset for Streamlit + the
# in-process ADK agent + the semantic layer - see its own header comment.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only what frontend/app.py and the ADK agent actually import - not the
# Cloud Functions, Terraform, SQL, docs, notebooks, or datasets.
COPY frontend/ frontend/
COPY genai/shopsense_agent/ genai/shopsense_agent/
COPY semantic/ semantic/
COPY .streamlit/ .streamlit/

# Run as a non-root user.
RUN useradd --create-home --uid 1000 shopsense \
    && chown -R shopsense:shopsense /app
USER shopsense

EXPOSE 8080

# Shell form (not exec-form) so $PORT is expanded by the shell at container
# start - Cloud Run sets a different PORT per revision/environment.
CMD streamlit run frontend/app.py \
    --server.address=0.0.0.0 \
    --server.port=$PORT \
    --server.headless=true
