"""The per-case facts for ONE call, fetched before the phone rings.

Until now the bot knew the product but nothing about the person it had dialled:
every call opened identically, could not use their name, and had no idea whether
the KYC it was ringing about was already done. This is that missing half.

The shape is a decision, not a convenience. A voice agent does not get a database
connection: it must not write SQL mid-call, must not wait on a query while the
customer is listening to silence, and must never be handed a row that still has
`error_details` and a chassis number in it. So the dialer runs one fixed query
before dialling, and the agent receives a small flat card.

Three rules hold that line, and all three are enforced here rather than asked
for in the prompt:

1. **Whitelist, not blacklist.** `FIELDS` is the complete set of keys that may
   reach the model. The prefetch query selects more than that — error_message_short,
   premiums, timestamps — because ops need them. Anything not in `FIELDS` is
   dropped on the way in, so a column added to the query next month cannot quietly
   become something the bot says out loud.

2. **The goal is an enum, not a sentence.** `call_goal` free text would be one
   more thing for the model to interpret. `GOALS` is a fixed set, derived from the
   statuses by `derive_goal()`, and the prompt branches on it. A dialer that sends
   its own `call_goal` string gets it shown to the model as context, but the
   branch still comes from the enum.

3. **Identifiers are stripped from free text.** `blocker` is human-written or
   DB-derived and the real example carries a policy number in it
   ("already insured under TP 0407033126P108547203"). Nobody wants that read down
   a phone line, so `_strip_identifiers` removes long alphanumeric runs before the
   model ever sees the string.

The card is optional everywhere. With no card the bot behaves exactly as it did
before — which is the degraded mode when the prefetch fails, and the reason the
dialer can roll this out gradually.

    DOMAIN=insurance python -m domains.insurance.call_card
"""

import json
import re

#: Every key the model may see. Anything else in the incoming body is dropped.
#:
#: Deliberately absent, and listed here so the next person does not re-add them:
#: chassis and engine numbers (on the customer's screen already, and identity
#: data in a transcript), payment and audit transaction ids, raw `error_details`,
#: `error_message_short` (insurer error prose, written for engineers), and the
#: premium figures — a bot that quotes money it cannot verify is how a call turns
#: into a refund dispute.
FIELDS = (
    "proposal_id",
    "customer_name",
    "insurer",
    "policy_type",
    "vehicle_reg",
    "prev_policy_expiry",
    "proposal_status",
    "kyc_status",
    "fulfillment_status",
    "policy_number",
    "ownership_type",
    "kyc_deadline_hint",
    "blocker",
    "call_goal",
    "do_not_say",
)

#: `metadata.owner_type` as the DB writes it, mapped to what the prompt branches
#: on. Roughly 795k Individual to 5.2k Company in DB 258.
#:
#: An unmappable or missing value stays MISSING — never "individual", however
#: lopsided that ratio is. Guessing wrong on the 5.2k means telling a company car
#: owner to photograph an Aadhaar that is not part of their KYC at all, and the
#: upload fails in front of them. Unknown means the bot asks one question, which
#: costs a turn; guessing costs the call.
_OWNERSHIP = {"individual": "individual", "company": "company"}

#: What the call is FOR, decided before dialling. The prompt branches on this.
GOALS = {
    # The ordinary case and the reason this product exists.
    "complete_kyc": "Get the KYC finished in the Park+ app.",
    # KYC is already done. Asking them to redo it is the single most annoying
    # thing this bot could do to someone who has already done the work.
    "explain_blocker": (
        "KYC is DONE. Do not ask for it again. Say what is holding the policy up, "
        "in plain language, and that the team is on it."
    ),
    "escalate_duplicate": (
        "The vehicle is already insured. Do not push KYC and do not take documents. "
        "Say a colleague will call to sort it out."
    ),
    "explain_requote": (
        "The amount paid does not match the premium. Do not collect anything. "
        "Say the team is checking it and will call back."
    ),
    "confirm_issued": (
        "The policy is ISSUED. Nothing is pending. Confirm it warmly and let them go."
    ),
}

#: Error codes that change the call, mapped to the goal they force.
_BLOCKING_ERRORS = {
    "IERR_DUPLICATE_POLICY": "escalate_duplicate",
}

