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
from dotenv import load_dotenv

# Load .env before importing agent (which initializes the Anthropic client at import time)
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from flask import Flask, render_template, request, jsonify, send_from_directory, abort
from flask_cors import CORS
from agent_claude import run_agent_turn
from auth import require_auth
import chat_store

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
        response_text = run_agent_turn(messages, log_fn=app.logger.info)
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


EXPORTS_DIR = os.path.join(os.path.dirname(__file__), "exports")


@app.route("/download/<filename>")
@require_auth
def download_file(filename):
    # Only allow .xlsx files and block path traversal
    if not filename.endswith(".xlsx") or "/" in filename or "\\" in filename:
        abort(404)
    return send_from_directory(
        EXPORTS_DIR, filename, as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


if __name__ == "__main__":
    print("Starting CobbleAI API on http://localhost:8000")
    app.run(host='0.0.0.0', debug=True, port=8000)
