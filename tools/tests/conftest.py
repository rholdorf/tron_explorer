import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

EXTRACTED = os.environ.get("TRON_EXTRACTED", "/Users/rui/src/pg/tron_explorer/extracted")


@pytest.fixture
def extracted():
    if not os.path.isdir(EXTRACTED):
        pytest.skip(f"extracted game data not found at {EXTRACTED}")
    return EXTRACTED
