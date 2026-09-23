"""Build domains/insurance/gold_replies.json from Gemini's clean replies.

Park+'s Qwen copies examples far better than it follows rules, and Gemini's
replies on real calls judge at ~99. So Gemini's answers become per-turn
examples for Park+ (guard.KycGuard.turn_hint with examples=True).

Sources: Gemini replays of OLDER real sessions (never the held-out newest 15)
and Gemini's scripted-suite runs. A reply the guard had to touch is dropped.
Card facts become placeholders, filled from the live call's card at use time.

    python -m evals.build_gold evals/gold_src_gemini.json evals/ab7_gemini_*.json ...
"""

import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[3] / "domains" / "insurance" / "gold_replies.json"
INSURERS = r"Bajaj\s*Allianz|ICICI\s*Lombard|HDFC\s*ERGO|HDFC\s*Ergo|Tata\s*AIG|United\s*India|Go\s*Digit|Kotak[\w\s]*?Insurance|National\s*Insurance|Bajaj|ICICI|HDFC"
REG = r"\b[A-Z]{2}\s?\d{1,2}\s?[A-Z]{1,3}\s?\d{3,4}\b"
NAMES = r"\b(?:Anush|Mangukiya|Bhavikbhai|Mahendrabhai|Gupta)\b(?:\s*(?:ji|जी))?"


def templatize(text: str) -> str:
    text = re.sub(INSURERS, "{insurer}", text, flags=re.I)
    text = re.sub(REG, "{reg}", text)
    # Only the CARD's policy type — "third party vs first party" knowledge stays.
    text = re.sub(r"(\{insurer\}\s*(?:ki|wali|वाली|की)?\s*)(third[\s-]*party|comprehensive)",
                  r"\1{ptype}", text, flags=re.I)
    text = re.sub(NAMES, "sir", text)
    return re.sub(r"\bsir,?\s+sir\b", "sir", text, flags=re.I)


def main(paths):
    bank, seen = [], set()
    for p in paths:
        res = json.load(open(p))
        res = res if isinstance(res, list) else res.get("results", res)
        for r in res:
            prev = ""
            for t in r["turns"]:
                reply = t["spoken"].strip()
                ok = (t["raw"].strip() == reply and not t["guard_fired"]
                      and not t.get("fails") and 8 < len(reply) < 260
                      and not re.search(r"[ऀ-ॿ]", reply))
                if ok:
                    key = (t["caller"], reply)
                    if key not in seen:
                        seen.add(key)
                        bank.append({"caller": t["caller"], "prev": templatize(prev)[:160],
                                     "reply": templatize(reply)})
                prev = reply
    OUT.write_text(json.dumps(bank, ensure_ascii=False, indent=1) + "\n")
    print(f"{len(bank)} gold pairs -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
