---
doc_id: operations-ai-calling-index
service: insurance
doc_type: operations
status: draft
kb_created_date: 2026-09-18
last_updated: 2026-09-18
last_verified: 2026-09-18
owner: unassigned-calling-operations
audience: [calling-team, product, engineering, operations]
evidence_type: internal-draft
summary: "Index for the post-payment AI voice calling agent context pack for KYC and proposal completion."
---

# AI calling — post-payment KYC & proposal pack

## Summary

- Runtime context for an AI voice agent that helps customers finish KYC and proposal after payment.
- Machine field graph plus canonical matrix, call phases, and safety rules.
- Consumed by the voice-agent prompt in [[ai-kyc-proposal-calling]]; does not replace human Insurance Calling SOPs.

## Pack contents

| Artifact | Role |
| --- | --- |
| `insurance/data/ai-calling/kyc-proposal-field-graph.json` | **Runtime graph** — insurers, fields, requirement matrix, call phases, safety rules |
| [[insurer-kyc-proposal-field-matrix]] | Canonical human-readable field matrix |
| [[ai-calling-runtime-context]] | How the agent boots, resolves missing fields, and closes a call |
| [[prompts/ai-kyc-proposal-calling]] | Copy-paste / system prompt for the voice agent |
| [[ai-calling-kyc-field-matrix-2026-09-18]] | Source record for the matrix screenshot |

## When to use this pack

- Building or running the **AI calling assistant** for post-payment KYC/proposal completion.
- Answering “which fields does insurer X need?” for the supported label set.
- Generating a per-case collection checklist from `insurer_id` / insurer label + already-present fields.

## When not to use this pack alone

- Live case status / failure diagnosis → start at [[proposal-id-routing-protocol]] and Metabase per [[mcp-diagnostic-contract]].
- Break-in inspection recovery → [[kyc-and-break-in-inspection-recovery]].
- Human calling dispositions / handoffs → [[operations/insurance-calling/index]].

## Related topics

- [[insurer-id-registry]]
- [[insurer-post-payment-matrix]]
- [[journey-status-state-machine]]
- [[privacy-and-log-handling]]
- [[manual-calling-dependency-kyc-inspection]]
