"""M6 Task 5 (D19): the stream choice "server" sends no format and no maxBitRate, so Navidrome's per-player
transcoding profile decides. It is the default; the opus presets stay as overrides."""
from pathlib import Path

from tests.test_service import get, svc  # noqa: F401  (svc is a fixture)

WEB = Path(__file__).resolve().parent.parent / "web"


def test_server_tier_redirect_carries_no_format_or_bitrate(svc):  # noqa: F811
    fake, app, srv = svc
    s, h, _ = get(srv.url + "/api/stream/s1?tier=server", raw=True)
    loc = h["Location"]
    assert s == 302 and "/rest/stream.view?" in loc
    assert "format=" not in loc and "maxBitRate" not in loc


def test_fresh_store_streams_server_and_lists_it_first(svc):  # noqa: F811
    fake, app, srv = svc
    s, _, v = get(srv.url + "/api/stream-tier")
    assert s == 200 and v["tier"] == "server" and list(v["tiers"])[0] == "server"
    assert v["tiers"]["server"] == {"format": None, "maxBitRate": None}


def test_web_menu_labels_server():
    html = (WEB / "index.html").read_text()
    assert 'value="server" selected' in html and "server · Navidrome decides" in html
    assert "Navidrome decides" in (WEB / "app.js").read_text()
