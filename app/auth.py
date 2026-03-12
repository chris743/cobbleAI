"""
Clerk authentication middleware for Flask.

Verifies Clerk session JWTs on protected routes using Clerk's JWKS endpoint.
Resolves Clerk user IDs to usernames via the Clerk Backend API (cached).
"""

import os
import base64
import functools
import jwt
from flask import request, jsonify
from clerk_backend_api import Clerk

_jwks_client = None
_clerk_api = None
_user_cache = {}  # user_id -> {"username": str, "email": str}


def _get_jwks_client():
    global _jwks_client
    if _jwks_client is None:
        pk = os.getenv("CLERK_PUBLISHABLE_KEY", "")
        encoded = pk.split("_")[-1]
        encoded += "=" * (4 - len(encoded) % 4) if len(encoded) % 4 else ""
        domain = base64.b64decode(encoded).decode("utf-8").rstrip("$")
        jwks_url = f"https://{domain}/.well-known/jwks.json"
        _jwks_client = jwt.PyJWKClient(jwks_url)
    return _jwks_client


def _get_clerk_api():
    global _clerk_api
    if _clerk_api is None:
        _clerk_api = Clerk(bearer_auth=os.getenv("CLERK_SECRET_KEY"))
    return _clerk_api


def get_clerk_user(user_id):
    """Resolve a Clerk user ID to username and email. Results are cached."""
    if user_id in _user_cache:
        return _user_cache[user_id]

    try:
        clerk = _get_clerk_api()
        u = clerk.users.get(user_id=user_id)
        info = {
            "username": f"{u.first_name or ''} {u.last_name or ''}".strip() or "Unknown",
            "email": u.email_addresses[0].email_address if u.email_addresses else None,
        }
        _user_cache[user_id] = info
        return info
    except Exception:
        return {"username": "Unknown", "email": None}


def verify_token(token):
    """Verify a Clerk session JWT. Returns the decoded claims or None."""
    try:
        client = _get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
        return claims
    except Exception:
        return None


def require_auth(f):
    """Flask route decorator that requires a valid Clerk session."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        if not token:
            token = request.cookies.get("__session")
        if not token:
            return jsonify({"error": "Authentication required"}), 401

        claims = verify_token(token)
        if not claims:
            return jsonify({"error": "Invalid or expired session"}), 401

        user_id = claims.get("sub")
        user_info = get_clerk_user(user_id)

        request.clerk_user_id = user_id
        request.clerk_username = user_info["username"]
        request.clerk_email = user_info["email"]
        return f(*args, **kwargs)
    return decorated
