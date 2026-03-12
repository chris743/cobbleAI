"""Thread-safe user context for agent tool calls.

Allows tools (like O365) to access the current user's identity without
changing the handle_tool_call() signature.
"""

import contextvars

_current_user_id = contextvars.ContextVar('current_user_id', default=None)


def set_user_id(uid: str):
    _current_user_id.set(uid)


def get_user_id() -> str | None:
    return _current_user_id.get()