# Policy numbers, proposal ids, transaction refs. Six or more characters with at
# least one digit, which is what an identifier looks like and what an ordinary
# Hindi or English word does not.
_IDENTIFIER_RE = re.compile(r"\b(?=[A-Za-z0-9/-]*\d)[A-Za-z0-9/-]{6,}\b")

_MAX_BLOCKER_CHARS = 160

_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")


def _speakable_date(value) -> str | None:
    """An ISO date as something a voice can say, or None.

    The DB hands over "2026-10-15" and a TTS reads that as digits and dashes.
    Formatting here rather than asking the prompt to do it means the model never
    sees the raw string, so it cannot read one out on a bad turn — and an
    unparseable value becomes no date at all, which is the safe end of the
    trade: a missing urgency line costs nothing, a wrong lapse date is a lie
    about someone's cover.
    """
    text = str(value or "").strip()[:10]
    try:
        year, month, day = (int(part) for part in text.split("-"))
        if not (1 <= month <= 12 and 1 <= day <= 31 and 2000 <= year <= 2100):
            return None
    except (ValueError, TypeError):
        return None
    return f"{day} {_MONTHS[month - 1]} {year}"


def _strip_identifiers(text: str) -> str:
    """Remove things nobody should read down a phone line."""
    return re.sub(r"\s{2,}", " ", _IDENTIFIER_RE.sub("", text)).strip(" -—,")


def derive_goal(row: dict) -> str:
    """Which GOAL this case is, from the statuses. Most decisive rule first.

    An issued policy outranks everything: whatever else the row says, if there is
    a policy number then nothing is pending and asking for KYC is absurd. A
    duplicate outranks the rest because pushing KYC at someone whose car is
    already insured is worse than doing nothing.
    """
    if row.get("policy_number"):
        return "confirm_issued"

    error = (row.get("error_code") or "").strip().upper()
    if error in _BLOCKING_ERRORS:
        return _BLOCKING_ERRORS[error]

    paid, expected = row.get("paid_amount"), row.get("paid_or_expected_premium")
    if paid is not None and expected is not None:
        try:
            # A rupee of rounding between the gateway and the insurer is normal.
            if abs(float(paid) - float(expected)) > 1:
                return "explain_requote"
        except (TypeError, ValueError):
            pass

    if str(row.get("kyc_status") or "").strip().upper() == "SUCCESS":
        # KYC is done, so whatever is still pending is not the customer's to fix.
        return "explain_blocker" if row.get("proposal_status") != "PROPOSAL_SUCCESS" \
            else "confirm_issued"

    return "complete_kyc"


def build(row: dict | None) -> dict | None:
    """A prefetched row (or an already-shaped card) as the card the model sees.

    Returns None for anything unusable, because a bot with no card behaves
    exactly as it always has — which is a far better failure than a bot
    greeting someone by a name that belongs to a different customer.
    """
    if not isinstance(row, dict) or not row:
        return None

    card = {k: row[k] for k in FIELDS if row.get(k) not in (None, "", [])}
    card["goal"] = row.get("goal") if row.get("goal") in GOALS else derive_goal(row)

    ownership = _OWNERSHIP.get(str(card.get("ownership_type", "")).strip().lower())
    if ownership:
        card["ownership_type"] = ownership
    else:
        card.pop("ownership_type", None)

    for key in ("kyc_deadline_hint", "prev_policy_expiry"):
        spoken = _speakable_date(card.get(key))
        if spoken:
            card[key] = spoken
        else:
            card.pop(key, None)

    if "blocker" in card:
        blocker = _strip_identifiers(str(card["blocker"]))[:_MAX_BLOCKER_CHARS]
        if blocker:
            card["blocker"] = blocker
        else:
            del card["blocker"]

    do_not_say = card.get("do_not_say")
    if isinstance(do_not_say, str):
        do_not_say = [do_not_say]
    card["do_not_say"] = [str(t).strip() for t in (do_not_say or []) if str(t).strip()]

    return card


def from_body(body) -> dict | None:
    """The card out of a Pipecat runner body, however the dialer nested it.

    `--runner-body` is the per-session channel Pipecat already has, and the eval
    harness passes the same thing through `runner_body:`, so a scenario can
    rehearse a real case.
    """
    if isinstance(body, (str, bytes)):
        try:
            body = json.loads(body)
        except (ValueError, TypeError):
            return None
    if not isinstance(body, dict):
        return None
    return build(body.get("call_card") or body.get("CALL_CARD") or body)


