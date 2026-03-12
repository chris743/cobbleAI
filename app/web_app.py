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
import sys
import uuid
import logging
import threading
from datetime import date as _date
from pathlib import Path
from dotenv import load_dotenv

# Load .env from repo root
_root = Path(__file__).resolve().parent.parent
load_dotenv(_root / ".env")

# Add mcp/ to path so we can import living_docs, customer_specs, o365_auth
sys.path.insert(0, str(_root / "mcp"))

from flask import Flask, render_template, request, jsonify, abort, Response
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
NORMAN_WEBHOOK_SECRET = os.getenv("NORMAN_WEBHOOK_SECRET", "")


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


# ── Scheduled Reports ────────────────────────────────────────────────────────

import report_scheduler


@app.route("/scheduled-reports", methods=["GET"])
@require_auth
def list_scheduled_reports():
    result = report_scheduler.list_schedules(request.clerk_user_id)
    return jsonify(result)


@app.route("/scheduled-reports/<schedule_id>", methods=["GET"])
@require_auth
def get_scheduled_report(schedule_id):
    result = report_scheduler.get_schedule(request.clerk_user_id, schedule_id)
    if not result.get("success"):
        abort(404)
    return jsonify(result)


@app.route("/scheduled-reports/<schedule_id>", methods=["PUT"])
@require_auth
def update_scheduled_report(schedule_id):
    data = request.get_json()
    result = report_scheduler.update_schedule(request.clerk_user_id, schedule_id, **data)
    if not result.get("success"):
        return jsonify(result), 400
    return jsonify(result)


@app.route("/scheduled-reports/<schedule_id>", methods=["DELETE"])
@require_auth
def delete_scheduled_report(schedule_id):
    result = report_scheduler.delete_schedule(request.clerk_user_id, schedule_id)
    if not result.get("success"):
        abort(404)
    return jsonify(result)


# ── File downloads (proxied from MCP server) ─────────────────────────────────

import requests as _requests

_MCP_BASE = os.getenv("MCP_URL", "http://127.0.0.1:9000/sse").rsplit("/sse", 1)[0]


@app.route("/download/<filename>")
@require_auth
def download_file(filename):
    # Block path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        abort(404)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".xlsx", ".pdf"):
        abort(404)
    try:
        r = _requests.get(f"{_MCP_BASE}/download/{filename}", timeout=30)
        r.raise_for_status()
    except Exception:
        abort(404)
    return Response(
        r.content,
        headers={
            "Content-Type": r.headers.get("content-type", "application/octet-stream"),
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# ── Norman Incoming Email Webhook ─────────────────────────────────────────────

import norman_email as _norman_email
import hmac

NORMAN_ADDRESS = os.getenv("NORMAN_EMAIL", "norman@cobblestonefruit.com").lower()


def _should_norman_reply(from_addr: str, subject: str, body: str) -> bool:
    """Check reply rules: respond only to threads Norman started or emails addressed to him."""
    subject_lower = (subject or "").lower().strip()
    body_lower = (body or "").lower().strip()

    # Rule 1: Reply to threads Norman started (Re: to something Norman sent)
    if subject_lower.startswith("re:"):
        return True

    # Rule 2: Email explicitly addresses Norman
    if body_lower.startswith("norman,") or body_lower.startswith("norman "):
        return True
    if "norman," in body_lower[:200]:
        return True

    return False


def _handle_incoming_email(email_data: dict):
    """Process an incoming email to Norman in a background thread."""
    from_addr = email_data.get("from", "")
    subject = email_data.get("subject", "")
    body = email_data.get("body", "")
    email_id = email_data.get("email_id", "")

    app.logger.info(f"Norman webhook: from={from_addr}, subject={subject[:60]}")

    if not _should_norman_reply(from_addr, subject, body):
        app.logger.info(f"Norman skipping email (doesn't match reply rules): {subject}")
        return

    # Build a prompt for the agent with the email context
    prompt = (
        f"You received an email in your inbox (norman@cobblestonefruit.com). "
        f"Read it and reply appropriately using norman_reply_email.\n\n"
        f"From: {from_addr}\n"
        f"Subject: {subject}\n"
        f"Email ID: {email_id}\n\n"
        f"Body:\n{body[:3000]}"
    )

    messages = [{"role": "user", "content": prompt}]

    try:
        response = run_agent_turn(messages, log_fn=app.logger.info)
        app.logger.info(f"Norman auto-reply completed: {response[:200]}")
    except Exception as e:
        app.logger.exception(f"Norman auto-reply failed: {e}")


@app.route("/norman/webhook", methods=["POST"])
def norman_incoming_email():
    """Webhook for Power Automate — called when Norman receives an email."""
    # Verify webhook secret
    secret = request.headers.get("X-Webhook-Secret", "")
    if not NORMAN_WEBHOOK_SECRET:
        abort(403, "Webhook secret not configured")
    if not hmac.compare_digest(secret, NORMAN_WEBHOOK_SECRET):
        abort(403, "Invalid webhook secret")

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400

    # Run in background so we don't block the Power Automate flow
    thread = threading.Thread(
        target=_handle_incoming_email,
        args=(data,),
        daemon=True,
        name="norman-email-handler",
    )
    thread.start()

    return jsonify({"ok": True, "message": "Processing email"})


if __name__ == "__main__":
    print("Starting CobbleAI API on http://localhost:8000")
    app.run(host='0.0.0.0', debug=True, port=8000)
