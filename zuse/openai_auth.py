"""Codex 'Sign in with ChatGPT' OAuth (PKCE loopback flow).

Reverse-engineered from the open-source Codex CLI: it uses Codex's public
OAuth client against auth.openai.com and yields a token usable against the
Codex Responses backend (chatgpt.com/backend-api/codex). This is unofficial
for third-party apps and may change — treat as best-effort.

Tokens are stored in ~/.zuse/openai_auth.json and refreshed on demand.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

from .config import CONFIG_DIR, ensure_dirs

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
SCOPE = "openid profile email offline_access"
REDIRECT_PORT = 1455
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/auth/callback"
CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
_REFRESH_SKEW = 120  # refresh this many seconds before expiry

AUTH_FILE = CONFIG_DIR / "openai_auth.json"

_SUCCESS_HTML = (
    "<html><body style='font-family:sans-serif;background:#0b0f14;color:#e5e7eb;"
    "text-align:center;padding-top:18%'><h2>✓ Zuse is signed in</h2>"
    "<p>You can close this tab and return to the terminal.</p></body></html>"
)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


def _decode_jwt_account_id(id_token: str) -> str | None:
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        auth = claims.get("https://api.openai.com/auth", {})
        return auth.get("chatgpt_account_id") or auth.get("account_id")
    except Exception:  # noqa: BLE001
        return None


class _CallbackHandler(BaseHTTPRequestHandler):
    code: str | None = None
    state: str | None = None

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.startswith("/auth/callback"):
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        _CallbackHandler.code = (params.get("code") or [None])[0]
        _CallbackHandler.state = (params.get("state") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(_SUCCESS_HTML.encode())

    def log_message(self, *args):  # silence the default request logging
        pass


def login(open_browser: bool = True, timeout: int = 300) -> dict:
    """Run the interactive OAuth flow and persist the tokens. Returns the saved
    auth dict. Raises RuntimeError on failure."""
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "state": state,
    }
    url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    _CallbackHandler.code = None
    _CallbackHandler.state = None
    try:
        server = HTTPServer(("localhost", REDIRECT_PORT), _CallbackHandler)
    except OSError as e:
        raise RuntimeError(f"Could not bind localhost:{REDIRECT_PORT} for the OAuth callback: {e}")
    server.timeout = timeout

    print(f"\nOpen this URL to sign in with ChatGPT:\n  {url}\n")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    # Serve requests until we capture the callback or time out.
    deadline = time.monotonic() + timeout
    while _CallbackHandler.code is None and time.monotonic() < deadline:
        server.handle_request()
    server.server_close()

    if _CallbackHandler.code is None:
        raise RuntimeError("Timed out waiting for the OAuth callback.")
    if _CallbackHandler.state != state:
        raise RuntimeError("OAuth state mismatch — aborting for safety.")

    tokens = _exchange_code(_CallbackHandler.code, verifier)
    return _save_tokens(tokens)


def _exchange_code(code: str, verifier: str) -> dict:
    resp = httpx.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    }, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Token exchange failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json()


def _refresh(refresh_token: str) -> dict:
    resp = httpx.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": refresh_token,
        "scope": SCOPE,
    }, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Token refresh failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json()


def _save_tokens(tok: dict, prior: dict | None = None) -> dict:
    ensure_dirs()
    expires_in = tok.get("expires_in", 3600)
    data = {
        "access_token": tok.get("access_token"),
        "refresh_token": tok.get("refresh_token") or (prior or {}).get("refresh_token"),
        "id_token": tok.get("id_token") or (prior or {}).get("id_token"),
        "account_id": _decode_jwt_account_id(tok.get("id_token", ""))
        or (prior or {}).get("account_id"),
        "expires_at": time.time() + expires_in,
    }
    AUTH_FILE.write_text(json.dumps(data, indent=2))
    try:
        AUTH_FILE.chmod(0o600)
    except OSError:
        pass
    return data


def load_auth() -> dict | None:
    if not AUTH_FILE.exists():
        return None
    try:
        return json.loads(AUTH_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def logged_in() -> bool:
    a = load_auth()
    return bool(a and a.get("access_token"))


def get_access_token() -> tuple[str, str | None]:
    """Return a valid (access_token, account_id), refreshing if near expiry."""
    auth = load_auth()
    if not auth or not auth.get("access_token"):
        raise RuntimeError("Not signed in. Run `zuse login` first.")
    if time.time() >= auth.get("expires_at", 0) - _REFRESH_SKEW:
        if not auth.get("refresh_token"):
            raise RuntimeError("Session expired and no refresh token. Run `zuse login` again.")
        auth = _save_tokens(_refresh(auth["refresh_token"]), prior=auth)
    return auth["access_token"], auth.get("account_id")
