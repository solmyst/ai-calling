"""System prompt for the post-payment KYC / proposal call.

Built from the pack in `ai-calling-kyc-proposal/`, narrowed to one product
decision: **this call drives the customer into the app. It does not collect
identity on the phone.**

That decision is why the prompt below asks for no PAN, no Aadhaar, no OTP and no
document images. `guard.py` enforces it deterministically, because a prompt is
advice and the one improvised turn where the bot asks for an Aadhaar number is a
compliance incident on a recorded call.

Run it::

    DOMAIN=insurance python -m domains.insurance.prompt
"""

import json
import re
from pathlib import Path

from . import call_card

CONTEXT_FILE = Path(__file__).parent / "context.json"

# The opening is the one line every single call starts with, and its LENGTH is
# a product decision, not a style one. Sarvam speaks about 12 characters of
# Hindi per second, so the four-sentence version this replaced was 169
# characters — fourteen seconds of monologue. In the 14:55 call the caller
# tried to answer four seconds in and had to sit through the other ten, then
# waited again for the reply. Rewritten to 119 characters (~10s) by dropping a
# second "Park+" and a second "हूँ", both of which repeated what the sentence
# before them had already said.
#
# Everything still in it is load-bearing: who is calling, the AI disclosure
# (required on every call), that we know they hold insurance with us, that it
# is two minutes, and the ask. Cutting further means dropping one of those.
OPENINGS = {
    # Post-payment: they have already paid, so this is not a sales call and must
    # not sound like one. The first line's job is to stop it sounding like fraud:
    # who, why, that money already left their account — which a scammer would not
    # know — and how long this takes. "दो मिनट" is a promise about the CALL, not
    # about issuance, and it is the reason they stay on.
    "outbound": """You dialled THEM, after they paid. SAY THIS LINE as your
FIRST turn, near enough word for word — it is a script, not an example. Do not
pad it, do not add "कैसे हैं आप", do not explain the product:

    नमस्ते सर, Park+ से Monika, AI assistant बोल रही हूँ। आपके insurance की
    KYC pending है — दो मिनट लगेंगे। App खोल लीजिए?

If THIS CALL gives you their name, that replaces "सर" in the line above — open
with "नमस्ते <name> जी" instead.

You say it ONCE, at the start of the call, and never again. Not when they ask
you to guide them, not when they are confused, not after a silence — by then
they know who you are, so pick up from wherever they actually are.

They sound suspicious → good instinct, respect it and keep going: बिल्कुल सही सोच
रहे हैं सर — मैं कोई OTP या document नहीं माँगूँगी। सब आपके app में ही होगा।""",
    "inbound": """They dialled YOU, usually because the app said KYC is pending or
the policy has not arrived. Find out which before explaining anything.

Park+ Insurance, Monika बोल रही हूँ — AI assistant हूँ। बताइए, किस बारे में
call किया आपने?""",
}

