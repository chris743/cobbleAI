"""
CobbleAI Web Chat
=================
Flask frontend for the DM03 data warehouse agent.
Conversations are persisted in MongoDB. Auth via Clerk.

Usage:
    pip install -r requirements.txt
    python web_app.py
    Open http://localhost:5000
"""

import os
import uuid
import logging
from datetime import date as _date
from dotenv import load_dotenv

# Load .env before importing agent (which initializes the Anthropic client at import time)
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from flask import Flask, render_template, request, jsonify, send_from_directory, abort, Response
from flask_cors import CORS
from agent_claude import run_agent_turn, run_agent_turn_streaming
from auth import require_auth
import chat_store
import living_docs as ld
import customer_specs as cs
import o365_auth

app = Flask(__name__)
app.logger.setLevel(logging.INFO)
CORS(app, origins=["http://localhost:5000"], supports_credentials=True)

CLERK_PUBLISHABLE_KEY = os.getenv("CLERK_PUBLISHABLE_KEY", "")


@app.route("/")
def index():
    return render_template("chat.html", clerk_publishable_key=CLERK_PUBLISHABLE_KEY)


@app.route("/chat", methods=["POST"])
@require_auth
def chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    conversation_id = data.get("conversation_id")
    user_id = request.clerk_user_id

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    # Get or create conversation (scoped to user)
    convo = None
    if conversation_id:
        convo = chat_store.get_conversation(conversation_id)
        # Ensure conversation belongs to this user
        if convo and convo.get("user_id") != user_id:
            convo = None

    if not convo:
        conversation_id = str(uuid.uuid4())
        chat_store.create_conversation(conversation_id, user_message[:60], user_id=user_id, username=request.clerk_username)
        convo = chat_store.get_conversation(conversation_id)

    # Rebuild messages list from stored state
    messages = convo["messages"]
    messages.append({"role": "user", "content": user_message})

    # Run agent (mutates messages in place with assistant + tool_result entries)
    try:
        response_text = run_agent_turn(messages, log_fn=app.logger.info, user_id=user_id)
    except Exception as e:
        app.logger.exception("Agent error")
        chat_store.update_messages(conversation_id, messages)
        return jsonify({"error": str(e), "conversation_id": conversation_id}), 500

    # Persist updated conversation
    chat_store.update_messages(conversation_id, messages)

    return jsonify({
        "response": response_text,
        "conversation_id": conversation_id
    })


@app.route("/chat/stream", methods=["POST"])
@require_auth
def chat_stream():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    conversation_id = data.get("conversation_id")
    user_id = request.clerk_user_id

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    # Get or create conversation (scoped to user)
    convo = None
    if conversation_id:
        convo = chat_store.get_conversation(conversation_id)
        if convo and convo.get("user_id") != user_id:
            convo = None

    if not convo:
        conversation_id = str(uuid.uuid4())
        chat_store.create_conversation(conversation_id, user_message[:60], user_id=user_id, username=request.clerk_username)
        convo = chat_store.get_conversation(conversation_id)

    messages = convo["messages"]
    messages.append({"role": "user", "content": user_message})

    # Capture user_id before entering generator (request context won't be available inside)
    current_user_id = user_id

    def generate():
        import json as _json
        # Send conversation_id first
        yield f"data: {_json.dumps({'type': 'meta', 'conversation_id': conversation_id})}\n\n"

        try:
            for event_type, payload in run_agent_turn_streaming(messages, log_fn=app.logger.info, user_id=current_user_id):
                if event_type == "token":
                    yield f"data: {_json.dumps({'type': 'token', 'text': payload})}\n\n"
                elif event_type == "tool":
                    yield f"data: {_json.dumps({'type': 'tool', 'name': payload})}\n\n"
        except Exception as e:
            app.logger.exception("Agent streaming error")
            yield f"data: {_json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        # Persist conversation after streaming completes
        chat_store.update_messages(conversation_id, messages)
        yield f"data: {_json.dumps({'type': 'done'})}\n\n"

    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
    })


@app.route("/new", methods=["POST"])
@require_auth
def new_conversation():
    return jsonify({"conversation_id": str(uuid.uuid4())})


@app.route("/conversations")
@require_auth
def list_conversations():
    return jsonify(chat_store.list_conversations(user_id=request.clerk_user_id))


@app.route("/conversations/<conversation_id>")
@require_auth
def get_conversation(conversation_id):
    result = chat_store.get_display_messages(conversation_id)
    if not result or result.get("user_id") != request.clerk_user_id:
        abort(404)
    return jsonify(result)



# ── Living Documents ──────────────────────────────────────────────────────────

@app.route("/living-docs", methods=["GET"])
@require_auth
def list_living_docs():
    return jsonify(ld.list_docs())


@app.route("/living-docs", methods=["POST"])
@require_auth
def create_living_doc():
    data = request.get_json()
    name = data.get("name", "").strip()
    prompt = data.get("prompt", "").strip()
    description = data.get("description", "").strip()
    if not name or not prompt:
        return jsonify({"error": "name and prompt are required"}), 400
    doc = ld.create_doc(name, description, prompt,
                        request.clerk_user_id, request.clerk_username)
    return jsonify(doc), 201


@app.route("/living-docs/<doc_id>", methods=["GET"])
@require_auth
def get_living_doc(doc_id):
    """Return the document definition and its latest snapshot (may be None)."""
    doc = ld.get_doc(doc_id)
    if not doc:
        abort(404)
    snapshot = ld.get_latest_snapshot(doc["id"])
    return jsonify({
        "id": doc["id"],
        "name": doc["name"],
        "description": doc.get("description", ""),
        "prompt": doc["prompt"],
        "snapshot": snapshot,
    })


