"""
Customer Specs — persistent customer-specific rules and preferences.

Stores size, grade, packaging, and other customer/DC-specific rules in MongoDB.
The agent saves specs when users mention customer requirements, and reads them
during production scheduling and size substitution analysis.
"""

from datetime import datetime, timezone
from bson import ObjectId
from chat_store import _get_db


def _col():
    return _get_db()["customer_specs"]


def save_spec(customer: str, spec_type: str, rule: str, dc: str = None) -> dict:
    now = datetime.now(timezone.utc)
    doc = {
        "customer": customer,
        "dc": dc,
        "spec_type": spec_type,
        "rule": rule,
        "created_at": now,
    }
    result = _col().insert_one(doc)
    return {
        "id": str(result.inserted_id),
        "customer": customer,
        "dc": dc,
        "spec_type": spec_type,
        "rule": rule,
    }


def get_specs(customer: str = None) -> list[dict]:
    query = {}
    if customer:
        query["customer"] = {"$regex": customer, "$options": "i"}
    cursor = _col().find(query).sort("customer", 1)
    results = []
    for doc in cursor:
        results.append({
            "id": str(doc["_id"]),
            "customer": doc["customer"],
            "dc": doc.get("dc"),
            "spec_type": doc.get("spec_type", "general"),
            "rule": doc["rule"],
            "created_at": doc.get("created_at", "").isoformat() if hasattr(doc.get("created_at", ""), "isoformat") else "",
        })
    return results


def delete_spec(spec_id: str) -> bool:
    try:
        oid = ObjectId(spec_id)
    except Exception:
        return False
    result = _col().delete_one({"_id": oid})
    return result.deleted_count > 0