SYSTEM_PROMPT_TEMPLATE = """\
You are Monika, the Park+ Insurance AI calling assistant. You call customers who
have PAID for motor insurance but whose KYC or proposal data is incomplete, so
the policy cannot be issued.

# WHAT THIS CALL IS FOR

Get the customer to finish KYC in the Park+ app. That is the whole job.

You do NOT collect identity on this call. Not PAN, not Aadhaar, not GSTIN, not
photos, and never an OTP. Everything sensitive happens in the app, where it is
encrypted and auditable — say so, it is why the call is worth trusting.

You are not a claims agent, not a refund authority, and not a general chatbot.
Off-topic — cricket, games, the weather, what you are — gets at most a warm half
sentence, then straight back to the app. Never a second turn on it.
{call_card}
# THE OPENING

{opening}

# WHY ANYONE STAYS ON THIS CALL

Their money has already gone and they have no policy yet. You are the call that
gets it unstuck in two minutes — that is relief, not pressure.

You do NOT know which fields are pending for this customer. Never name one.

## "अभी टाइम नहीं है" / "बाद में कर लूँगा" / "न करूँ तो क्या?"

The commonest objection on this call. It has a true answer, and the answer is
also the strongest thing you can say — so say it, and then stop there.

{mandate}

Do not reach past those two lines for something more frightening. Refunds,
circulars, cancellation dates, whether they are covered right now — you know
none of it, and a recorded call is where a guess becomes a complaint. Anything
outside them: मुझे इसका exact जवाब पता नहीं है सर, team confirm करके बता देगी।

If they still say no: offer a callback, take a time, thank them, close.

A question is NOT a refusal — "न करूँ तो क्या?", "कब तक time है?", "ये safe है?"
all get answered, and they do not count. A refusal is "नहीं", "बाद में", "टाइम
नहीं है", "खुद कर लूँगा". Count only those. After the SECOND one you stop asking — no "बस दो मिनट", no
"अभी कर लेते हैं", not once more. Take a callback time if they will give one,
thank them, and end the call. Pushing a third time is how the number gets
blocked, and they were always going to hang up anyway.

# THE CALL

Say you are an AI assistant in your very first line. Required, every call.

## 1. Get them to the form

    Park+ app  →  Insurance icon  →  insurance home screen  →  "Complete KYC"

There is a screen in between. Never say "Complete KYC दिख रहा होगा" while they
are still on the app's main screen — the button is not there yet and they will
hunt for it. Insurance icon first, wait for "खुल गया", THEN:

    सर, insurance वाला page खुल गया? उस पर 'Complete KYC' का button दिखेगा —
    उसी पे click कीजिए।

Then stop and wait again.

## 2. When a form opens — NEVER read the fields out

This is the rule for both pages and it is the one that makes or breaks the call.
The customer is looking at the form and you are not. Reciting fields at someone
who can see them turns two minutes into twenty.

Say this, then be quiet:

    सर, form खुल गया है। आप आराम से सारी details complete कर दीजिए। मैं line पे
    ही हूँ — कहीं error या confusion हो तो बता दीजिए, मैं help कर दूँगी।

Then WAIT. Silence is correct. They are typing.

## 3. Help only when they ask

Answer that ONE thing, then go quiet again. Every field is listed under THE
SCREENS — answer from there, never from guesswork, and answer straight:
pre-filled means pre-filled, with no "अगर खाली दिखे तो भर दीजिए" hedge on it.

EMPTY, they type — owner's name, email, current address, and all three nominee
fields. Whose name, whose email: theirs; the policy goes to that address.
ALREADY FILLED, they only look — date of birth, gender, engine number, chassis
number, the four previous-insurer fields.
THEY CONFIRM — Is Indian?, Is Politically Exposed?, purchased on loan? Set on
their screen, not answered to you.

Engine number and chassis number come from Park+'s own records and are already
on the screen. Never add "RC से देख के डाल दीजिए" or "अगर खाली दिखे तो भर दीजिए"
to a field listed as filled — that sends someone off to find their RC book for
nothing. Never call an EMPTY field filled. That makes someone tick the declaration and
press Next on a blank form, and it fails in front of them. For a field THE
SCREENS does not list at all: जो भी field खाली हो वो भर दीजिए सर।

## 4. The KYC page — same rule

Do not announce PAN, Aadhaar and the uploads. They are on the screen in front of
them. Say the same "complete कर दीजिए, मैं line पे हूँ" line, then wait.

Reaching this page is NOT a question. "अब KYC वाला page आ गया है" means keep
going, not recite what is on it.

Answer WHICH documents are needed only if they ask, and for their case only —
the set depends on who owns the car:

- individual / private car → PAN number, Aadhaar number, Aadhaar front image,
  Aadhaar back image
- company-owned car → PAN number, PAN photo, GST certificate. NO Aadhaar at
  all — not the number, not the images

If THIS CALL states the ownership, you already know — use that set and never
ask. If it does not, that means UNKNOWN, never individual: ask that one
question rather than listing both sets at them.

The one thing worth saying unprompted, and only when they are actually at the
Aadhaar number: it has to be typed exactly right. One wrong digit and the KYC
FAILS and the whole thing is redone. Ten seconds now saves a second call.

The Full Name here must also match the name on the previous page, or the upload
is rejected.

## 5. When they say they are done

Thank them and say you will check and confirm.

Asked when the policy will arrive, say this and nothing more — no date, no
number of days, no "24 to 48 hours":

    {delivery} You cannot see the system, so you
never call it complete — and you never answer this with the IRDAI line either.
That one is for someone refusing, not for someone who has finished.

## When it does not work

THREE failures are known and written down. You fix these yourself, calmly, and
more than once if they need it:

- "Complete KYC का button दिख ही नहीं रहा" → work DOWN this ladder, one step per
  turn, in order. Do not jump to the bottom because they sound annoyed, and do
  not offer the link until they have actually reopened the app:

{ladder}

- KYC failed / Aadhaar rejected → almost always one wrong digit. Have them
  re-enter the Aadhaar number carefully, and check the Full Name matches the
  name on the previous page.
- Next or Complete KYC does nothing → the declaration checkbox is not ticked.
  It stays GREYED OUT until it is, on BOTH pages, and it is the commonest
  reason someone says the app is broken.

Anything ELSE — a screen that looks wrong, an error you do not recognise — you
get ONE try at, then you stop and hand over. Do not guess at error messages, do
not invent a screen or a button that is not listed below:

सर, ये मुझसे यहाँ से नहीं हो पा रहा — मैं हमारी team को भेज देती हूँ, वो आपको
call करके करवा देंगे।

Then close warmly. A customer handed to a human in two minutes is a success. A
customer walked in circles for ten is how the number gets blocked.

One job per turn. Ask or confirm, not both plus an explanation.

# THINGS YOU MUST NEVER SAY

These are not style preferences. Each one is either a compliance breach or a
promise nobody can keep.

- Never ask for an OTP. Not once, not "just to verify". If they offer one,
  refuse it: OTP किसी को मत बताइए सर, मुझे भी नहीं।
- Never ask for a PAN, Aadhaar, GSTIN or CIN number on the call. They go in the
  app.
- Never ask for documents or photos over WhatsApp, email or message, and never
  ACCEPT them either. Offered documents, refuse plainly: आपके documents मुझे
  नहीं चाहिए सर — privacy की वजह से ये सब app में ही होता है, मैं यहाँ से नहीं
  भर सकती।
- Never offer to SEND anything — no link, no SMS, no WhatsApp, no email. You
  have no way to send a message, so it is a promise that breaks on every call.
  The app is already on their phone. The handover is a person ringing them.
- Never say KYC, verification or the proposal is complete. You cannot see it.
- Never promise when the policy will be issued, or that a refund is approved.
- Never state an insurer requirement that is not in the context below. If you do
  not know, say it is not confirmed and a colleague will check.
- Never cite a regulation, circular, section or penalty beyond the one sanctioned
  line above, and never say their money is stuck, blocked, lost or refundable.
  You do not know, and on a recorded call a guess is a complaint.
- Never describe an app screen, button, field or error message that is not in
  THE SCREENS below. Guessing wrong sends them hunting and costs the call.
  Hand over instead.
- Never ask the customer to read a field value back to you unless the screen
  asks them to type it and it is not sensitive.

# HOW YOU SOUND

Gurgaon Hindi with English words left in English — KYC, app, upload, policy,
payment stay English. Short turns. You are calling about someone's money and
their documents: calm and exact, never breezy.

# WHAT YOU KNOW

{context}
"""


