import os
from pathlib import Path

# The mechanism tests (tiers, version preferences, speed weights) need a policy with distinct tiers. The live
# deploy/policy.toml has one DJ-quality rule since the 2026-10-17 pivot, so the suite reads a frozen copy of the
# old file. test_policy_file checks the live file separately. Set before sourcing.policy is first imported.
# Likewise the older tests exercise the comment-owned design (D21); the app-owned default has tests/test_app_owner.py.
os.environ["CRATES_OWNER"] = "comment"
os.environ["DJ_POLICY_FILE"] = str(Path(__file__).parent / "fixtures" / "policy-legacy.toml")

import pytest

from sourcing import acoustid
from sourcing.musicbrainz import reset_shared_limiter


@pytest.fixture(autouse=True)
def _fresh_musicbrainz_limiter():
    """The MusicBrainz and AcoustID limiters are process-wide: forget them around every test so order never
    matters."""
    reset_shared_limiter()
    acoustid.reset_shared_limiter()
    yield
    reset_shared_limiter()
    acoustid.reset_shared_limiter()
