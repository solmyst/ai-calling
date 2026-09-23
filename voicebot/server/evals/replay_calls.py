"""Every live call in call.log becomes a test: replay the caller's real lines.

The scripted scenarios in ab_models only cover what we thought of. This takes
each real session from call.log (Mac or VM), keeps the caller lines the bot
actually answered (NoiseGate drops removed), and replays them through the
CURRENT prompt + guard + hints on a model, then has the judge grade the call.

    python -m evals.replay_calls ../../data/logs/*.log --model parkplus --out evals/replay_parkplus.json
    python -m evals.judge_replies evals/replay_parkplus.json

Sessions need >= 3 caller turns. The card is rebuilt from the insurer the log
recorded; unknown fields stay out, as they would on a real call without them.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evals.ab_models import SCENARIOS, _endpoints, run_scenario  # noqa: E402

# Cards the test proposals used, so a replay sees what the live call saw.
KNOWN_CARDS = {
    "Bajaj Allianz": {"insurer": "Bajaj Allianz", "policy_type": "THIRD_PARTY",
                      "vehicle_reg": "AP09CU0999", "ownership_type": "individual"},
    "ICICI Lombard": {"insurer": "ICICI Lombard", "policy_type": "COMPREHENSIVE",
                      "ownership_type": "individual"},
}


def sessions(paths):
    out = []
    for path in paths:
        cur = None
        for line in open(path, encoding="utf-8", errors="ignore"):
            if "| Starting bot" in line:
                cur = {"src": Path(path).name, "at": line[:8], "insurer": None, "callers": []}
                out.append(cur)
            if cur is None:
                continue
            m = re.search(r"CALL CARD .*insurer=([^=]+?) kyc=", line)
            if m and m.group(1) != "?":
                cur["insurer"] = m.group(1).strip()
            m = re.search(r"\| CALLER \| (.*)", line)
            if m:
                cur["callers"].append(m.group(1).strip())
            m = re.search(r"\| NOISE  \| dropped '(.*)'", line)
            if m and cur["callers"] and cur["callers"][-1] == m.group(1):
                cur["callers"].pop()
    return [s for s in out if len(s["callers"]) >= 3]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--model", choices=["parkplus", "gemini"], required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip-last", type=int, default=0,
                    help="leave out the newest N sessions (kept as the held-out test set)")
    args = ap.parse_args()
    ep = next(e for e in _endpoints() if e[0] == args.model)
    found = sessions(args.logs)
    if args.skip_last:
        found = found[:-args.skip_last]
    if args.limit:
        found = found[-args.limit:]
    results = []
    for i, s in enumerate(found):
        name = f"live_{s['src'].split('_')[0]}_{s['at'].replace(':', '')}_{i}"
        card_src = KNOWN_CARDS.get(s["insurer"] or "")
        card = {"goal": "complete_kyc", "do_not_say": [], **card_src} if card_src else None
        # judge_replies looks the scenario up to rebuild the same system prompt.
        SCENARIOS[name] = {"card": card, "turns": []} if card else []
        r = run_scenario(*ep, name, [{"caller": c} for c in s["callers"]], card=card)
        r["card"] = card
        results.append(r)
        print(f"{name}: {len(r['turns'])} turns {'ERR ' + str(r['errors']) if r['errors'] else ''}")
    json.dump(results, open(args.out, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
