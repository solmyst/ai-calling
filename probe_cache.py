"""Does the gateway actually charge us once for a prompt we send every turn?

75% of everything this bot spent on 2026-09-19 was one byte-identical prefix:
the 3,556-token system prompt, re-sent on all 2,043 turns. If the provider
caches that prefix the bill collapses; if it does not, the prompt's size is the
bill and shortening it is the only lever.

That is a question with a measurable answer, and guessing it wrong in either
direction is expensive — so measure, the same way `costs.py` measured Groq's
prefix caching and found it did NOT apply on the free tier despite being
documented.

    python probe_cache.py                 # the bot's live LLM chain
    python probe_cache.py --provider parkplus

Reads voicebot/server/.env. Sends the REAL system prompt several times in a row
with a one-token completion, so the only meaningful cost is the prefix, and
prints whatever the provider says about caching.
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DOMAIN", "insurance")

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / "voicebot" / "server" / ".env", override=False)
except ImportError:
    pass

from openai import OpenAI  # noqa: E402

PROVIDERS = {
    "bifrost": dict(
        url=lambda: os.getenv("BIFROST_URL") or "https://bifrost.parkplus.io/v1",
        key=lambda: "not-needed",
        model=lambda: (os.getenv("BIFROST_MODELS") or "gemini/gemini-3.6-flash").split(",")[0],
        headers=lambda: {"x-bf-vk": os.getenv("BIFROST_EVAL_VK") or os.getenv("BIFROST_VK") or ""},
    ),
    "parkplus": dict(
        url=lambda: os.getenv("PARKPLUS_LLM_URL"),
        key=lambda: os.getenv("PARKPLUS_LLM_API_KEY") or "not-needed",
        model=lambda: os.getenv("PARKPLUS_LLM_MODEL") or "ulkaa/Ornith-1.5-35B-A3B-AWQ-INT4",
        headers=lambda: None,
    ),
}


def _cached_tokens(usage) -> int | None:
    """However this provider spells it, or None if it says nothing at all.

    OpenAI puts it at usage.prompt_tokens_details.cached_tokens; Anthropic-style
    gateways use cache_read_input_tokens. A provider that reports nothing is not
    the same as one reporting zero — the first is silence, the second is a
    measured miss — so this keeps them distinct.
    """
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        cached = getattr(details, "cached_tokens", None)
        if cached is None and isinstance(details, dict):
            cached = details.get("cached_tokens")
        if cached is not None:
            return int(cached)
    for alt in ("cache_read_input_tokens", "cached_tokens"):
        value = getattr(usage, alt, None)
        if value is not None:
            return int(value)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=sorted(PROVIDERS), default="bifrost")
    ap.add_argument("--calls", type=int, default=4)
    args = ap.parse_args()

    from domain import build_system_prompt

    system = build_system_prompt("outbound")
    spec = PROVIDERS[args.provider]
    base_url, model = spec["url"](), spec["model"]()
    if not base_url:
        print(f"{args.provider}: no base URL configured in .env")
        return 2

    client = OpenAI(api_key=spec["key"](), base_url=base_url,
                    default_headers=spec["headers"]())
    print(f"provider     : {args.provider}  ({base_url})")
    print(f"model        : {model}")
    print(f"system prompt: {len(system)} chars")
    if args.provider == "bifrost":
        print("virtual key  : "
              + ("BIFROST_EVAL_VK" if os.getenv("BIFROST_EVAL_VK") else "BIFROST_VK"))
    print()

    rows = []
    for i in range(args.calls):
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": "ok"}],
                max_completion_tokens=1, timeout=90,
            )
        except Exception as e:
            text = str(e)
            print(f"call {i + 1}: FAILED — {type(e).__name__}")
            if "budget_exceeded" in text or "402" in text:
                print("\n  The virtual key is out of budget, so nothing can be measured.")
                print("  Top it up (or point BIFROST_EVAL_VK at a funded key) and re-run.")
            else:
                print(f"  {text[:300]}")
            return 1
        usage = r.usage
        cached = _cached_tokens(usage)
        rows.append((usage.prompt_tokens, cached))
        shown = "not reported" if cached is None else f"{cached}"
        print(f"call {i + 1}: prompt_tokens={usage.prompt_tokens:<6} cached={shown}")
        if i == 0:
            print(f"        raw usage: {json.dumps(usage.model_dump(), default=str)[:300]}")

    print()
    prompt_tokens = rows[0][0]
    later = [c for _, c in rows[1:]]
    if all(c is None for c in later):
        print("VERDICT: the provider reports no caching field at all.")
        print("  Same result costs.py measured on Groq's free tier. Treat the full")
        print(f"  {prompt_tokens}-token prompt as billed on every turn, and remember")
        print("  that shortening it is then the only lever on input cost.")
    elif all((c or 0) == 0 for c in later):
        print("VERDICT: caching is reported but NOT hitting — 0 cached tokens on a")
        print("  byte-identical prefix. Check whether the gateway forwards Gemini's")
        print("  cache controls; until it does, the prompt is billed in full every turn.")
    else:
        best = max(c or 0 for c in later)
        print(f"VERDICT: caching WORKS — up to {best} of {prompt_tokens} prompt tokens "
              f"({best / prompt_tokens:.0%}) served from cache.")
        print("  Re-run costs.py's per-call figures with that discount applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
