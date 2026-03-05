"""
CobbleAI Web Chat
=================
Simple Flask frontend for the DM03 data warehouse agent.

Usage:
    pip install flask markdown
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
from agent_claude import run_agent_turn

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# In-memory conversation store: {conversation_id: [messages]}
conversations = {}


@app.route("/")
def index():
    return render_template("chat.html")


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    conversation_id = data.get("conversation_id")

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    # Get or create conversation
    if not conversation_id or conversation_id not in conversations:
        conversation_id = str(uuid.uuid4())
        conversations[conversation_id] = []

    messages = conversations[conversation_id]
    messages.append({"role": "user", "content": user_message})

    # Run agent (log tool calls to Flask logger instead of stdout)
    try:
        response_text = run_agent_turn(messages, log_fn=app.logger.info)
    except Exception as e:
        app.logger.exception("Agent error")
        return jsonify({"error": str(e), "conversation_id": conversation_id}), 500

    return jsonify({
        "response": response_text,
        "conversation_id": conversation_id
    })


@app.route("/new", methods=["POST"])
def new_conversation():
    return jsonify({"conversation_id": str(uuid.uuid4())})


EXPORTS_DIR = os.path.join(os.path.dirname(__file__), "exports")


@app.route("/download/<filename>")
def download_file(filename):
    # Only allow .xlsx files and block path traversal
    if not filename.endswith(".xlsx") or "/" in filename or "\\" in filename:
        abort(404)
    return send_from_directory(
        EXPORTS_DIR, filename, as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


if __name__ == "__main__":
    print("Starting CobbleAI Web Chat on http://localhost:5000")
    app.run(debug=True, port=5000)
