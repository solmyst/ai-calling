# AI Calling — KYC & Proposal context pack

Standalone copy for the Park+ post-payment AI voice calling assistant.

## Use in the voice agent

1. Load `prompts/ai-kyc-proposal-calling.md` as the system prompt.
2. Load `data/kyc-proposal-field-graph.json` as the runtime field graph.
3. Inject per-case boot data: proposal_id, insurer_id/label, present fields, upload path.

## Contents

| Path | What |
|------|------|
| `data/kyc-proposal-field-graph.json` | Machine knowledge graph (insurers, fields, matrix, call phases) |
| `operations/index.md` | Pack index |
| `operations/insurer-kyc-proposal-field-matrix.md` | Human-readable field matrix |
| `operations/ai-calling-runtime-context.md` | Boot / phases / safety |
| `prompts/ai-kyc-proposal-calling.md` | Voice-agent system prompt |
| `sources/ai-calling-kyc-field-matrix-2026-09-18.md` | Source record for the matrix |

## Canonical source (repo)

These files were copied from:

`/Users/anushgupta/parkplus-deepagent/knowledge/insurance/`

Edit the repo copies when updating the knowledge base, then re-copy here if you want this folder refreshed.

Created: 2026-09-18
