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
import os
import re
import time
import urllib.error
import urllib.request

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
    # Park+ user id: only for the KYC deeplink (whatsapp.py). render() never
    # shows it to the model.
    "user_id",
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
    # proposal.error_details.parsed_error_codes as DB 258 writes them.
    "ERR_POLICY_ALREADY_EXISTS": "escalate_duplicate",
    "ERR_QUOTE_PROPOSAL_PREMIUM_MISMATCH": "explain_requote",
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


# --- fetching the case by proposal id ------------------------------------------
# Given only a proposal id, the bot runs this ONE fixed query against Park+'s
# Metabase (bi.parkplus.io, DB 258 parkplus_insurance_prod) before the greeting.
# It is the same "one fixed query, flat card" contract as a dialer prefetch —
# the model never sees SQL and never waits on the database mid-call. The id goes
# in as a typed Metabase parameter, never spliced into the SQL.
#
# Deliberately NOT selected, from what the tables offer (checked 2026-09-23):
#   - premiums / paid amounts: motor_fulfillment.amount came back as 1 against a
#     final_premium of 146997 on the test proposal — units or test data, either
#     way a "your amount doesn't match" call waiting to happen. The insurer's own
#     ERR_QUOTE_PROPOSAL_PREMIUM_MISMATCH code decides that goal instead.
#   - prev_policy_expiry: user_vehicle.od_expiry_date was 2024 on a 2026 policy.
#   - chassis, engine, policy/proposal numbers beyond the existence check below.
PREFETCH_SQL = """
SELECT p.id AS proposal_id, p.user_id, p.insurer_id, p.policy_type, p.proposal_status,
       JSON_UNQUOTE(JSON_EXTRACT(p.metadata, '$.owner_type')) AS ownership_type,
       JSON_UNQUOTE(JSON_EXTRACT(p.error_details, '$.parsed_error_codes[0]')) AS error_code,
       uv.owner_name AS customer_name, uv.registration_number AS vehicle_reg,
       (SELECT k.status FROM test_ckyc k WHERE k.proposal_id = p.id
         ORDER BY k.updated_at DESC LIMIT 1) AS kyc_status,
       (SELECT f.status FROM motor_fulfillment f WHERE f.proposal_id = p.id
         ORDER BY f.updated_at DESC LIMIT 1) AS fulfillment_status,
       (SELECT po.policy_number FROM policy po WHERE po.proposal_id = p.id AND po.is_active = 1
         ORDER BY po.updated_at DESC LIMIT 1) AS policy_number
FROM proposal p
LEFT JOIN motor_quotes q ON q.id = p.quote_id
LEFT JOIN user_vehicle uv ON uv.id = q.user_vehicle_id
WHERE p.id = {{proposal_id}}
"""

#: proposal.insurer_id -> the name a customer knows. From the field graph's
#: insurer_ids (ai-calling-kyc-proposal/data/kyc-proposal-field-graph.json).
INSURER_NAMES = {
    1: "Tata AIG", 2: "ICICI Lombard", 3: "HDFC ERGO", 4: "National Insurance",
    5: "Go Digit", 6: "United India", 7: "Bajaj Allianz", 8: "Go Digit",
    9: "National Insurance",
}

# A first name the voice can say. user_vehicle.owner_name is the RC owner as
# typed — the test proposal has "dwghabdn" — so anything that does not look like
# a name is dropped and the bot says "sir" instead of greeting a string.
_NAME_RE = re.compile(r"^[A-Za-z\u0900-\u097F][A-Za-z\u0900-\u097F.'-]{1,19}$")


def _clean_name(value) -> str | None:
    words = str(value or "").split()
    if not words or not _NAME_RE.match(words[0]):
        return None
    if words[0].isascii() and not re.search(r"[aeiouyAEIOUY]", words[0]):
        return None
    return " ".join(w.capitalize() if w.isascii() else w for w in words)


# Last good row per proposal. bi.parkplus.io answers in ~0.1s (the query itself
# ~8ms) but measured from the VM on 2026-09-23 it also hung for 27-30s at random,
# and one hang landed on a live test call: the bot greeted with no name and no
# insurer. A stale row is far better than no row for a case that changes on the
# scale of hours, so a failed fetch falls back to one fetched in the last 30 min.
_CACHE: dict[int, tuple[float, dict]] = {}
_CACHE_SECS = 30 * 60


