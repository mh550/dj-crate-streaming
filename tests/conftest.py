import pytest

from sourcing.musicbrainz import reset_shared_limiter


@pytest.fixture(autouse=True)
def _fresh_musicbrainz_limiter():
    """The MusicBrainz limiter is process-wide: forget it around every test so order never matters."""
    reset_shared_limiter()
    yield
    reset_shared_limiter()