def _format_context(ctx: dict, ownership: str | None = None,
                    insurer: str | None = None) -> str:
    """The facts the bot may state, rendered from context.json.

    Rendering the screens from data rather than hard-coding them into the
    template means a screen change is a data edit, not a prompt rewrite.

    The four field states are kept DISTINCT on purpose. Collapsing them is what
    makes the bot ask someone to retype a chassis number that is already on their
    screen, or tell them the form needs nothing when three fields are blank.

    `ownership` comes from the call card when the dialer knows it. The KYC page
    is the one screen that genuinely differs: a company-owned car needs a PAN
    photo and a GST certificate and NO Aadhaar at all. Rendering the Aadhaar
    fields to a company case put them in front of the model as the fields on
    this customer's screen, and it read them out — the wrong document set, to
    someone who cannot supply it. So when ownership is known, only that set is
    rendered.
    """
    app = ctx["app_flow"]
    STATE = {
        "customer_fills": "TYPE",
        "customer_confirms": "CONFIRM",
        "customer_uploads": "UPLOAD",
        "prefilled": "already filled, just check",
    }
    lines = [
        f"Business: {ctx['business']['name']} — {ctx['business']['purpose']}.",
        f"Not in scope: {', '.join(ctx['business']['not_in_scope'])}.",
        "",
        "# THE SCREENS",
        "",
        "Progress bar: " + " → ".join(app["stepper"]) + ". Payment is already done.",
        "Getting there: " + " → ".join(app["entry_path"]) + ".",
        "",
        "At the bottom of BOTH pages:",
        f'  checkbox — "{app["declaration"]["label"]}"',
        f'  {app["declaration"]["note"]}',
    ]
    for key in ("proposal_page", "kyc_page"):
        page = app[key]
        same = ("SAME for every insurer" if page["same_for_all_insurers"]
                else "DIFFERS by insurer")
        lines += ["", f'## Page: "{page["title"]}" — {same}',
                  f'   submit button: "{page["submit_button"]}"']
        sections = page["sections"]
        flows = page.get("insurer_flows") or {}
        united = flows.get("united")
        if key == "kyc_page" and united and insurer and "united" in insurer.lower():
            # United does not use this page at all — submitting the proposal
            # redirects to HyperVerge and everything happens there, with live
            # capture rather than uploads. Rendering the normal Aadhaar upload
            # fields to a United case would send them looking for a Browse
            # button that is not on their screen.
            lines.append(f'  THIS customer is with {united["label"]}, which does '
                         f'NOT use this page. {united["how"]}')
            lines += [f"    {i}. {step}" for i, step in enumerate(united["steps"], 1)]
            lines.append(f'  {united["note"]}')
            sections = []
        elif key == "kyc_page" and ownership == "company":
            company = app["kyc_page"]["ownership_types"]["company_owned_car"]
            lines.append("  THIS customer's car is COMPANY-OWNED, so this page asks for:")
            lines += [f"    - {doc}" for doc in company["documents"]]
            lines.append(f'  {company["note"]}')
            sections = []
        elif key == "kyc_page" and ownership == "individual":
            lines.append("  THIS customer's car is INDIVIDUALLY owned — the fields below "
                         "are the ones on their screen. No GST certificate, no PAN photo.")
        for section in sections:
            lines.append(f"  {section['name']}:")
            for f in section["fields"]:
                bits = [f"{STATE[f['state']]}: {f['label']}"]
                if f.get("type") and f["type"] != "upload":
                    bits.append(f["type"])
                if f.get("formats"):
                    bits.append(f"Browse, {f['formats']}")
                if f.get("help"):
                    bits.append(f["help"])
                lines.append("    - " + " — ".join(bits))
        # The KYC page's warnings are about ITS fields — typing the Aadhaar
        # number, photographing the card. Whenever this customer's KYC does not
        # use that page, those warnings name fields that are not on their
        # screen: a company car has no Aadhaar at all, and United captures it
        # live on HyperVerge with no Browse button anywhere. Both were caught by
        # the same assertion, one after the other.
        replaced = key == "kyc_page" and not sections and page.get("sections")
        for warning in page.get("failure_warnings", []):
            if replaced and re.search("aadha?ar", warning, re.I):
                continue
            lines.append(f"  WARN: {warning}")
        if page.get("on_screen_warning"):
            lines.append(f'  On screen: {page["on_screen_warning"]}')

    lines += [
        "",
        "IN THE APP, NEVER ON THIS CALL: "
        + ", ".join(sorted(set(ctx["field_groups"]["upload_only"])
                           | set(ctx["field_groups"]["sensitive_id_voice"]))) + ".",
        "",
        "Anything about this product that is NOT written above is something you "
        "do not know. Say so and hand over; do not fill the gap yourself.",
    ]
    return "\n".join(lines)


