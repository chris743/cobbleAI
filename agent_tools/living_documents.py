"""Living document agent tool helpers."""

import living_docs as _living_docs


def _agent_update_living_doc(name: str, new_name: str = None,
                             new_description: str = None, new_prompt: str = None) -> dict:
    doc = _living_docs.get_doc_by_name(name)
    if not doc:
        available = [d["name"] for d in _living_docs.list_docs()]
        return {"error": f"No living document named '{name}'.", "available": available}
    updated = _living_docs.update_doc(doc["id"], name=new_name,
                                      description=new_description, prompt=new_prompt)
    if not updated:
        return {"error": "No fields to update."}
    return {"success": True, "document": updated}


def _agent_delete_living_doc(name: str) -> dict:
    doc = _living_docs.get_doc_by_name(name)
    if not doc:
        available = [d["name"] for d in _living_docs.list_docs()]
        return {"error": f"No living document named '{name}'.", "available": available}
    _living_docs.delete_doc(doc["id"])
    return {"success": True, "deleted": name}


def _agent_get_living_doc(name: str) -> dict:
    doc = _living_docs.get_doc_by_name(name)
    if not doc:
        available = [d["name"] for d in _living_docs.list_docs()]
        return {
            "error": f"No living document named '{name}'.",
            "available_documents": available,
        }
    snap = _living_docs.get_latest_snapshot(doc["id"])
    if not snap:
        return {
            "name": doc["name"],
            "description": doc.get("description"),
            "snapshot": None,
            "message": "No snapshot generated yet. Ask the user to click Refresh in the sidebar.",
        }
    return {
        "name": doc["name"],
        "description": doc.get("description"),
        "snapshot": snap,
    }


TOOL_DEFINITIONS = [
    {
        "name": "list_living_documents",
        "description": "List all defined living documents (shared daily reports consistent across all users). Use this to show the user what documents exist or to check before creating a duplicate.",
        "parameters": {"type": "object", "properties": {}}
    },
    {
        "name": "get_living_document",
        "description": "Retrieve today's snapshot of a living document by name. Living documents are shared across all users and refreshed daily. Use this when a user asks to see a living document or wants to discuss its contents.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Exact name of the living document (use list_living_documents if unsure)"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "create_living_document",
        "description": "Register a new living document definition. Called when the user types /living-doc-add. The prompt must be a complete, self-contained instruction that will be run daily to generate the document (e.g., 'Generate a daily production summary showing all packing lines...'). Confirm the name and prompt with the user before calling this.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short display name (e.g., 'Daily Production Plan', 'Morning Pick Plan')"},
                "description": {"type": "string", "description": "One-sentence description of what this document shows"},
                "prompt": {"type": "string", "description": "The full prompt to run to generate this document. Must be detailed and self-contained."}
            },
            "required": ["name", "prompt"]
        }
    },
    {
        "name": "update_living_document",
        "description": "Update an existing living document's name, description, or prompt. Use when the user wants to change what a living document generates or rename it. Look up the document by name first using get_living_document or list_living_documents to get the ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Current name of the living document to update"},
                "new_name": {"type": "string", "description": "New display name (omit to keep current)"},
                "new_description": {"type": "string", "description": "New description (omit to keep current)"},
                "new_prompt": {"type": "string", "description": "New prompt to generate the document (omit to keep current)"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "delete_living_document",
        "description": "Delete a living document by name. Confirm with the user before calling this. The document and its snapshots will no longer be visible.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the living document to delete"}
            },
            "required": ["name"]
        }
    },
]


def register_handlers() -> dict:
    return {
        "list_living_documents": lambda p: _living_docs.list_docs(),
        "get_living_document": lambda p: _agent_get_living_doc(p.get("name", "")),
        "create_living_document": lambda p: _living_docs.create_doc(
            p.get("name", ""), p.get("description", ""), p.get("prompt", ""),
            created_by="agent",
        ),
        "update_living_document": lambda p: _agent_update_living_doc(
            p.get("name", ""), p.get("new_name"), p.get("new_description"), p.get("new_prompt"),
        ),
        "delete_living_document": lambda p: _agent_delete_living_doc(p.get("name", "")),
    }
