"""Slack for the voice bot: breakage alerts, team handovers, one summary per call.

Posts through a Slack incoming webhook (SLACK_WEBHOOK_URL — Slack app ->
Incoming Webhooks -> pick the channel). Unset, every function here is a no-op,
so a dev box without the URL behaves exactly as before.
"""

import json
import os
import re
import sys
import threading
import time
import urllib.request

# Slack truncates long messages anyway; a whole six-minute call fits in this.
_MAX_CHARS = 3500
# The same failure repeats every second while a service is down (Sarvam's rate
# limit logged 10 ERROR lines in 2s on 2026-09-22). One alert per kind per window.
_REPEAT_SECS = 300
_last_sent: dict[str, float] = {}


def enabled() -> bool:
    return bool(os.getenv("SLACK_WEBHOOK_URL"))


def post(text: str) -> None:
    """Fire and forget, on a thread: a slow Slack must never stall a call."""
    url = os.getenv("SLACK_WEBHOOK_URL")
    if not url:
        return
    body = json.dumps({"text": text[:_MAX_CHARS]}).encode()

    def _send() -> None:
        try:
            req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5).close()
        except Exception as e:  # noqa: BLE001 — alerting must not raise into the call
            # stderr, not the logger: a logged failure would re-enter the alert sink.
            print(f"slack post failed: {e}", file=sys.stderr)

    threading.Thread(target=_send, daemon=True).start()


def _alert_key(message: str) -> str:
    # Ids, counts and timestamps differ between repeats of the same failure.
    return re.sub(r"[0-9a-f]{8,}|\d+", "#", message)[:120]


def should_alert(message: str, now: float | None = None) -> bool:
    """True for a breakage line not already alerted in the last _REPEAT_SECS."""
    # GUARDRAIL lines log at ERROR but are the guard WORKING, not breakage.
    if message.startswith("GUARDRAIL"):
        return False
    now = time.monotonic() if now is None else now
    key = _alert_key(message)
    if now - _last_sent.get(key, float("-inf")) < _REPEAT_SECS:
        return False
    _last_sent[key] = now
    return True


def alert_filter(record) -> bool:
    """Loguru filter: errors, plus the warning that says a call was dropped."""
    return record["level"].no >= 40 or record["message"].startswith(
        "Hanging up: processor_unusable"
    )


def alert_sink(message) -> None:
    """Loguru sink: one Slack alert per new kind of failure."""
    record = message.record
    if should_alert(record["message"]):
        post(f":rotating_light: *Voice bot {record['level'].name}* "
             f"{record['time']:%H:%M:%S} — {record['message']}")


if __name__ == "__main__":
    assert not should_alert("GUARDRAIL rewrote a line", now=0)
    assert should_alert("TTS Error: Rate limit exceeded ErrorFrame#1", now=0)
    assert not should_alert("TTS Error: Rate limit exceeded ErrorFrame#7", now=10)
    assert should_alert("TTS Error: Rate limit exceeded ErrorFrame#9", now=_REPEAT_SECS + 1)
    assert should_alert("a different failure", now=10)
    print("slack ok")
