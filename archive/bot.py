#!/usr/bin/env python3
"""Stage 1 text chat bot for Park+ Car Spa. Ollama + context.json, terminal loop."""
import json
import datetime
import urllib.request
from pathlib import Path

from domain import build_system_prompt  # moved: see domain.py

MODEL = "qwen3:8b"
OLLAMA_URL = "http://localhost:11434/api/chat"
LOG_FILE = Path(__file__).parent / "conversation_log.jsonl"


def call_ollama(messages: list[dict]) -> str:
    payload = json.dumps({"model": MODEL, "messages": messages, "stream": False}).encode()
    req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["message"]["content"]


def log_turn(role: str, content: str) -> None:
    with LOG_FILE.open("a") as f:
        f.write(json.dumps({"ts": datetime.datetime.now().isoformat(), "role": role, "content": content}) + "\n")


def main() -> None:
    messages = [{"role": "system", "content": build_system_prompt()}]
    print("Park+ Car Spa bot (type 'quit' to exit)\n")
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in {"quit", "exit"}:
            break
        messages.append({"role": "user", "content": user_input})
        log_turn("user", user_input)
        reply = call_ollama(messages)
        messages.append({"role": "assistant", "content": reply})
        log_turn("assistant", reply)
        print(f"\nBot: {reply}\n")


if __name__ == "__main__":
    main()
