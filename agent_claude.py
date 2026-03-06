"""
DM03 Agent - Claude API Integration Example
=============================================
Shows how to wire up the AgentToolkit with Claude's function calling.

Requirements:
    pip install anthropic pyodbc pyyaml python-dotenv

Usage:
    python agent_claude.py "How many bins of Fancy Navels are in inventory?"
"""

import os
import sys
import json
from dotenv import load_dotenv
from anthropic import Anthropic
from agent_tools import AgentToolkit

# Load environment variables
load_dotenv()

# Initialize
client = Anthropic()  # Uses ANTHROPIC_API_KEY from .env
toolkit = AgentToolkit()

# Config from .env
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
MAX_TURNS = int(os.getenv("MAX_AGENT_TURNS", "10"))

# Load system prompt
with open("agent_system_prompt.md", "r") as f:
    SYSTEM_PROMPT = f.read()


def get_tools():
    """Get tool definitions in Claude's format."""
    tools = []
    for tool_def in toolkit.get_tool_definitions():
        tools.append({
            "name": tool_def["name"],
            "description": tool_def["description"],
            "input_schema": tool_def["parameters"]
        })
    return tools


def run_agent_turn(messages: list, max_turns: int = None, log_fn=None) -> str:
    """
    Run the agent for one user question, continuing the conversation in messages.
    Messages list is mutated in place to preserve history for follow-ups.
    log_fn: optional callable for tool call logging (defaults to print).
    """
    if log_fn is None:
        log_fn = print
    max_turns = max_turns or MAX_TURNS
    tools = get_tools()
    accumulated_text = []

    for turn in range(max_turns):
        # Call Claude with streaming (required for high max_tokens)
        with client.messages.stream(
            model=MODEL,
            max_tokens=30000,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages
        ) as stream:
            response = stream.get_final_message()

        # Collect any text from this response (may appear alongside tool calls)
        for block in response.content:
            if hasattr(block, "text") and block.text.strip():
                accumulated_text.append(block.text)

        # Add assistant response to conversation history
        messages.append({"role": "assistant", "content": response.content})

        # Check if we're done (no more tool calls)
        if response.stop_reason == "end_turn":
            return "\n".join(accumulated_text) if accumulated_text else "No response generated."

        # Process tool calls
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                log_fn(f"  [Tool Call] {block.name}: {json.dumps(block.input)[:100]}...")
                result = toolkit.handle_tool_call(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str)
                })

        # Add tool results to conversation history
        messages.append({"role": "user", "content": tool_results})

    # Return whatever text we accumulated even if max turns hit
    return "\n".join(accumulated_text) if accumulated_text else "Max turns reached without final response."


def run_agent(user_question: str, max_turns: int = None) -> str:
    """Run a single standalone question (no conversation history)."""
    messages = [{"role": "user", "content": user_question}]
    return run_agent_turn(messages, max_turns)


def interactive_mode():
    """Run in interactive chat mode with conversation history."""
    print("DM03 Data Warehouse Agent")
    print("=" * 50)
    print("Ask questions about inventory, receiving, sales, growers, etc.")
    print("Follow-up questions use prior responses as context.")
    print("Type 'new' to start a fresh conversation.")
    print("Type 'exit' to quit.\n")

    conversation = []

    while True:
        try:
            question = input("\nYou: ").strip()
            if question.lower() in ('exit', 'quit', 'q'):
                break
            if not question:
                continue
            if question.lower() == 'new':
                conversation = []
                print("\n--- New conversation started ---")
                continue

            # Add user question to ongoing conversation
            conversation.append({"role": "user", "content": question})

            print("\nAgent thinking...\n")
            response = run_agent_turn(conversation)
            print(f"\nAgent: {response}")

        except KeyboardInterrupt:
            break

    print("\nGoodbye!")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Single question mode
        question = " ".join(sys.argv[1:])
        print(f"Question: {question}\n")
        response = run_agent(question)
        print(f"\nAnswer:\n{response}")
    else:
        # Interactive mode
        interactive_mode()