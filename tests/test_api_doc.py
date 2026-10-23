"""S3-05: docs/api.md documents the request endpoints for a future client."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "api.md"

ROUTES = ["POST /api/requests", "GET /api/requests", "GET /api/requests/<id>", "POST /api/requests/<id>/preview",
          "POST /api/requests/<id>/approve", "GET /api/catalog/search"]
# the ApiError statuses crates/service.py raises for these routes (grep ApiError there)
STATUSES = [400, 404, 409, 502, 503]


def test_the_doc_names_every_request_route():
    text = DOC.read_text()
    for route in ROUTES:
        assert f"`{route}`" in text, route


def test_the_doc_names_every_error_status_the_handlers_raise():
    text = DOC.read_text()
    for status in STATUSES:
        assert re.search(rf"\b{status}\b", text), status


def test_the_handlers_raise_no_status_the_doc_leaves_out():
    src = (ROOT / "crates" / "service.py").read_text()
    start, end = src.index("def catalog_search"), src.index("# --- ", src.index("def approve_request"))
    raised = {int(n) for n in re.findall(r"ApiError\((\d{3})", src[start:end])}
    assert raised <= set(STATUSES)


def test_the_doc_has_the_client_flow_and_links_from_the_architecture_and_worker_docs():
    text = DOC.read_text()
    assert "## For a client" in text and "/api/events" in text
    assert "api.md" in (ROOT / "docs" / "architecture.md").read_text()
    assert "api.md" in (ROOT / "docs" / "worker.md").read_text()


def test_the_doc_says_no_peer_or_library_path_appears():
    text = DOC.read_text().lower()
    assert "peer" in text and "path" in text and "tailnet" in text