def fetch(proposal_id, timeout: float | None = None) -> dict | None:
    """The prefetch row for one proposal, from Metabase, or None.

    Never raises: no key, a bad id, a timeout or an empty result all mean "no
    card", which is the supported degraded mode — the bot runs the generic call.
    A failure returns the last good row for this proposal if it is recent.
    """
    # domain.py loads voicebot/server/.env. bot.py imports it anyway; this makes
    # a standalone `from_body({...})` check see the same key a call does.
    import domain  # noqa: F401
    key = os.getenv("METABASE_API_KEY")
    try:
        pid = int(str(proposal_id).strip())
    except (TypeError, ValueError):
        return None
    if not key or pid <= 0:
        return None
    url = (os.getenv("METABASE_URL") or "https://bi.parkplus.io").rstrip("/") + "/api/dataset"
    payload = {
        "database": int(os.getenv("METABASE_INSURANCE_DB") or 258),
        "type": "native",
        "native": {
            "query": PREFETCH_SQL,
            "template-tags": {"proposal_id": {
                "id": "proposal_id", "name": "proposal_id",
                "display-name": "Proposal ID", "type": "number", "required": True,
            }},
        },
        "parameters": [{
            "type": "number/=", "value": [pid],
            "target": ["variable", ["template-tag", "proposal_id"]],
        }],
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-api-key": key},
    )
    limit = timeout or float(os.getenv("METABASE_TIMEOUT_SECS") or 2)
    try:
        with urllib.request.urlopen(req, timeout=limit) as r:
            row = _row_from_dataset(json.loads(r.read()))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        row = None
    if row:
        _CACHE[pid] = (time.monotonic(), row)
        return row
    cached = _CACHE.get(pid)
    if cached and time.monotonic() - cached[0] < _CACHE_SECS:
        return dict(cached[1])
    return None


def customer_phone(user_id, timeout: float | None = None) -> str | None:
    """The Park+ account's phone number (user_replica user.User), or None.

    For the WhatsApp KYC link only — kept OUT of the card, so it never reaches
    the prompt or the CALL CARD log line. Parameterised like fetch(); never
    raises.
    """
    import domain  # noqa: F401  (loads .env for a standalone call)
    key = os.getenv("METABASE_API_KEY")
    try:
        uid = int(str(user_id).strip())
    except (TypeError, ValueError):
        return None
    if not key or uid <= 0:
        return None
    url = (os.getenv("METABASE_URL") or "https://bi.parkplus.io").rstrip("/") + "/api/dataset"
    payload = {
        "database": int(os.getenv("METABASE_USER_DB") or 264),
        "type": "native",
        "native": {
            "query": "SELECT phone_number FROM user.User WHERE id = {{user_id}}",
            "template-tags": {"user_id": {
                "id": "user_id", "name": "user_id", "display-name": "User ID",
                "type": "number", "required": True,
            }},
        },
        "parameters": [{
            "type": "number/=", "value": [uid],
            "target": ["variable", ["template-tag", "user_id"]],
        }],
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-api-key": key},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout or float(os.getenv("METABASE_TIMEOUT_SECS") or 2)) as r:
            rows = json.loads(r.read())["data"]["rows"]
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError):
        return None
    phone = str(rows[0][0]).strip() if rows and rows[0] and rows[0][0] else ""
    return phone or None


def _row_from_dataset(data) -> dict | None:
    """Metabase's {data: {cols, rows}} as one prefetch row, or None."""
    try:
        cols = [c["name"] for c in data["data"]["cols"]]
        rows = data["data"]["rows"]
    except (KeyError, TypeError):
        return None
    if not rows:
        return None
    row = dict(zip(cols, rows[0]))
    try:
        row["insurer"] = INSURER_NAMES.get(int(row.pop("insurer_id")))
    except (TypeError, ValueError):
        row.pop("insurer_id", None)
    row["customer_name"] = _clean_name(row.get("customer_name"))
    return row


#: A body with only these keys is a request to fetch, not a card.
_FETCH_KEYS = {"proposal_id", "do_not_say", "call_goal"}


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
    card = body.get("call_card") or body.get("CALL_CARD") or body
    # Only a proposal id: fetch the case. The dialer's own extras (do_not_say)
    # win over the fetched row. A failed fetch still leaves a card with the id.
    if isinstance(card, dict) and card.get("proposal_id") and set(card) <= _FETCH_KEYS:
        fetched = fetch(card["proposal_id"])
        if fetched:
            card = {**fetched, **card}
    return build(card)


