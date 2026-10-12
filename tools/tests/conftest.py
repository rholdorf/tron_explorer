import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

EXTRACTED = os.environ.get("TRON_EXTRACTED", "/Users/rui/src/pg/tron_explorer/extracted")


@pytest.fixture(scope="session")
def extracted():
    if not os.path.isdir(os.path.join(EXTRACTED, "worlds")):
        pytest.skip(f"game data not found at {EXTRACTED} (set TRON_EXTRACTED)")
    return EXTRACTED


@pytest.fixture(scope="session")
def world(extracted):
    """Loads (and caches) a level by its path under worlds/, without .dat."""
    import dat85
    cache = {}

    def load(name):
        if name not in cache:
            cache[name] = dat85.load(os.path.join(extracted, "worlds", name + ".dat"))
        return cache[name]
    return load
