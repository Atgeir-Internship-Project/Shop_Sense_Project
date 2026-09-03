"""Put `genai/` on sys.path so `import shopsense_agent` resolves in tests."""

import os
import sys

_GENAI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if _GENAI_DIR not in sys.path:
    sys.path.insert(0, _GENAI_DIR)
