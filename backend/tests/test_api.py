"""
Basic API-flow tests: health check, unsupported file rejection, and
GET-by-name for a non-existent document. These don't require a live
ANTHROPIC_API_KEY since they exercise the validation/error paths, which
run before any LLM call.
"""
import io

from fastapi.testclient import TestClient

from app.main import app

# Using the context-manager form ensures FastAPI's startup event (which
# calls init_db()) actually runs before the tests hit the DB.
client = TestClient(app)
client.__enter__()


def test_health_check():
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_unsupported_file_type_is_rejected():
    fake_file = io.BytesIO(b"not a real document")
    res = client.post(
        "/api/v1/documents/process",
        files={"file": ("notes.txt", fake_file, "text/plain")},
        data={"document_type": "invoice"},
    )
    assert res.status_code == 422
    body = res.json()
    assert body["detail"]["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_empty_file_is_rejected():
    empty_file = io.BytesIO(b"")
    res = client.post(
        "/api/v1/documents/process",
        files={"file": ("empty.pdf", empty_file, "application/pdf")},
        data={"document_type": "invoice"},
    )
    assert res.status_code == 422
    assert res.json()["detail"]["error"]["code"] == "EMPTY_FILE"


def test_get_unknown_document_returns_404():
    res = client.get("/api/v1/documents/does-not-exist.pdf")
    assert res.status_code == 404
    assert res.json()["detail"]["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_list_documents_returns_list():
    res = client.get("/api/v1/documents")
    assert res.status_code == 200
    assert isinstance(res.json(), list)
