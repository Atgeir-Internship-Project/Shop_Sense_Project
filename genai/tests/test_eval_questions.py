"""
Verify every question in eval/eval_questions.yaml compiles to valid SQL through
the semantic layer. This is the automated half of the agent eval - it proves
the catalog *can* answer each canonical question. The other half (does the LLM
pick the right call, is the phrasing of the answer good) needs a live model and
is run from eval_questions.yaml manually / via `adk eval`.
"""

import os
import pathlib
import sys

import pytest
import yaml

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from semantic import SemanticLayer  # noqa: E402
from shopsense_agent import tools  # noqa: E402

_EVAL_FILE = pathlib.Path(__file__).parents[1] / "eval" / "eval_questions.yaml"
_CASES = yaml.safe_load(_EVAL_FILE.read_text(encoding="utf-8"))


class _CaptureRunner:
    def __init__(self):
        self.compiled = None

    def execute(self, compiled):
        self.compiled = compiled
        return {"sql": compiled.sql, "row_count": 0, "rows": [], "truncated": False}


@pytest.fixture
def capture():
    runner = _CaptureRunner()
    tools.configure(semantic_layer=SemanticLayer.load(), runner=runner)
    return runner


@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_eval_question_compiles(case, capture):
    tool_fn = {
        "run_metric_query": tools.run_metric_query,
        "run_segment_query": tools.run_segment_query,
        "explain_metric": tools.explain_metric,
    }[case["tool"]]

    result = tool_fn(**case["call"])

    assert "error" not in result, f"{case['id']}: {result.get('error')}"
    if case["tool"] != "explain_metric":
        assert capture.compiled is not None
        assert capture.compiled.sql.lstrip().startswith("SELECT")


def test_all_cases_have_required_fields():
    for case in _CASES:
        assert {"id", "question", "tool", "call", "expect"} <= case.keys()
