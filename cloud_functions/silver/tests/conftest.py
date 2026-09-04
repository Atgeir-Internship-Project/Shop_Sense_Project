"""
Shared test setup.

The Cloud Function modules import each other flat (`import config`,
`from message import ...`), the same way they will on the Functions
runtime where the function directory is the working directory. Adding the
function directory to sys.path lets the tests import them the same way.
"""

import os
import sys

_FUNCTION_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if _FUNCTION_DIR not in sys.path:
    sys.path.insert(0, _FUNCTION_DIR)
