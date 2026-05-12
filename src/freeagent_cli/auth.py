from __future__ import annotations

import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from . import config as cfg


def _token_url(c: cfg.Config) -> str:
    return f"{c.api_base}/v2/token_endpoint"


def _authorize_url(c: cfg.Config) -> str:
    return f"{c.api_base}/v2/approve_app"


class _Handler(BaseHTTPRequestHandler):
    received: dict[str, str] = {}

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        _Handler.received = params
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        body = b"<html><body style='font-family:sans-serif;padding:2rem'>" \
               b"<h1>FreeAgent CLI authorised</h1>" \
               b"<p>You can close this tab and return to the terminal.</p>" \
               b"</body></html>"
        self.wfile.write(body)

    def log_message(self, *args, **kwargs):  # silence
        pass


def _wait_for_callback(port: int) -> dict[str, str]:
    _Handler.received = {}
    server = HTTPServer(("localhost", port), _Handler)
    server.handle_request()
    server.server_close()
    return _Handler.received


def login(c: cfg.Config) -> None:
    if not c.client_id or not c.client_secret:
        raise RuntimeError("client_id/client_secret not configured; run `auth init`")
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": c.client_id,
        "response_type": "code",
        "redirect_uri": c.redirect_uri,
        "state": state,
    }
    url = f"{_authorize_url(c)}?{urlencode(params)}"
    port = urlparse(c.redirect_uri).port or cfg.DEFAULT_PORT
    print(f"Opening browser for authorisation. If it doesn't open, visit:\n  {url}")
    webbrowser.open(url)
    received = _wait_for_callback(port)
    if "error" in received:
        raise RuntimeError(f"Authorisation failed: {received.get('error_description') or received['error']}")
    if received.get("state") != state:
        raise RuntimeError("OAuth state mismatch — possible CSRF; aborting.")
    code = received.get("code")
    if not code:
        raise RuntimeError(f"No authorisation code in callback: {received}")
    resp = httpx.post(
        _token_url(c),
        auth=(c.client_id, c.client_secret),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": c.redirect_uri,
        },
        timeout=30,
    )
    resp.raise_for_status()
    _apply_token_response(c, resp.json())
    cfg.save(c)


def refresh(c: cfg.Config) -> None:
    if not c.refresh_token:
        raise RuntimeError("No refresh token; run `auth login`")
    resp = httpx.post(
        _token_url(c),
        auth=(c.client_id, c.client_secret),
        data={
            "grant_type": "refresh_token",
            "refresh_token": c.refresh_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    _apply_token_response(c, resp.json())
    cfg.save(c)


def _apply_token_response(c: cfg.Config, payload: dict) -> None:
    c.access_token = payload["access_token"]
    c.access_token_expires_at = time.time() + int(payload.get("expires_in", 3600))
    if payload.get("refresh_token"):
        c.refresh_token = payload["refresh_token"]


def access_token(c: cfg.Config) -> str:
    if not c.access_token or time.time() >= c.access_token_expires_at - 60:
        refresh(c)
    return c.access_token
