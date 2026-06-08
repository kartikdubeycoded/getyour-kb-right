"""Optional shared-secret gate for the write/trigger endpoints (/ingest, /refresh-all).

OPT-IN: while INGEST_TOKEN is unset (or blank) the endpoints stay open — fine on localhost in
dev. Set INGEST_TOKEN in the environment BEFORE exposing the app through a tunnel, so the public
webhook URL can't be hit by anyone who learns it (the review's "unauth POST" hole). The client
sends the secret in the `X-Ingest-Token` header; we compare in constant time."""

import hmac
import os

from fastapi import Header, HTTPException


def require_ingest_token(x_ingest_token: str | None = Header(default=None)) -> None:
    """FastAPI dependency. No-op when INGEST_TOKEN is unset/blank; otherwise the request must
    carry a matching X-Ingest-Token header or get 401 (rejected before the route body runs, so
    no work or outbound fetch happens on a bad token)."""
    expected = os.environ.get("INGEST_TOKEN", "").strip()
    if not expected:
        return  # not configured -> open (dev / localhost)
    provided = (x_ingest_token or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid or missing ingest token")
