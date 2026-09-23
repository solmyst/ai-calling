# Domains

One voice pipeline, one folder per business. `DOMAIN=<folder>` in
`voicebot/server/.env` picks which one a process runs.

```
voicebot/server/bot.py   the pipeline: transport, STT, LLM failover, TTS, logging,
                         idle handling, and the tools every call needs
                         (escalate_to_human, end_call)
guardrails.py            output rules every domain shares — model failures, not
                         business rules (JSON read aloud, "I am an AI", thinking
                         out loud, speaker labels, wrong script)
domain.py                the seam: loads the active domain's pieces below

domains/car_spa/         Park+ car wash booking
domains/insurance/       post-payment motor insurance KYC (Shreya)
```

## What a domain folder contains

| File | Required | What it is |
|---|---|---|
| `context.json` | yes | The facts the bot may state. Prompt and guard both read it. |
| `prompt.py` | yes | `build_system_prompt(mode, card)`; optionally `opening_line(mode, card)` for a greeting spoken without an LLM call. |
| `guard.py` | yes | `GUARD` — deterministic rewrite of every sentence before TTS, with a `COUNTERS` table of what to log. The domain's own never-say rules live here. |
| `tools.py` | no | `TOOLS` — the domain's own LLM tools, registered beside the shared ones. |
| `call_card.py` | no | `from_body(body)` — the per-call case the dialer prefetches. |
| `knowledge/` | no | Source documents the context was built from. Never read at runtime. |

A missing required file fails at startup with the list of domains that exist.
There is no fallback guard: a new domain ships its own or does not start.

## Self-checks

```bash
DOMAIN=insurance ./venv/bin/python -m domains.insurance.guard
DOMAIN=insurance ./venv/bin/python -m domains.insurance.prompt
DOMAIN=car_spa   ./venv/bin/python -m domains.car_spa.guard
DOMAIN=car_spa   ./venv/bin/python -m domains.car_spa.prompt
./venv/bin/python guardrails.py
```
