import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

EXTRACTED = os.environ.get("TRON_EXTRACTED", "/Users/rui/src/pg/tron_explorer/extracted")


@pytest.fixture(scope="session")
def extracted():
    if not os.path.isdir(EXTRACTED):
        pytest.skip(f"game data not found at {EXTRACTED} (set TRON_EXTRACTED)")
    return EXTRACTED
