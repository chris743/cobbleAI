"""MongoDB connection helper for the MCP server."""

import os
from pymongo import MongoClient

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
