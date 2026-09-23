"""Export Gemini's replies on real calls as a fine-tuning set for the Park+ model.

Prompting tops out around 94-95 for Park+'s Qwen3-30B-A3B on replayed real calls
(Gemini ~99). Distillation — training Park+ on Gemini's answers — is the one
lever left. Each line is one call in OpenAI chat format, built EXACTLY as the
bot sends it live: same system prompt + card, the spoken opening, and each
caller line with the same guard turn hint appended; assistant turns are
Gemini's replies after the guard. Never includes the held-out newest calls.

    python -m evals.export_sft evals/gold_src_gemini.json evals/gold_src2_gemini.json \
        --out ../../data/finetune/parkplus_sft.jsonl
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
os.environ.setdefault("DOMAIN", "insurance")
from domain import build_guard, build_opening_line, build_system_prompt  # noqa: E402
from domains.insurance.call_card import build as build_card  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sources", nargs="+")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    calls = turns = 0
    with open(args.out, "w") as f:
        for src in args.sources:
            for r in json.load(open(src)):
                card = build_card(r["card"]) if r.get("card") else None
                guard = build_guard(card)
                msgs = [{"role": "system", "content": build_system_prompt("outbound", card)}]
                opening = build_opening_line("outbound", card)
                if opening:
                    msgs.append({"role": "assistant", "content": opening})
                for t in r["turns"]:
                    guard.note_caller(t["caller"])
                    hint = guard.turn_hint()
                    msgs.append({"role": "user", "content": f"{t['caller']}\n\n({hint})" if hint else t["caller"]})
                    spoken = guard.check(t["spoken"]) or t["spoken"]
                    msgs.append({"role": "assistant", "content": spoken})
                    turns += 1
                f.write(json.dumps({"messages": msgs}, ensure_ascii=False) + "\n")
                calls += 1
    print(f"{calls} calls, {turns} assistant turns -> {args.out}")


if __name__ == "__main__":
    main()