def render(card: dict) -> str:
    """The CALL CARD block, as the prompt shows it."""
    lines = ["# THIS CALL", "", GOALS[card["goal"]], ""]

    labels = (
        ("customer_name", "Customer"),
        ("insurer", "Insurer"),
        ("vehicle_reg", "Vehicle"),
        ("policy_type", "Cover"),
        ("ownership_type", "Ownership"),
        ("kyc_deadline_hint", "Their current cover runs out"),
        ("kyc_status", "KYC status"),
        ("proposal_status", "Proposal status"),
        ("policy_number", "Policy number"),
        ("prev_policy_expiry", "Previous policy expires"),
    )
    for key, label in labels:
        if card.get(key):
            lines.append(f"  {label}: {card[key]}")

    if card.get("blocker"):
        lines += ["", f'What is stuck: {card["blocker"]}',
                  "Say that in your own plain words. Never read it out verbatim, "
                  "never read a code or a number out of it."]

    if card.get("kyc_deadline_hint"):
        lines += ["", "That date is when their EXISTING cover lapses, and it is the "
                  "one honest reason to do this today rather than next week. Use it "
                  "if they stall. It is not a KYC deadline and not the new policy's "
                  "end date — do not call it either of those."]

    if card.get("customer_name"):
        # The prompt's scripts all say "सर", which is fine when the bot knows
        # nothing about who picked up. Once it has a name it is not fine: the
        # eval caught it opening "नमस्ते सर" to a Neha. Nothing in the card says
        # whether this is a man or a woman, and a name is not evidence — so the
        # bot uses "जी", which is respectful and carries no gender at all.
        first = str(card["customer_name"]).split()[0]
        lines += [
            "",
            f'Their name is {first}. Say "{first} जी" wherever the scripts below '
            f'say "सर", including in the opening line.',
            "Never say सर or मैडम to them, and never guess whether they are a man "
            "or a woman — not from the name, not from the voice. जी fits everyone.",
        ]

    if card.get("do_not_say"):
        lines += ["", "NEVER say these out loud: " + ", ".join(card["do_not_say"]) + "."]

    lines += [
        "",
        "This card is the only thing you know about THIS customer. Every status "
        "above is what our system says right now. Anything not on it — what they "
        "have already typed, which field is blank, why the insurer objected — you "
        "do NOT know, and you do not guess.",
    ]
    return "\n".join(lines)


