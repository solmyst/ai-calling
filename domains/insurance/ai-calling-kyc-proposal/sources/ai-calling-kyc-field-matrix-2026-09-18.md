---
source_id: ai-calling-kyc-field-matrix-2026-09-18
service: insurance
doc_type: source
status: draft
kb_created_date: 2026-09-18
last_updated: 2026-09-18
last_verified: 2026-09-18
owner: unassigned-calling-operations
audience: [calling-team, product, engineering, operations]
source_type: screenshot
reliability: internal-draft
evidence_type: internal-ops-matrix-screenshot
summary: "Internal insurer KYC/proposal user-field requirement matrix used to seed the AI calling field graph."
---

# Source — AI calling KYC/proposal field matrix (2026-09-18)

## Summary

- Captures an internal comparison of user fields required by AIG, ICICI, HDFC, United, Bajaj, Digit, NIC, and Kotak for KYC/proposal completion.
- Seeds [[insurer-kyc-proposal-field-matrix]] and the runtime graph `data/ai-calling/kyc-proposal-field-graph.json`.
- Remains draft until verified against live insurer adapters and owning product/ops review.

## What this source is

An operations/product spreadsheet-style matrix (screenshot) showing green check / red X per user field per insurer label.

## What it is not

- Not a regulatory citation.
- Not proof of current production adapter behavior for every route (especially Digit/NIC dual routes and Kotak).
- Not authorization to log raw Aadhaar/PAN or collect identity images on a voice call.

## Derived artifacts

- [[insurer-kyc-proposal-field-matrix]]
- `insurance/data/ai-calling/kyc-proposal-field-graph.json`
- [[ai-kyc-proposal-calling]] prompt pack

## Related topics

- [[insurer-id-registry]]
- [[kyc-and-break-in-inspection-recovery]]
- [[privacy-and-log-handling]]
