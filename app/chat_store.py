"""
MongoDB-backed conversation store for CobbleAI.

Handles serialization of Anthropic SDK message objects so full
conversation state (including tool_use / tool_result blocks) can
be persisted and reloaded for multi-turn agents.
"""

import os
from datetime import datetime, timezone
from pymongo import MongoClient, DESCENDING


# ── Connection ──

_client = None
_db = None


def _get_db():
    global _client, _db
    if _db is None:
        uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
        db_name = os.getenv("MONGO_DB", "cobbleai")
        _client = MongoClient(uri)
        _db = _client[db_name]
    return _db


def conversations_col():
    return _get_db()["conversations"]


# ── Serialization helpers ──

def _clean_block(block):
    """Strip a content block down to only the fields the Anthropic API accepts."""
    if isinstance(block, dict):
        t = block.get("type")
    elif hasattr(block, "model_dump"):
        block = block.model_dump()
        t = block.get("type")
    else:
        return block

    if t == "text":
        return {"type": "text", "text": block.get("text", "")}
    elif t == "tool_use":
        return {"type": "tool_use", "id": block["id"], "name": block["name"], "input": block["input"]}
    elif t == "tool_result":
        return {"type": "tool_result", "tool_use_id": block["tool_use_id"], "content": block.get("content", "")}
    return block


def _serialize_content(content):
    """Convert message content to a MongoDB-safe format with only API-compatible fields."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return [_clean_block(item) for item in content]
    if hasattr(content, "model_dump"):
        return _clean_block(content)
    return content


def serialize_messages(messages):
    """Serialize a full messages list for MongoDB storage."""
    return [
        {"role": msg["role"], "content": _serialize_content(msg["content"])}
        for msg in messages
    ]


# ── CRUD ──

def create_conversation(conversation_id, title, user_id=None, username=None, messages=None):
    now = datetime.now(timezone.utc)
    doc = {
        "_id": conversation_id,
        "title": title,
        "user_id": user_id,
        "username": username,
        "messages": serialize_messages(messages or []),
        "created_at": now,
        "updated_at": now,
    }
    conversations_col().insert_one(doc)
    return doc


def get_conversation(conversation_id):
    return conversations_col().find_one({"_id": conversation_id})


def update_messages(conversation_id, messages):
    conversations_col().update_one(
        {"_id": conversation_id},
        {
            "$set": {
                "messages": serialize_messages(messages),
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )


def list_conversations(user_id=None, limit=50):
    query = {}
    if user_id:
        query["user_id"] = user_id
    cursor = (
        conversations_col()
        .find(query, {"title": 1, "created_at": 1})
        .sort("updated_at", DESCENDING)
        .limit(limit)
    )
    return [{"id": doc["_id"], "title": doc["title"]} for doc in cursor]


def get_display_messages(conversation_id):
    """Return only user/assistant text messages for the frontend."""
    convo = get_conversation(conversation_id)
    if not convo:
        return None
    display = []
    for msg in convo["messages"]:
        if msg["role"] == "user" and isinstance(msg["content"], str):
            display.append({"role": "user", "content": msg["content"]})
        elif msg["role"] == "assistant":
            # Extract text from content blocks
            content = msg["content"]
            if isinstance(content, str):
                display.append({"role": "assistant", "content": content})
            elif isinstance(content, list):
                texts = [
                    b["text"] for b in content
                    if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
                ]
                if texts:
                    display.append({"role": "assistant", "content": "\n".join(texts)})
    return {"id": convo["_id"], "title": convo["title"], "user_id": convo.get("user_id"), "messages": display}
