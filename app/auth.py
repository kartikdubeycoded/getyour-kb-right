"""Optional shared-secret gate for the WHOLE app (every route except /health and /static).

OPT-IN: while INGEST_TOKEN is unset (or blank) everything stays open — fine on localhost in dev.
Set INGEST_TOKEN in the environment BEFORE exposing the app through a tunnel, so a public URL
can't read your corpus or trigger ingests/fetches.

Two transports, one secret:
- machines (the iOS Shortcut) send it in the `X-Ingest-Token` header;
- a browser viewing the dashboard sends it as the HTTP Basic-Auth password (any username) —
  the browser shows a login box when it gets our 401 + WWW-Authenticate challenge.
Both are compared in constant time."""

import base64
import binascii
import hmac
import os

# Routes that must work without the token: liveness probes and public CSS (no secrets there).
EXEMPT_PREFIXES = ("/health", "/static")


def _expected_token() -> str:
    return os.environ.get("INGEST_TOKEN", "").strip()


def _matches(provided: str, expected: str) -> bool:
    """Constant-time equality. Defensive against non-ASCII input (compare_digest raises TypeError
    on it) — a malformed value is simply 'not a match', never a crash."""
    if not provided:
        return False
    try:
        return hmac.compare_digest(provided, expected)
    except TypeError:
        return False


def _password_from_basic_auth(authorization: str | None) -> str:
    """The password out of an `Authorization: Basic base64(user:pass)` header. Username is ignored;
    the password is the shared token. Returns '' if the header is absent or malformed."""
    if not authorization or not authorization.lower().startswith("basic "):
        return ""
    try:
        raw = base64.b64decode(authorization[6:].strip(), validate=True)
        decoded = raw.decode("utf-8", "replace")
    except (binascii.Error, ValueError):
        return ""
    _user, _sep, password = decoded.partition(":")
    return password


def is_authorized(x_ingest_token: str | None, authorization: str | None) -> bool:
    """True when the gate is disabled (no token configured) OR the request carries the shared secret
    via the X-Ingest-Token header or HTTP Basic Auth."""
    expected = _expected_token()
    if not expected:
        return True  # gate off (localhost dev)
    if _matches((x_ingest_token or "").strip(), expected):
        return True
    return _matches(_password_from_basic_auth(authorization).strip(), expected)


def is_exempt(path: str) -> bool:
    """Paths that bypass the gate entirely (liveness + public static assets)."""
    return any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES)
