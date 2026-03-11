"""Microsoft 365 OAuth integration with per-user token storage in MongoDB."""

import os
from datetime import datetime, timezone

from O365 import Account
from O365.utils import BaseTokenBackend

from chat_store import _get_db


# ── MongoDB token backend ────────────────────────────────────────────────────

class _MongoTokenBackend(BaseTokenBackend):
    """Store O365 MSAL token cache in MongoDB, keyed by Clerk user ID."""

    def __init__(self, user_id: str):
        super().__init__()
        self.user_id = user_id

    def _col(self):
        return _get_db()["o365_tokens"]

    def load_token(self) -> bool:
        doc = self._col().find_one({"user_id": self.user_id})
        if doc and doc.get("token_cache"):
            self._cache = doc["token_cache"]
            return True
        return False

    def save_token(self, force=False) -> bool:
        if not self._cache:
            return False
        if not force and not self._has_state_changed:
            return True
        self._col().update_one(
            {"user_id": self.user_id},
            {"$set": {"token_cache": self._cache, "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        self._has_state_changed = False
        return True

    def delete_token(self) -> bool:
        self._col().delete_one({"user_id": self.user_id})
        self._cache = {}
        return True

    def check_token(self) -> bool:
        doc = self._col().find_one({"user_id": self.user_id})
        return bool(doc and doc.get("token_cache"))


# ── OAuth state → user mapping (in-memory, short-lived) ──────────────────────

_pending_auth = {}  # state_string -> user_id


# ── Config helpers ───────────────────────────────────────────────────────────

SCOPES = [
    "User.Read",
    "Mail.Read",
    "Mail.Send",
    "Calendars.Read",
    "Files.Read.All",
    "Sites.Read.All",
]


def _get_credentials():
    client_id = os.getenv("O365_CLIENT_ID", "")
    client_secret = os.getenv("O365_CLIENT_SECRET", "")
    return client_id, client_secret


def _get_tenant():
    return os.getenv("O365_TENANT_ID", "common")


def is_configured() -> bool:
    client_id, client_secret = _get_credentials()
    return bool(client_id and client_secret)


def _make_account(user_id: str) -> Account:
    credentials = _get_credentials()
    return Account(
        credentials,
        auth_flow_type="authorization",
        tenant_id=_get_tenant(),
        token_backend=_MongoTokenBackend(user_id),
    )


# ── Public API ───────────────────────────────────────────────────────────────

def get_auth_url(user_id: str, redirect_uri: str) -> tuple[str, str]:
    """Generate an OAuth authorization URL. Returns (url, state)."""
    account = _make_account(user_id)
    url, state = account.con.get_authorization_url(
        requested_scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    # O365 lib returns state as the full MSAL flow dict (contains PKCE verifier, nonce, etc.)
    flow = state
    state_str = flow["state"] if isinstance(flow, dict) else str(flow)
    _pending_auth[state_str] = {"user_id": user_id, "account": account, "flow": flow}
    print(f"[O365] Stored state key: {state_str!r}")
    return url, state_str


def complete_auth(callback_url: str, redirect_uri: str, state: str) -> tuple[bool, str | None]:
    """Exchange the authorization code for tokens. Returns (success, error_msg)."""
    print(f"[O365] Callback state: {state!r}")
    print(f"[O365] Pending keys: {list(_pending_auth.keys())}")
    entry = _pending_auth.pop(state, None)
    if not entry:
        return False, "Invalid or expired OAuth state. Please try connecting again."

    # Reuse the same Account object and pass the MSAL flow dict
    account = entry["account"]
    flow = entry["flow"]

    try:
        result = account.con.request_token(
            authorization_url=callback_url,
            flow=flow,
        )
        if result:
            return True, None
        return False, "Token exchange returned False — check Azure app configuration."
    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"Token exchange failed: {e}"


def get_account(user_id: str) -> Account | None:
    """Get an authenticated O365 Account for a user, or None."""
    if not is_configured():
        return None
    account = _make_account(user_id)
    if account.is_authenticated:
        return account
    return None


def is_connected(user_id: str) -> bool:
    """Check if a user has a valid O365 connection."""
    return get_account(user_id) is not None


def disconnect(user_id: str):
    """Remove a user's O365 tokens."""
    _MongoTokenBackend(user_id).delete_token()