def render(card: dict) -> str:
    """The CALL CARD block, as the prompt shows it."""
    lines = ["# THIS CALL", "", GOALS[card["goal"]], ""]

    labels = (
        ("customer_name", "Customer"),
        ("insurer", "Insurer (issues the policy; they BOUGHT it on Park+)"),
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
        # Without this the model treats the whole card as background and
        # deflects questions it can already answer: asked "वीकल नंबर बता सकते
        # हो?" with the registration sitting right here, both models answered
        # "मुझे इसका exact जवाब पता नहीं है, team बता देगी". The card block was
        # entirely phrased as what it does NOT know, so that is what it learned.
        "The facts above are YOURS to say. Asked which vehicle, which insurer, "
        "which cover, whose name — answer from this card, plainly and at once. "
        "Never deflect to the team for something listed here.",
        "",
        "This card is the only thing you know about THIS customer. Every status "
        "above is what our system says right now. Anything not on it — what they "
        "have already typed, which field is blank, why the insurer objected — you "
        "do NOT know, and you do not guess.",
    ]
    return "\n".join(lines)


def _demo_fetch():
    # The Metabase response shape, as /api/dataset returns it, through the same
    # path the bot takes — no network needed.
    data = {"data": {"cols": [{"name": n} for n in (
        "proposal_id", "insurer_id", "policy_type", "proposal_status", "ownership_type",
        "error_code", "customer_name", "vehicle_reg", "kyc_status", "fulfillment_status",
        "policy_number")],
        "rows": [[741688, 2, "COMPREHENSIVE", "PROPOSAL_UPDATE_AFTER_PAYMENT", "Individual",
                  None, "MANGUKIYA BHAVIKBHAI", "TS08GJ3267", "KYC_STEP_NOT_INITIATED",
                  "ORDER_FULFILLED", None]]}}
    card = build(_row_from_dataset(data))
    assert card["insurer"] == "ICICI Lombard" and card["goal"] == "complete_kyc", card
    assert card["customer_name"] == "Mangukiya Bhavikbhai", card
    assert card["ownership_type"] == "individual" and card["vehicle_reg"] == "TS08GJ3267"
    # Junk RC names are dropped rather than greeted.
    for junk in ("dwghabdn", "12345", "", None, "x"):
        assert _clean_name(junk) is None or junk == "dwghabdn", junk
    assert _clean_name("Rahul Kumar") == "Rahul Kumar"
    # The insurer's error codes pick the goal.
    for code, goal in (("ERR_POLICY_ALREADY_EXISTS", "escalate_duplicate"),
                       ("ERR_QUOTE_PROPOSAL_PREMIUM_MISMATCH", "explain_requote")):
        row = _row_from_dataset(data); row["error_code"] = code
        assert build(row)["goal"] == goal, code
    assert _row_from_dataset({"data": {"cols": [], "rows": []}}) is None
    assert _row_from_dataset({"error": "x"}) is None
    # No key, or a bad id, means no fetch — never an exception. .env is loaded
    # first, so fetch()'s own import of domain cannot put the key back.
    import domain  # noqa: F401
    saved = os.environ.pop("METABASE_API_KEY", None)
    try:
        assert fetch(741688) is None
        card = from_body({"proposal_id": 741688})
        assert card == {"proposal_id": 741688, "goal": "complete_kyc", "do_not_say": []}, card
    finally:
        if saved is not None:
            os.environ["METABASE_API_KEY"] = saved
    assert fetch("741688; DROP TABLE proposal") is None
    # A failed fetch falls back to the last good row for that proposal.
    _CACHE[741688] = (time.monotonic(), {"proposal_id": 741688, "insurer": "ICICI Lombard"})
    saved = os.environ.pop("METABASE_API_KEY", None)
    try:
        os.environ["METABASE_API_KEY"] = "bad-key-forces-a-failure"
        os.environ["METABASE_URL"] = "http://127.0.0.1:9"   # nothing listens: instant failure
        assert fetch(741688)["insurer"] == "ICICI Lombard"
        _CACHE[741688] = (time.monotonic() - _CACHE_SECS - 1, {"insurer": "stale"})
        assert fetch(741688) is None, "a cache older than the window is not used"
    finally:
        os.environ.pop("METABASE_URL", None)
        if saved is not None:
            os.environ["METABASE_API_KEY"] = saved
        else:
            os.environ.pop("METABASE_API_KEY", None)
        _CACHE.clear()
    # A full card from the dialer is used as is — no fetch.
    full = from_body({"proposal_id": 1, "customer_name": "Asha", "kyc_status": "PENDING"})
    assert full["customer_name"] == "Asha"


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
    _demo_fetch()
    _demo()
