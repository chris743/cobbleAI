"""
Living Documents — shared, globally-consistent daily documents.

Stores document definitions (name, prompt) and daily snapshots in MongoDB.
All users see the same snapshot for any given day, making plans and reports
consistent regardless of who is asking.
"""

import re
from datetime import datetime, timezone, date
from bson import ObjectId
from pymongo import DESCENDING
from chat_store import _get_db


def _docs_col():
    return _get_db()["living_documents"]


def _snaps_col():
    return _get_db()["living_document_snapshots"]


def _to_dict(doc):
    if doc is None:
        return None
    d = dict(doc)
    d["id"] = str(d.pop("_id"))
    # Convert datetime fields for JSON serialization
    for key in ("created_at",):
        if key in d and hasattr(d[key], "isoformat"):
            d[key] = d[key].isoformat()
    return d


def create_doc(name: str, description: str, prompt: str,
               created_by: str = None, username: str = None) -> dict:
    now = datetime.now(timezone.utc)
    result = _docs_col().insert_one({
        "name": name,
        "description": description,
        "prompt": prompt,
        "created_by": created_by,
        "created_by_username": username,
        "created_at": now,
        "active": True,
    })
    return {
        "id": str(result.inserted_id),
        "name": name,
        "description": description,
        "prompt": prompt,
        "created_by_username": username,
    }


def get_doc(doc_id: str) -> dict | None:
    try:
        oid = ObjectId(doc_id)
    except Exception:
        return None
    return _to_dict(_docs_col().find_one({"_id": oid, "active": True}))


def get_doc_by_name(name: str) -> dict | None:
    doc = _docs_col().find_one({
        "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"},
        "active": True,
    })
    return _to_dict(doc)


def list_docs() -> list[dict]:
    return [_to_dict(d) for d in _docs_col().find({"active": True}).sort("name", 1)]


def get_latest_snapshot(doc_id: str) -> dict | None:
    snap = _snaps_col().find_one({"doc_id": doc_id}, sort=[("date", DESCENDING)])
    if snap is None:
        return None
    return {
        "date": snap["date"],
        "content": snap["content"],
        "generated_at": snap["generated_at"].isoformat(),
        "is_today": snap["date"] == date.today().isoformat(),
    }


def save_snapshot(doc_id: str, content: str, snapshot_date: str = None) -> None:
    today = snapshot_date or date.today().isoformat()
    _snaps_col().update_one(
        {"doc_id": doc_id, "date": today},
        {"$set": {"content": content, "generated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )


def list_snapshot_history(doc_id: str, limit: int = 30) -> list[dict]:
    cursor = _snaps_col().find(
        {"doc_id": doc_id}, {"content": 0}
    ).sort("date", DESCENDING).limit(limit)
    return [{"date": s["date"], "generated_at": s["generated_at"].isoformat()} for s in cursor]