#: For every goal EXCEPT complete_kyc. No screens, no walkthrough, no forms.
SHORT_CALL_TEMPLATE = """\
You are Monika, the Park+ Insurance AI calling assistant, calling a customer
about the motor insurance they already paid for.

Say you are an AI assistant in your very first line. Required, every call.
{call_card}
# THIS IS NOT A KYC WALKTHROUGH

Their KYC is not what you are ringing about. Do NOT ask them to open the app, do
NOT walk them through any form, do NOT ask for a single document. There is
nothing on this call for them to do.

Your whole job is three sentences, and the FIRST turn carries all three:
  1. who you are and which vehicle this is about
  2. what the position actually is, from THIS CALL above, in plain Hindi
  3. what happens next — our team is handling it, or nothing at all if the
     policy is already issued

Then thank them and let them go. A minute is plenty.

Do not ask whether you may speak, do not ask if this is a good time, do not ask
how they are. You rang with news that takes twenty seconds; open with it. If the
policy is issued, that is good news — say so in the first breath.

If they ask something the card does not answer — why, how long, how much, what
about the money — you do not know it. Say so and say the team will confirm:
मुझे इसका exact जवाब पता नहीं है सर, team check करके आपको बता देगी।

# THINGS YOU MUST NEVER SAY

- Never ask for an OTP, a PAN, an Aadhaar, a GSTIN or any document. Nothing on
  this call needs them.
- Never read out an error code, a policy number, a proposal id or any reference.
- Never promise when the policy will be issued, or that a refund is approved.
- Never invent a reason. If the card does not say why, you do not know why.
- Never say a status the card does not state.

# HOW YOU SOUND

Gurgaon Hindi with English words left in English — KYC, app, policy, payment
stay English. Short turns. You are calling about someone's money, so be calm and
exact, never breezy. If they are annoyed, apologise once, say the team is on it,
and close.
"""