@app.route("/living-docs/<doc_id>", methods=["PUT"])
@require_auth
def update_living_doc(doc_id):
    """Update a living document's name, description, or prompt."""
    data = request.get_json()
    updated = ld.update_doc(doc_id,
                            name=data.get("name"),
                            description=data.get("description"),
                            prompt=data.get("prompt"))
    if not updated:
        abort(404)
    return jsonify(updated)


@app.route("/living-docs/<doc_id>", methods=["DELETE"])
@require_auth
def delete_living_doc(doc_id):
    """Soft-delete a living document."""
    if not ld.delete_doc(doc_id):
        abort(404)
    return jsonify({"ok": True})


@app.route("/living-docs/<doc_id>/refresh", methods=["POST"])
@require_auth
def refresh_living_doc(doc_id):
    """Stream-generate today's snapshot using the document's prompt."""
    doc = ld.get_doc(doc_id)
    if not doc:
        abort(404)

    def generate():
        import json as _json
        messages = [{"role": "user", "content": doc["prompt"]}]
        full_text = []

        try:
            for event_type, payload in run_agent_turn_streaming(messages, log_fn=app.logger.info):
                if event_type == "token":
                    full_text.append(payload)
                    yield f"data: {_json.dumps({'type': 'token', 'text': payload})}\n\n"
                elif event_type == "tool":
                    yield f"data: {_json.dumps({'type': 'tool', 'name': payload})}\n\n"
        except Exception as e:
            app.logger.exception("Living doc refresh error")
            yield f"data: {_json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        content = "".join(full_text)
        if content:
            ld.save_snapshot(doc["id"], content)

        today = _date.today().isoformat()
        yield f"data: {_json.dumps({'type': 'done', 'date': today})}\n\n"

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.route("/living-docs/<doc_id>/history", methods=["GET"])
@require_auth
def living_doc_history(doc_id):
    doc = ld.get_doc(doc_id)
    if not doc:
        abort(404)
    return jsonify(ld.list_snapshot_history(doc["id"]))


# ── Customer Specs ────────────────────────────────────────────────────────────

@app.route("/customer-specs", methods=["GET"])
@require_auth
def list_customer_specs():
    return jsonify(cs.get_specs())


@app.route("/customer-specs/<spec_id>", methods=["DELETE"])
@require_auth
def delete_customer_spec(spec_id):
    if not cs.delete_spec(spec_id):
        abort(404)
    return jsonify({"ok": True})


# ── Microsoft 365 ─────────────────────────────────────────────────────────────

O365_REDIRECT_URI = os.getenv("O365_REDIRECT_URI", "http://localhost:5000/o365/callback")


@app.route("/o365/status")
@require_auth
def o365_status():
    if not o365_auth.is_configured():
        return jsonify({"configured": False, "connected": False})
    connected = o365_auth.is_connected(request.clerk_user_id)
    return jsonify({"configured": True, "connected": connected})


@app.route("/o365/auth-url")
@require_auth
def o365_auth_url():
    if not o365_auth.is_configured():
        return jsonify({"error": "Microsoft 365 integration is not configured on the server"}), 400
    url, state = o365_auth.get_auth_url(request.clerk_user_id, O365_REDIRECT_URI)
    return jsonify({"url": url})


@app.route("/o365/callback")
def o365_callback():
    """OAuth callback from Microsoft. Runs in popup, closes itself on completion."""
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error:
        return _o365_callback_html(False, request.args.get("error_description", error))

    if not code or not state:
        return _o365_callback_html(False, "Missing authorization code")

    # Reconstruct callback URL using configured redirect URI (request.url may show
    # the wrong host/port when behind Vite proxy)
    callback_url = O365_REDIRECT_URI + "?" + request.query_string.decode("utf-8")

    app.logger.info(f"O365 callback — state={state[:20]}... code={'yes' if code else 'no'}")

    success, err = o365_auth.complete_auth(
        callback_url=callback_url,
        redirect_uri=O365_REDIRECT_URI,
        state=state,
    )

    app.logger.info(f"O365 auth result: success={success}, err={err}")
    return _o365_callback_html(success, err)


def _o365_callback_html(success: bool, error: str = None):
    """Return HTML that notifies the opener window and closes the popup."""
    status = "connected" if success else "error"
    msg = error or ""
    return f"""<!DOCTYPE html>
<html><head><title>Microsoft 365</title></head>
<body>
<p>{"Connected successfully!" if success else f"Connection failed: {msg}"}</p>
<p>You can close this window.</p>
<script>
  if (window.opener) {{
    window.opener.postMessage({{ type: 'o365-auth', status: '{status}', error: '{msg}' }}, '*');
  }}
  setTimeout(function() {{ window.close(); }}, 1500);
</script>
</body></html>"""


@app.route("/o365/disconnect", methods=["POST"])
@require_auth
def o365_disconnect():
    o365_auth.disconnect(request.clerk_user_id)
    return jsonify({"ok": True})


# ── File downloads ────────────────────────────────────────────────────────────

EXPORTS_DIR = os.path.join(os.path.dirname(__file__), "exports")


_DOWNLOAD_MIMETYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pdf": "application/pdf",
}


@app.route("/download/<filename>")
@require_auth
def download_file(filename):
    # Block path traversal
    if "/" in filename or "\\" in filename:
        abort(404)
    ext = os.path.splitext(filename)[1].lower()
    mimetype = _DOWNLOAD_MIMETYPES.get(ext)
    if not mimetype:
        abort(404)
    return send_from_directory(EXPORTS_DIR, filename, as_attachment=True, mimetype=mimetype)


if __name__ == "__main__":
    print("Starting CobbleAI API on http://localhost:8000")
    app.run(host='0.0.0.0', debug=True, port=8000)
