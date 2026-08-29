"""
Shared test setup - put the function directory on sys.path so the flat
imports (`import config`, `from build import ...`) resolve the same way
they do on the Cloud Functions runtime.
"""

import os
import sys

_FUNCTION_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if _FUNCTION_DIR not in sys.path:
    sys.path.insert(0, _FUNCTION_DIR)
