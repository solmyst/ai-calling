# The call card — what the dialer sends the bot

One fixed query before the phone rings. The voice agent never touches the
database: it does not compose SQL mid-call, does not wait on Metabase while a
customer listens to silence, and never sees `error_details`, a chassis number or
a payment reference.

`call_card.py` is the enforcement, not this document. Read that if the two ever
disagree.

## Passing it

The card rides in on Pipecat's per-session runner body.

```bash
python bot.py --runner-body /tmp/card-845671.json      # a PATH, not inline JSON
```

```json
{ "call_card": { "proposal_id": 845671, "kyc_status": "PENDING", "...": "..." } }
```

A bare object (no `call_card` wrapper) works too, as does a JSON string. In an
eval manifest it is `runner_body: cards/duplicate.json`.

**No card is a supported state.** If the prefetch fails, times out, or the
dialer has not been updated, the bot runs exactly the generic call it ran
before any of this existed. Never block a dial on the card.

## What you send

Send the prefetch row. Keys outside the whitelist in `call_card.FIELDS` are
dropped on the way in, so sending the whole row is safe — and is the point:
a column added to the query next month cannot quietly become something the bot
says down a phone line.

| Field | Used for |
|---|---|
| `customer_name` | Greeting. Missing → the bot greets generically. |
| `insurer` | Which KYC path, and it can answer "किस company का insurance है?" |
| `policy_type` | Wording only. |
| `vehicle_reg` | Confirms the right case out loud. |
| `ownership_type` | **`individual` or `company`.** See below — this one matters. |
| `prev_policy_expiry` | Urgency. |
| `proposal_status`, `kyc_status`, `fulfillment_status` | Goal derivation. |
| `policy_number` | Present ⇒ issued ⇒ nothing is pending. |
| `blocker` | One short human sentence. Identifiers are stripped, then capped at 160 chars. |
| `do_not_say` | Hard stop. The guard replaces any sentence containing one of these. |

Also read, never shown to the model: `error_code` (picks the goal),
`paid_amount` and `paid_or_expected_premium` (a mismatch over ₹1 picks the
goal).

Deliberately **not** in the whitelist: `error_message_short`, chassis and engine
numbers, payment and audit transaction ids, raw `error_details`, premium
figures. The bot quoting money it cannot verify is how a call becomes a refund
dispute.

## `do_not_say`

Codes and identifiers only — `["IERR_DUPLICATE_POLICY", "audit log"]`. It is a
sentence-level kill switch, so an ordinary word like `"policy"` would silence
half the call. The prompt shows the list as well; the guard is the backstop for
when the model ignores it.

## The goal

Derived from the row by `derive_goal()`, most decisive rule first. Send your own
`goal` to override; a free-text `call_goal` is shown to the model as context but
never drives the branch.

| Condition | Goal | What the bot does |
|---|---|---|
| `policy_number` present | `confirm_issued` | Congratulates, closes. No KYC ask. |
| `error_code = IERR_DUPLICATE_POLICY` | `escalate_duplicate` | Explains, escalates. Takes nothing. |
| paid ≠ premium by more than ₹1 | `explain_requote` | Explains, no collection. |
| `kyc_status = SUCCESS`, proposal not successful | `explain_blocker` | Explains the blocker. **Never re-asks for KYC.** |
| otherwise | `complete_kyc` | The full app walkthrough. |

Only `complete_kyc` gets the walkthrough prompt. Every other goal gets
`SHORT_CALL_TEMPLATE` — no screens, no forms, nothing for the customer to do —
because handing a "your policy is already issued" call a form guide is how
twenty seconds becomes five minutes.

## What the card unlocks in the guard

The guard normally rewrites any claim that KYC is complete, because the bot
cannot see the system. The safety rule is *"never mark KYC complete from **verbal
confirmation** alone"* — and a prefetched card is not verbal confirmation, it is
our own system. So when the card says `kyc_status: SUCCESS` or carries a
`policy_number`, the bot may say so. Without a card, or with a pending one, it
still cannot. Every other rule — OTP, Aadhaar by voice, WhatsApp, invented
regulators, promising to send a link — is unaffected.

## Still open

- **`ownership_type` has no source yet.** Individual/private ⇒ PAN + Aadhaar
  number + Aadhaar front and back. Company-owned ⇒ PAN + PAN photo + GST
  certificate, and **no Aadhaar at all**. The card carries the field and the
  prompt renders it; the prefetch query does not select it. Until it does, the
  bot has to ask the customer which it is — which is the field-recitation this
  whole design exists to avoid. Likely somewhere in `p.car_ownership_details`.

- **The card is fetched once, before dialling, and the customer completes KYC
  *during* the call.** Harmless today: the bot never claims completion, so a
  stale `PENDING` costs nothing. It matters the day you want the closing turn to
  confirm. That is the `get_call_card(proposal_id)` refresh tool — one fixed
  tool, never free-form SQL.

- **`prev_policy_expiry` is the PREVIOUS policy's date.** `context.json`'s
  `kyc_mandate.deadline` says KYC can be done any time before *the policy*
  expires. Confirm which policy that means before the bot says a date out loud;
  right now it says no date at all, which is safe.
