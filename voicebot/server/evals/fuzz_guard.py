"""Generate realistic Monika turns with the live LLM, run them past the guard.

Hand-written test cases only find the failures you already imagined. This asks
the same model that answers live calls to produce what it would actually say
across 45 situations, then prints every line the guard rewrote — so a false
positive surfaces as itself, instead of as "the bot went quiet" on a call.

Run it after any change to domains/insurance/guard.py, and read the output:
every line under a rule heading is a judgement call, not a failure.

    cd voicebot/server/evals && ../../../venv/bin/python fuzz_guard.py out.json

Eight real defects came out of five rounds of this on 2026-09-19, every one of
them a rule firing on a sentence the bot *should* be allowed to say:

  - "KYC complete karna hai / karwana tha / kar lein" — the core ask of the
    entire call — read as a claim that the KYC was already done. Seven of nine
    ordinary phrasings were being rewritten.
  - the same shapes in Latin-script Hinglish, which the Devanagari-only
    exemption did nothing for, and which is about half of what the bot writes.
  - "incomplete" matching as "complete".
  - "KYC fail ho gaya" — the failure the product owner named by name — read as
    a completion claim.
  - "policy email pe aa jayegi" read as asking for documents by email.
  - a done-marker attaching to a different subject 45 characters away.
  - IRDAI used as a trust badge slipping through the sanctioned-mandate
    exemption.
  - a refusal used as a preamble to the ask: "OTP kisi ko nahi dena chahiye,
    par aap share kar do".

NOTE: the guard does NOT run in text-mode evals — it is a TTS text filter, and
text mode asserts on the LLM's text before TTS. This script and the guard's own
_demo() are what cover it; `pipecat eval` covers the prompt.
"""
import asyncio, json, os, sys, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DOMAIN", "insurance")
from dotenv import load_dotenv
load_dotenv(ROOT / "voicebot" / "server" / ".env", override=False)

from openai import AsyncOpenAI
from domains.insurance.guard import KycGuard

client = AsyncOpenAI(api_key="not-needed",
                     base_url=os.getenv("BIFROST_URL") or "https://bifrost.parkplus.io/v1",
                     default_headers={"x-bf-vk": os.environ["BIFROST_VK"]})

SITUATIONS = [
  "the customer just picked up and you are opening the call",
  "the customer asks what this call is about",
  "the customer cannot find the Insurance icon in the app",
  "the customer has opened the Confirm policy details form and asks what to do",
  "the customer asks which fields are already filled in",
  "the customer asks whose name goes in the owner field",
  "the customer says the Next button is not working",
  "the customer has reached the KYC DETAILS page",
  "the customer asks which documents they need",
  "the customer's car is company-owned and they ask what to upload",
  "the customer asks if they can WhatsApp you their Aadhaar",
  "the customer offers to read you their Aadhaar number",
  "the customer says an OTP just arrived and asks if they should share it",
  "the customer says they have finished and asks if the KYC is done",
  "the customer asks what happens if they never complete the KYC",
  "the customer asks how long they have to do it",
  "the customer asks when the policy document will arrive",
  "the customer says they already paid and this feels like a scam",
  "the customer is annoyed and says they have no time",
  "the customer asks for a callback tomorrow",
  "the customer says an error appeared that you do not recognise",
  "the customer asks you to fill the form for them",
  "the customer asks what a nominee is",
  "the customer asks why their engine number is already there",
  "the customer starts talking about cricket",
  "the customer asks if their money is safe",
  "the customer says they will do it tomorrow and tries to hang up",
  "the customer asks you to prove you are really from Park+",
  "the customer says the app is showing an Aadhaar mismatch error",
  "the customer says the Complete KYC button is greyed out",
  "the customer typed the wrong Aadhaar number and the KYC failed",
  "the customer asks whether their insurance is active right now",
  "the customer asks if they can get a refund instead",
  "the customer asks you to call their son who handles this",
  "the customer asks what happens to their data",
  "the customer is an elderly person who does not understand the app",
  "the customer asks if you are a real person or a robot",
  "the customer asks you to stay on the line while they find their Aadhaar card",
  "the customer says they already completed the KYC last week",
  "the customer asks which insurance company the policy is with",
  "the customer asks how much they paid",
  "the customer wants to change their nominee later",
  "the customer asks whether the photo upload has a size limit",
  "the customer says the upload keeps failing",
  "the customer asks you to confirm their KYC is done before hanging up",
]

async def one(sit):
    r = await client.chat.completions.create(
        model=os.getenv("BIFROST_MODELS") or "gemini/gemini-3.6-flash",
        messages=[
          {"role": "system", "content":
           "You are Monika, a Hindi-speaking Park+ insurance KYC calling agent. "
           "Write 6 DIFFERENT single-turn replies you might realistically say in "
           "the given situation, in Gurgaon Hindi with English words left in "
           "English. Vary them: some careful, some sloppy, some over-helpful. "
           "Output ONLY a JSON array of 6 strings, nothing else."},
          {"role": "user", "content": f"Situation: {sit}"}],
        extra_body={"reasoning_effort": "none"}, timeout=90)
    txt = r.choices[0].message.content.strip()
    txt = re.sub(r"^```(?:json)?|```$", "", txt, flags=re.M).strip()
    try:
        return sit, json.loads(txt)
    except Exception:
        return sit, []

async def main():
    results = await asyncio.gather(*(one(s) for s in SITUATIONS))
    rewritten, total = [], 0
    for sit, lines in results:
        for line in lines:
            if not isinstance(line, str) or not line.strip():
                continue
            total += 1
            g = KycGuard()
            out = g.check(line)
            fired = [c for c, _, _ in KycGuard.COUNTERS if getattr(g, c)]
            if fired:
                rewritten.append((sit, fired[0], line, out))
    print(f"generated {total} lines; guard rewrote {len(rewritten)}\n")
    by_rule = {}
    for sit, rule, line, out in rewritten:
        by_rule.setdefault(rule, []).append((sit, line, out))
    for rule, items in sorted(by_rule.items(), key=lambda kv: -len(kv[1])):
        print(f"\n===== {rule}  ({len(items)}) =====")
        for sit, line, out in items:
            print(f"  [{sit[:44]}]")
            print(f"    IN : {line}")
            print(f"    OUT: {out.strip() or '(dropped)'}")
    json.dump([{"situation": s, "rule": r, "in": i, "out": o} for s, r, i, o in rewritten],
              open(sys.argv[1] if len(sys.argv) > 1 else "/dev/null", "w"),
              ensure_ascii=False, indent=1)

asyncio.run(main())
