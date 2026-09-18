---
doc_id: operations-ai-calling-runtime-context
service: insurance
doc_type: operations
status: draft
kb_created_date: 2026-09-18
last_updated: 2026-09-18
last_verified: 2026-09-18
owner: unassigned-calling-operations
audience: [calling-team, product, engineering, operations]
evidence_type: internal-draft
summary: "Runtime boot, field-resolution, call-phase, and safety contract for the post-payment AI KYC/proposal calling agent."
---

# AI calling runtime context

## Summary

- Defines how the voice agent boots a case, computes missing KYC/proposal fields, and progresses call phases.
- Separates voice-collectable fields from upload-only documents.
- Requires live system verification before closing a recovery attempt.

## Agent goal

After successful payment, help the customer complete **KYC** and **proposal** data so the journey can continue toward policy issuance (or a correctly escalated blocked state). This agent does **not** invent insurer rules, issue policies, process refunds, or collect identity documents on the call.

## Boot payload (minimum)

Before speaking, the runtime should supply:

| Field | Why |
| --- | --- |
| `proposal_id` | Case anchor |
| `insurer_id` and/or matrix label | Field set selection |
| Journey / KYC / proposal status | What is actually blocked |
| Already-known field map | Skip re-asking verified data |
| Approved upload/continuation path | For Aadhaar images / profile photo |
| Contact consent / DNC flags | Whether the call may proceed |

If live tools (Metabase / case API) are available, prefer them over static assumptions. Wiki SOP remains authority for process; live rows are authority for “what is true now.” See [[mcp-diagnostic-contract]].

## Field resolution algorithm

1. Map `insurer_id` → matrix insurer via [[insurer-id-registry]] + [[insurer-kyc-proposal-field-matrix]].
2. `required = requirement_matrix[insurer]`.
3. `missing = required − present_and_verified`.
4. Split:
   - `voice_collect_now` — channel `voice_allowed*`
   - `upload_only` — Aadhaar images, HDFC profile photo
5. If insurer unmapped (e.g. Kotak without registry ID): collect only **universal** fields, state the gap, escalate for confirmed checklist.

Runtime encoding: `insurance/data/ai-calling/kyc-proposal-field-graph.json`.

## Call phases

1. **consent_and_purpose** — identify Park+ Insurance calling context; state post-payment KYC/proposal purpose; get consent.
2. **resolve_missing_fields** — compute checklist silently; do not dump the full matrix to the customer.
3. **collect_voice_fields** — ask one field (or tight group) at a time; read back critical values.
4. **hand_off_uploads** — guide approved app/WhatsApp/KYC link; never accept images/OTP on the call.
5. **verify_system_state** — check CKYC/proposal/journey evidence; verbal “done” is insufficient.
6. **disposition_and_next_action** — privacy-safe disposition, callback, or escalation.

Recommended voice order is in the JSON graph under `call_phases.collect_voice_fields.recommended_order`.

## Speech / UX constraints

- One job per turn: ask or confirm, not both plus a long explanation.
- Spell-back email, PAN, pincode, and Aadhaar number when collected.
- If customer refuses a required field, mark blocked + reason; do not invent a workaround.
- If customer asks policy/coverage questions beyond this flow, stay brief and return to completion, or hand off per [[operations/insurance-calling/index]].

## Safety hard rules

Copied for runtime; full privacy policy in [[privacy-and-log-handling]]:

- No OTP collection.
- No Aadhaar/profile images on the voice channel.
- No raw Aadhaar/PAN in unrestricted logs, tickets, or wiki.
- No completion from verbal confirmation alone.
- No promises of issuance timing or refund approval.
- Prefer live evidence when it conflicts with this draft matrix; flag the conflict.

## Success criteria

A call attempt is successful when:

1. All voice-required missing fields for that insurer are collected and submitted through the approved write path, **and**
2. Upload-only items are either already verified or the customer has been correctly handed to the approved upload path with a scheduled verify/callback, **and**
3. System state shows progression or a documented remaining blocker.

## Related topics

- [[operations/ai-calling/index]]
- [[insurer-kyc-proposal-field-matrix]]
- [[kyc-and-break-in-inspection-recovery]]
- [[journey-status-state-machine]]
- [[insurance-calling-reasons-and-dispositions]]