def _format_ladder(ctx: dict) -> str:
    return "\n".join(f"  {i}. {line}"
                      for i, line in enumerate(ctx["button_not_found"]["ladder"], 1))


def _format_mandate(ctx: dict) -> str:
    """The only two sentences the bot may say about WHY KYC is mandatory.

    Kept in context.json rather than hard-coded here because the guard checks
    the same block: what is sanctioned and what is a fabrication have to be one
    decision, made in one place.
    """
    m = ctx["kyc_mandate"]
    lines = ["Asked why:", "", f'    {m["sanctioned_lines"]["why"]}', "",
             "Asked how long they have:", "", f'    {m["sanctioned_lines"]["deadline"]}']
    return "\n".join(lines)


def build_system_prompt(mode: str = "outbound", card: dict | None = None) -> str:
    """The system prompt, optionally narrowed to one customer's case.

    With no card this is exactly what it has always been — the full walkthrough,
    for a bot that knows the product and nothing about who picked up. That is the
    degraded mode when the prefetch fails, and it still works.

    With a card, the goal picks the playbook: complete_kyc keeps the walkthrough,
    and every other goal gets SHORT_CALL_TEMPLATE, which has no screens in it at
    all because there is nothing for the customer to do.
    """
    if mode not in OPENINGS:
        raise ValueError(f"mode must be one of {sorted(OPENINGS)}, got {mode!r}")
    block = f"\n{call_card.render(card)}\n" if card else ""

    if card and card["goal"] != "complete_kyc":
        return SHORT_CALL_TEMPLATE.format(call_card=block)

    ctx = json.loads(CONTEXT_FILE.read_text())
    return SYSTEM_PROMPT_TEMPLATE.format(
        opening=OPENINGS[mode],
        mandate=_format_mandate(ctx),
        ladder=_format_ladder(ctx),
        delivery=ctx["policy_delivery"]["sanctioned_line"],
        context=_format_context(ctx, (card or {}).get("ownership_type"),
                                (card or {}).get("insurer")),
        call_card=block,
    )


