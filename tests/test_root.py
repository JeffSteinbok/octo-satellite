"""Tests for root endpoints and homepage."""


def test_root_homepage(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Octo Satellite" in resp.text
    assert "/docs" in resp.text
    assert "/openapi.json" in resp.text
    assert "/amazon/health" in resp.text
    assert "/monarch/health" in resp.text


def test_root_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_openapi_json(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    data = resp.json()
    assert "paths" in data
    assert "/monarch/sync-status" in data["paths"]
    assert "/monarch/refresh" in data["paths"]


def test_docs_page(client):
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert "swagger" in resp.text.lower() or "html" in resp.headers.get("content-type", "")