def _demo():
    # The worked example from the product owner's spec, verbatim.
    duplicate = build({
        "proposal_id": 845671,
        "customer_name": "Rahul Suresh Singh",
        "insurer": "United India",
        "policy_type": "COMPREHENSIVE",
        "vehicle_reg": "DL6CP8915",
        "proposal_status": "PROPOSAL_PENDING",
        "kyc_status": "SUCCESS",
        "fulfillment_status": "ORDER_FULFILLED",
        "error_code": "IERR_DUPLICATE_POLICY",
        "blocker": "Duplicate policy — vehicle already insured under TP 0407033126P108547203",
        "do_not_say": ["IERR_DUPLICATE_POLICY", "engine number", "chassis number"],
    })
    assert duplicate["goal"] == "escalate_duplicate", duplicate["goal"]
    # The policy number in the blocker must not survive to anything speakable.
    assert "0407033126P108547203" not in json.dumps(duplicate, ensure_ascii=False)
    assert "already insured" in duplicate["blocker"]

    # The whitelist is the enforcement, not the prompt. A dialer that sends the
    # whole row must not be able to put identity data in front of the model.
    leaky = build({
        "proposal_id": 1, "kyc_status": "PENDING", "insurer": "HDFC",
        "chassis_number": "SAJAB4AN9JL9961421117",
        "engine_number": "170911P0005204DTF",
        "error_details": {"raw": "stack trace with a PAN in it ABCDE1234F"},
        "error_message_short": "IERR_9001 proposer.pan mismatch at node 4",
        "payment_txn_id": "pay_29f8a1",
    })
    blob = json.dumps(leaky, ensure_ascii=False) + render(leaky)
    for leaked in ("SAJAB4AN", "170911P", "ABCDE1234F", "IERR_9001", "pay_29f8a1"):
        assert leaked not in blob, f"{leaked} reached the model"

    # Every branch of the goal table.
    assert build({"kyc_status": "PENDING"})["goal"] == "complete_kyc"
    assert build({"kyc_status": "FAILED"})["goal"] == "complete_kyc"
    assert build({"kyc_status": "SUCCESS",
                  "proposal_status": "PROPOSAL_PENDING"})["goal"] == "explain_blocker"
    assert build({"kyc_status": "SUCCESS",
                  "proposal_status": "PROPOSAL_SUCCESS"})["goal"] == "confirm_issued"
    assert build({"kyc_status": "PENDING",
                  "policy_number": "P123"})["goal"] == "confirm_issued", \
        "an issued policy outranks a pending KYC — there is nothing left to ask for"
    assert build({"kyc_status": "PENDING", "paid_amount": 5000,
                  "paid_or_expected_premium": 7200})["goal"] == "explain_requote"
    # Rounding between the gateway and the insurer is not a mismatch.
    assert build({"kyc_status": "PENDING", "paid_amount": 7199.5,
                  "paid_or_expected_premium": 7200})["goal"] == "complete_kyc"
    # A duplicate outranks a premium mismatch: pushing KYC at someone whose car
    # is already insured is the worse mistake.
    assert build({"kyc_status": "PENDING", "error_code": "IERR_DUPLICATE_POLICY",
                  "paid_amount": 1, "paid_or_expected_premium": 2})["goal"] \
        == "escalate_duplicate"

    # No card is a supported state, not an error: it is what happens when the
    # prefetch fails, and the bot still has a whole product to talk about.
    for empty in (None, {}, "", [], "not json"):
        assert from_body(empty) is None, empty
    assert from_body('{"call_card": {"kyc_status": "PENDING", "insurer": "Bajaj"}}')["insurer"] \
        == "Bajaj", "a JSON string body must parse"
    assert from_body({"call_card": {"kyc_status": "PENDING"}})["goal"] == "complete_kyc"
    assert from_body({"kyc_status": "PENDING"})["goal"] == "complete_kyc", \
        "an un-nested body must work too"

    # --- ownership: mapped, or absent. Never guessed. -------------------------
    assert build({"kyc_status": "PENDING", "ownership_type": "Individual"})[
        "ownership_type"] == "individual"
    assert build({"kyc_status": "PENDING", "ownership_type": "Company"})[
        "ownership_type"] == "company"
    assert build({"kyc_status": "PENDING", "ownership_type": "  company "})[
        "ownership_type"] == "company"
    for unknown in ("Proprietorship", "HUF", "", None, "individual_llp", 7):
        got = build({"kyc_status": "PENDING", "ownership_type": unknown})
        assert "ownership_type" not in got, \
            f"{unknown!r} became {got.get('ownership_type')!r} — never guess ownership"

    # --- dates: speakable, or absent. Never an ISO string. --------------------
    dated = build({"kyc_status": "PENDING", "kyc_deadline_hint": "2026-10-15",
                   "prev_policy_expiry": "2026-10-15T00:00:00"})
    assert dated["kyc_deadline_hint"] == "15 October 2026", dated["kyc_deadline_hint"]
    assert dated["prev_policy_expiry"] == "15 October 2026"
    assert "2026-10-15" not in render(dated), "a TTS would read that as digits"
    for bad in ("0000-00-00", "not a date", "15/10/2026", None, "2026-13-01"):
        assert "kyc_deadline_hint" not in build(
            {"kyc_status": "PENDING", "kyc_deadline_hint": bad}), bad

    rendered = render(duplicate)
    assert "United India" in rendered
    # First name only, and the gender-free honorific — "Rahul जी", never "सर".
    assert "Rahul जी" in rendered, rendered
    assert "Suresh Singh जी" not in rendered, "address them by first name"
    assert "IERR_DUPLICATE_POLICY" in rendered, "the do-not-say list must reach the model"
    assert "already insured" in rendered

    print(f"call card ok — {len(FIELDS)} fields, {len(GOALS)} goals, "
          f"identifiers stripped, non-whitelisted keys dropped")


if __name__ == "__main__":
    _demo()