def _demo():
    ctx = json.loads(CONTEXT_FILE.read_text())
    for mode in OPENINGS:
        p = build_system_prompt(mode)
        # The prompt is resent every turn. The bill is not the real constraint —
        # input tokens on Gemini flash are cheap and prefill is not what makes a
        # turn feel slow (reply LENGTH is: Sarvam speaks ~12 chars/sec). The
        # ceiling is here because instructions DILUTE: every rule added makes
        # the others weaker, and this prompt is mostly safety rules. So growth
        # has to be paid for by deleting something, not by raising the number.
        # Raised again to 3900 later the same day. The first two raises were
        # paid for by deletion, but at 3750 the suite's remaining failures were
        # all the same shape — a rule the model followed most of the time and
        # hedged on the rest — and every one of them was fixed by making the
        # rule MORE specific, not by removing another. Dilution is still the
        # reason there is a ceiling; vagueness turned out to cost more.
        # Raised 3400 -> 3750 on 2026-09-19, paid for by deleting the
        # per-insurer matrix (unusable without a per-case payload), the
        # engineering notes, and two sections that restated rules stated
        # elsewhere. What it bought: the IRDAI mandate answer, the pre-filled
        # rule, known-failure handling, and refusal counting.
        # 4300 as of 2026-09-20. The ceiling exists to make growth deliberate,
        # not to hold a number: the prompt got bigger because the PRODUCT got
        # bigger, and every addition came from a live call or the product owner.
        # In this round: the button-not-found ladder (the 14:55 call spent four
        # turns stuck there with nothing to climb), the policy-delivery answer
        # (asked twice, answered "मुझे इसका exact जवाब पता नहीं है" three times),
        # the refusal for offered documents, and the address field's
        # no-special-characters rule.
        #
        # What keeps it from running away is that the biggest blocks are now
        # CONDITIONAL — United's HyperVerge flow renders only for United, the
        # company document set only for a company car, and a non-KYC goal drops
        # the walkthrough entirely. Growth in the shared part still has to be
        # paid for by a deletion.
        tokens = len(p) / 3.2
        assert tokens < 4300, f"{mode}: {tokens:.0f} tokens is too expensive per turn"
        assert "AI assistant" in p
        # Every hard rule must actually be stated, not just implied.
        for rule in ("OTP", "WhatsApp", "complete", "refund"):
            assert rule in p, f"{mode}: missing the {rule} rule"
        # The app handoff IS the product.
        assert "app" in p.lower()
        # The real screen labels must reach the prompt verbatim — the bot says
        # them out loud and the customer is looking at them.
        for label in ("Confirm policy details", "Car Owner's name (as per RC)",
                      "Nominee Details", "Aadhar Front Image", "Engine Number",
                      "Chassis Number", "Previous Own Damage Insurer name",
                      "Complete KYC", "Next"):
            assert label in p, f"{mode}: screen label missing: {label!r}"
        # The four field states must stay DISTINCT in the rendered prompt. When a
        # renderer edit silently stopped matching the new state names, every
        # field came out as "already filled" — the bot would have told customers
        # the form needed nothing while three fields sat blank. Caught by reading
        # the output, not by the prompt building without error.
        for state in ("TYPE:", "CONFIRM:", "UPLOAD:", "already filled, just check:"):
            assert state in p, f"{mode}: field state missing from the prompt: {state}"
        assert p.count("TYPE:") >= 6, "the fields the customer types went missing"
        # The two things that actually cost calls.
        assert "hereby declare" in p, "the declaration checkbox blocks submit"
        # The sanctioned answer to the commonest objection. Rendered from
        # context.json, so a bad edit there silently muted the bot on the one
        # question every customer asks — until this caught it.
        assert "IRDAI" in p, "the sanctioned mandate line went missing"
        for line in ctx["kyc_mandate"]["sanctioned_lines"].values():
            assert line in p, f"a sanctioned mandate line went missing: {line[:40]}"
        assert "FAILS" in p, "the wrong-Aadhaar-digit warning must survive"

    # --- with a call card -----------------------------------------------------
    no_card = build_system_prompt("outbound")
    assert "{call_card}" not in no_card and "# THIS CALL" not in no_card, \
        "no card must render exactly the prompt it always did"

    kyc = call_card.build({
        "customer_name": "Rahul Suresh Singh", "insurer": "Bajaj",
        "vehicle_reg": "DL6CP8915", "kyc_status": "PENDING",
    })
    p_kyc = build_system_prompt("outbound", kyc)
    assert "Rahul Suresh Singh" in p_kyc and "DL6CP8915" in p_kyc
    # complete_kyc still gets the whole walkthrough — the screens are the job.
    assert "Complete KYC" in p_kyc and "hereby declare" in p_kyc
    assert "Aadhar Front Image" in p_kyc

    dup = call_card.build({
        "customer_name": "Rahul", "insurer": "United India", "vehicle_reg": "DL6CP8915",
        "kyc_status": "SUCCESS", "proposal_status": "PROPOSAL_PENDING",
        "error_code": "IERR_DUPLICATE_POLICY",
        "blocker": "Duplicate policy — already insured under TP 0407033126P108547203",
        "do_not_say": ["IERR_DUPLICATE_POLICY"],
    })
    p_dup = build_system_prompt("outbound", dup)
    # A call with nothing for the customer to do must not carry a form guide.
    # Shipping the walkthrough here is how the bot starts hunting for a screen
    # to send someone to on a call that needed one honest sentence.
    for screen in ("hereby declare", "Aadhar Front Image", "Complete KYC button",
                   "Engine Number", "Nominee Details"):
        assert screen not in p_dup, f"the short call must not carry {screen!r}"
    assert "Rahul" in p_dup and "already insured" in p_dup
    assert "AI assistant" in p_dup, "the disclosure is required on every call"
    assert "OTP" in p_dup, "the OTP rule is required on every call"
    assert "0407033126P108547203" not in p_dup, "identifiers must never reach the model"
    assert len(p_dup) < len(p_kyc) / 2, "the short call should be much shorter"

    # A company-owned car must not have the Aadhaar fields rendered as "the
    # fields on their screen" — that set is not on their screen at all.
    company = call_card.build({"customer_name": "Neha Bhatia", "kyc_status": "PENDING",
                               "ownership_type": "Company"})
    p_co = build_system_prompt("outbound", company)
    screens = p_co.split("# THE SCREENS", 1)[1]
    for aadhaar_field in ("Aadhar Number", "Aadhar Front Image", "Aadhar Back Image"):
        assert aadhaar_field not in screens, f"{aadhaar_field} rendered for a company car"
    assert "GST certificate" in p_co and "PAN photo" in p_co
    assert "Neha जी" in p_co, "a name replaces सर, and जी carries no gender"

    individual = call_card.build({"customer_name": "Rahul", "kyc_status": "PENDING",
                                  "ownership_type": "Individual"})
    p_ind = build_system_prompt("outbound", individual)
    ind_screens = p_ind.split("# THE SCREENS", 1)[1]
    assert "Aadhar Front Image" in ind_screens
    assert "COMPANY-OWNED" not in ind_screens

    # Unknown ownership still renders the common case AND lets the bot ask.
    unknown = call_card.build({"customer_name": "Rahul", "kyc_status": "PENDING"})
    assert "ownership_type" not in unknown
    assert "Aadhar Front Image" in build_system_prompt("outbound", unknown)

    issued = call_card.build({"customer_name": "Asha", "policy_number": "P9001",
                              "kyc_status": "SUCCESS"})
    assert "ISSUED" in build_system_prompt("outbound", issued)

    # --- 2026-09-20: facts added after the 14:55 call --------------------------
    for fact, why in (
        ("app बंद करके दोबारा खोलिए", "the button-not-found ladder"),
        ("WhatsApp पर KYC का link", "the ladder's last step"),
        ("notification", "the policy-delivery answer"),
        ("special characters are rejected", "the address field rule"),
        ("NEVER tell a customer to cut", "the 14:55 call told someone to cut their Aadhaar in half"),
        ("privacy की वजह से", "refusing offered documents"),
    ):
        assert fact in no_card, f"{why} went missing: {fact!r}"

    # United does its KYC on HyperVerge, not on this page at all.
    utd = call_card.build({"customer_name": "Asha", "kyc_status": "PENDING",
                           "insurer": "United India"})
    p_utd = build_system_prompt("outbound", utd)
    assert "HyperVerge" in p_utd and "selfie" in p_utd
    utd_screens = p_utd.split("# THE SCREENS", 1)[1]
    for upload_field in ("Aadhar Front Image", "Aadhar Back Image"):
        assert upload_field not in utd_screens, \
            f"{upload_field} rendered for United, which has no Browse button"
    # ...and nobody else gets sent to HyperVerge.
    other = call_card.build({"customer_name": "Asha", "kyc_status": "PENDING",
                             "insurer": "Bajaj"})
    assert "HyperVerge" not in build_system_prompt("outbound", other)
    assert "HyperVerge" not in no_card, "with no card the insurer is unknown"

    # The opening's LENGTH is the product decision. At ~12 characters of Hindi
    # per second, 135 characters is about eleven seconds — already long for the
    # first thing a stranger hears. The version this replaced was 169 and the
    # caller in the 14:55 call tried to answer four seconds in.
    spoken = re.sub(r"\s+", " ",
                    re.search(r"नमस्ते[^\"]*?App खोल लीजिए\?", OPENINGS["outbound"],
                              re.S).group(0))
    assert len(spoken) <= 135, f"the opening grew back to {len(spoken)} chars " \
                               f"(~{len(spoken) / 12:.0f}s of speech)"
    for clause in ("Park+", "Monika", "AI assistant", "KYC", "दो मिनट", "App"):
        assert clause in spoken, f"the opening lost a load-bearing clause: {clause}"

    assert build_system_prompt("outbound") != build_system_prompt("inbound")
    try:
        build_system_prompt("sideways")
        raise AssertionError("unknown mode must raise")
    except ValueError:
        pass
    sizes = {m: int(len(build_system_prompt(m)) / 3.2) for m in OPENINGS}
    print("insurance prompt ok — " + ", ".join(f"{m} ~{t} tokens" for m, t in sizes.items()))


if __name__ == "__main__":
    _demo()
