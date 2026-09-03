"""
The ShopSense analyst agent, wired for Google ADK.

`adk web` (run from the `genai/` directory) discovers `root_agent` here.
"""

from __future__ import annotations

import os

from google.adk.agents import Agent

from semantic import SemanticLayer

from . import tools
from .prompts import INSTRUCTION

_MODEL = os.environ.get("SHOPSENSE_AGENT_MODEL", "gemini-3.5-flash-lite")


def _catalog_block() -> str:
    """Render the catalog into the instruction so the agent never has to fetch it."""
    cat = SemanticLayer.load().describe()
    lines = ["# CATALOG", "", "## Metrics (name - meaning)"]
    for name, spec in cat["metrics"].items():
        lines.append(f"- {name}: {spec['description'] or spec['label']}")
    lines.append("")
    lines.append("## Dimensions (name - synonyms)")
    for name, spec in cat["dimensions"].items():
        syn = f"  (also: {', '.join(spec['synonyms'])})" if spec["synonyms"] else ""
        lines.append(f"- {name}{syn}")
    lines.append("")
    lines.append(f"## Time grains: {', '.join(cat['time_grains'])}")
    lines.append("## Segments: " + ", ".join(cat["segments"]))
    return "\n".join(lines)


root_agent = Agent(
    name="shopsense_analyst",
    model=_MODEL,
    description=(
        "Conversational analyst for ShopSense e-commerce event data "
        "(views, carts, purchases; Oct-Nov 2019). Answers questions about the "
        "funnel, conversion, revenue, categories, brands and user intent by "
        "querying the trusted semantic layer - never by guessing numbers."
    ),
    instruction=INSTRUCTION + "\n\n" + _catalog_block(),
    tools=[
        tools.get_semantic_catalog,
        tools.explain_metric,
        tools.run_metric_query,
        tools.run_segment_query,
    ],
)
