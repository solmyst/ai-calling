---
doc_id: operations-insurer-kyc-proposal-field-matrix
service: insurance
doc_type: operations
status: draft
kb_created_date: 2026-09-18
last_updated: 2026-09-18
last_verified: 2026-09-18
owner: unassigned-calling-operations
audience: [calling-team, product, engineering, operations]
evidence_type: internal-ops-matrix-screenshot
source_refs: [ai-calling-kyc-field-matrix-2026-09-18]
summary: "Canonical insurer-by-field KYC/proposal requirements used by the AI calling agent."
---

# Insurer KYC / proposal user-field matrix

## Summary

- Lists which user fields each insurer label requires to complete KYC/proposal after payment.
- Universal fields vs insurer-specific deltas (HDFC-heavy, ICICI Aadhaar number, AIG CIN, etc.).
- Machine copy lives in `data/ai-calling/kyc-proposal-field-graph.json`; this page is the factual Markdown source.

## Scope and confidence

- **Scope:** post-payment KYC and proposal data completion for motor insurance journeys assisted by AI calling.
- **Evidence:** internal matrix screenshot recorded 2026-09-18 — see [[ai-calling-kyc-field-matrix-2026-09-18]].
- **Status:** `draft` until verified against live adapters and owning product/ops.
- **Label note:** matrix uses short labels (AIG, ICICI, HDFC, United, Bajaj, Digit, NIC, Kotak). Resolve numeric `insurer_id` via [[insurer-id-registry]]. Kotak is **unmapped** in the current `1`–`9` registry.

## Universal (all 8 labels)

| Field | Collection channel |
| --- | --- |
| Name | Voice allowed |
| Mobile | Voice allowed (prefer confirm existing) |
| Email | Voice allowed |
| Aadhaar images | **Approved upload only** — never on the call |
| Nominee | Voice allowed |

## Almost universal (all except NIC)

| Field |
| --- |
| DOB |
| Gender |
| Correspondence address |
| Correspondence pincode |

## Full matrix

| User field | AIG | ICICI | HDFC | United | Bajaj | Digit | NIC | Kotak |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Name | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Mobile | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Email | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| DOB | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ |
| Gender | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ |
| Correspondence address | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ |
| Correspondence pincode | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ |
| Correspondence city/state | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Permanent address | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| PAN | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✓ |
| Aadhaar number | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Aadhaar images | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| GSTIN | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✓ |
| PEP | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✓ |
| Indian | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Profile photo | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| CIN | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Nominee | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

## Entity-specific deltas (quick scan)

- **PAN:** AIG, ICICI, HDFC, Kotak
- **GSTIN:** ICICI, HDFC, Kotak
- **PEP:** HDFC, Kotak
- **Aadhaar number:** ICICI only
- **CIN:** AIG only
- **HDFC-only:** correspondence city/state, permanent address, Indian nationality flag, profile photo

## Backend ID hints

| Matrix label | Typical `insurer_id` | Notes |
| --- | ---: | --- |
| AIG | 1 | Direct AIG |
| ICICI | 2 | Direct ICICI |
| HDFC | 3 | Direct HDFC |
| United | 6 | Operationally UIIC / TurtleFin — confirm string code |
| Bajaj | 7 | TurtleFin |
| Digit | 5 or 8 | Dual routes — use live case adapter evidence |
| NIC | 4 or 9 | Dual routes — use live case adapter evidence |
| Kotak | — | **Unmapped** in registry; do not invent an ID |

## Agent usage rule

1. Resolve insurer from live case (`insurer_id` preferred).
2. Load required fields from this matrix / runtime JSON.
3. Subtract fields already present and verified in the case payload.
4. Collect voice-allowed gaps; hand off upload-only fields to the approved digital path.
5. Confirm completion from system state, not verbal confirmation alone.

See [[ai-calling-runtime-context]] and [[privacy-and-log-handling]].

## Related topics

- [[operations/ai-calling/index]]
- [[kyc-and-break-in-inspection-recovery]]
- [[insurer-post-payment-matrix]]
- [[insurer-id-registry]]
- [[ckyc-log]]
