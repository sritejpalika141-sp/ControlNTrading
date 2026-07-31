"""Tests for security middleware."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.security_middleware import SecurityHeadersMiddleware


def test_security_headers_present():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/ping")
    assert r.status_code == 200
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "Referrer-Policy" in r.headers
