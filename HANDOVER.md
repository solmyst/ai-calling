# Handover — Park+ insurance KYC voice bot

Written 2026-09-21. For whoever picks this up next.

Read this before touching anything. Most of what follows was learned from live
calls that went wrong, and the reasons are not obvious from the code.

---

## What this is

A Hindi/Hinglish outbound voice bot. It rings Park+ customers who have **paid**
for motor insurance but whose KYC is incomplete, and talks them through
finishing it in the Park+ app. It never collects identity on the call.

Pipecat 1.10 cascade pipeline:

```
transport.input() → AssemblyAI STT → NoiseGate → user_aggregator
                  → Gemini (via Bifrost, Park+ fallback) → Sarvam TTS
                  → transport.output() → assistant_aggregator
```

One pipeline, several businesses. Everything business-specific is in
`domains/<name>/`; everything else is in `voicebot/`. `DOMAIN=insurance` in
`.env` selects it. **Insurance is the priority — do not spend time on car spa.**

## Where the important code is

| | |
|---|---|
| `voicebot/server/bot.py` | the whole pipeline, transports, failover, STT/TTS config |
| `domains/insurance/prompt.py` | system prompt, built from context.json |
| `domains/insurance/context.json` | every fact the bot may state. Single source of truth |
| `domains/insurance/guard.py` | 14 deterministic output rules. The prompt is advice; this is not |
| `domains/insurance/call_card.py` | per-call data from the dialer. See `CALL_CARD.md` |
| `guardrails.py` | car spa's guard **and** the rules both domains share |
| `voicebot/server/evals/` | behavioural scenarios + the guard fuzzer |

## Run the offline checks — all of these, before and after any change

They cost nothing and every one of them has caught a real bug.

```bash
DOMAIN=insurance ./venv/bin/python -m domains.insurance.guard
DOMAIN=insurance ./venv/bin/python -m domains.insurance.prompt
DOMAIN=insurance ./venv/bin/python -m domains.insurance.call_card
cd voicebot/server && DOMAIN=insurance ../../venv/bin/python test_noise_gate.py
DOMAIN=car_spa ./venv/bin/python guardrails.py     # needs its own DOMAIN
./venv/bin/python redaction.py
```

The behavioural suite needs LLM credit (see Blockers):

```bash
cd voicebot/server/evals
DOMAIN=insurance PYTHONPATH=. ../../../venv/bin/pipecat eval suite suite_insurance.yaml
```

---

## THE TASK: telephony + a hangup path

Today this bot is **browser-only**. `bot.py` registers `webrtc` and `eval` and
nothing else, so a carrier that connects gets
`ValueError: Missing transport params`. There is also no way for the bot to end
a call. Both need to exist before any real call happens.

### 1. Register a telephony transport

`bot.py` ~line 1441:

```python
transport_params = {
    "webrtc": lambda: TransportParams(...),
    "eval":   lambda: EvalTransportParams(...),
}
```

Pipecat's `create_transport` already knows `daily`, `twilio`, `telnyx`,
`plivo`, **`exotel`**, `livekit`, `websocket`, `vonage`, `moq`
(`venv/.../pipecat/runner/utils.py`). Add the key and the serializer is wired
for you.

**Use Plivo.** Researched 2026-09-21:

- **Twilio is out entirely.** Their own India guidelines bar domestic outbound
  calling within India — calls to Indian numbers must originate from non-Indian
  numbers as international traffic. Not viable here.
- **Plivo** publishes ₹0.38/min domestic, ₹200/month number rental, no platform
  fee, $10 trial credit. Its docs list "160-series — service and transactional,
  BFSI sector only" as a number type it provisions, and **AudioStream is
  confirmed bidirectional** (`keepCallAlive="true"`), which is what Pipecat
  needs. μ-law 8kHz is the native telephony codec.
- **Exotel** is the fallback: AgentStream is also confirmed bidirectional, but
  pricing is quote-only with a ₹4,999–10,499 setup fee, reported ₹0.60–1.50/min,
  and **reportedly bills on a 30s or 60s pulse rather than per-second** — on
  short KYC calls that matters more than the headline rate. Ask for the pulse in
  writing before modelling anything.

Ask Plivo in writing whether AudioStream is genuinely ₹0 and what the billing
pulse is. Their page is silent on streaming cost, which is consistent with free
but is an absence, not a published zero.

Also needed:
- the Pipecat extra in `voicebot/server/pyproject.toml` (see the dependency
  blocker — that file is already wrong today)
- a public HTTPS host; `run.py` binds `localhost:7860`
- the provider's stream config pointed at it

### 2. The greeting will not fire on a phone call — fix this at the same time

This one will waste your afternoon if you hit it cold. `bot.py` ~1398:

```python
@worker.rtvi.event_handler("on_client_ready")
async def on_client_ready(rtvi): ...
```

`on_client_ready` is an **RTVI** event. It fires when a browser client sends
`client-ready`. A Twilio/Exotel media-stream websocket sends no RTVI frames at
all, so **the bot will answer the leg and then sit in silence** until the
customer speaks first.

Fix: pull the greeting body into a function and call it from both
`on_client_ready` and the existing `on_client_connected`
(`bot.py` ~1419, transport-level, fires on every transport). The `greeted` flag
right above already dedupes, and `on_client_disconnected` already resets it —
keep both, they exist for reasons written in the comments there.

### 3. Give the bot a way to hang up

Today the only exit is the remote side disconnecting (`on_client_disconnected`
→ `runner.cancel()`). On PSTN, a customer who sets the handset down without
hanging up holds a **billed** line open until the carrier times it out.

`EndWorkerFrame` exists in this Pipecat version — verified. The pattern from
`voicebot/AGENTS.md` §4:

```python
async def end_call(params: FunctionCallParams):
    """End the call once the goodbye is said."""
    await params.result_callback({"success": True})
    await params.llm.push_frame(EndWorkerFrame())   # downstream: queued audio flushes first
```

Do **not** use `EndTaskFrame` (deprecated) and do not invent a shutdown path.

Two catches:
- **`LLM_TOOLS=off` in `.env`** disables all tools, so a tool-based hangup will
  not work as configured. It is off because Park+'s vLLM was launched without
  `--enable-auto-tool-choice` and 400s any request carrying tools. Either turn
  tools back on (needs Bifrost healthy, which is a Gemini endpoint and does
  support them), or trigger the hangup without a tool.
- Add a **max call duration** and a **silence watchdog** regardless. Neither
  exists, and a tool the model forgets to call is not a safety net.

### 4. While you are in there: nothing recovers from a failure

There is no `on_pipeline_error` handler and `processor_unusable_policy`
defaults to `CONTINUE`. If the LLM exhausts every endpoint, or the TTS or STT
websocket dies for good, **the pipeline stays alive and mute and the line stays
open**. That has already happened once here, on the day the Bifrost key hit its
cap. A hangup path is what makes that survivable, which is why it belongs in
this task and not a later one.

---

## BLOCKERS — real calls cannot happen until these clear

These are not engineering tasks. Escalate them today; some have weeks of lead
time.

### Legal

1. **1600-series CLI — and we probably cannot hold it.** IRDAI Circular
   IRDAI/PP&GR/CIR/MISC/02/01/2026 (6 Jan 2026): insurers and insurance
   intermediaries may make **no** service or transactional voice call from any
   number other than a 1600-series CLI after **15 Feb 2026**, *regardless of
   consent*. That date passed seven months ago.

   DoT reserved the series; **the telco allocates it** (Airtel/Jio/Vi/BSNL/Tata),
   circle-wise, from a small pool — 485 entities and ~2,800 numbers nationwide as
   of mid-2026. Eligibility is limited to entities regulated by RBI, SEBI, IRDAI
   or PFRDA, and TRAI's stated design principle for the sibling 1601 series is
   that numbers go **"directly to eligible entities, and not to intermediaries or
   aggregators."**

   So the number sits with the **IRDAI-registered insurer or intermediary**, not
   with a technology vendor. A CPaaS can be the routing leg against the insurer's
   registration; it cannot hold the entitlement. **This is the one unresolved
   legal question — get the insurer's compliance head to put it to their TSP
   enterprise account manager in writing.**

   Documents: company registration, PAN, GSTIN, signatory KYC, **IRDAI
   registration certificate**, an undertaking to use it only for
   service/transactional calls, and DLT Principal Entity registration.
   **Start at least 8 weeks before you need to dial.** Number price is
   quote-only — no telco publishes it.

   Penalty: up to ₹10 lakh per violation plus blacklisting of all telecom
   resources for up to a year.
2. **A2P pre-declaration.** TCCCPR Third Amendment, notified 18 Sept 2026:
   every entity using automated calling must pre-declare the usage and its CLIs
   to its telecom provider. Undeclared automated traffic is spam by definition.
3. **Script must disclose the call is recorded, and the caller's identity**
   (IRDAI Distance Marketing Guidelines). The prompt currently does neither.
4. **Zero promotional content.** One cross-sell line converts the call from
   "service" to "promotional" and forfeits the DND/NCPR exemption entirely,
   which then requires full scrubbing and explicit consent.
5. **DLT template registration — read this before promising anything.**
   Principal Entity registration is ₹5,900 incl. GST, 3–7 working days; content
   templates are free but take 3–7 days, realistically 2–3 weeks for a first-time
   entity. The insurer registers as PE, not us.

   **The hard part: every outbound voice script the bot can use must be
   registered as a template**, tagged transactional/service/promotional, with
   language and an exemplar script. A free-form generative agent does not
   obviously map onto a registered template, and nobody has resolved how a
   per-turn LLM output satisfies that. This is a product-design question, not a
   paperwork one, and it is the item most likely to force a rethink of how much
   the model is allowed to improvise. Raise it early.

**AI disclosure is NOT required** by any current Indian law, TRAI regulation or
IRDAI circular — this was researched specifically. The product owner's
instruction to stop saying "AI assistant" is fine. TRAI has said it is
*considering* adding such a rule, so this answer has an expiry date.

The bot must still **never claim to be a person** — that is enforced in
`guardrails.py` (`_CLAIMS_HUMAN_RE`), and it is the line that keeps "not
announcing" from becoming impersonation. Do not remove it.

### Money — currently stops you at ~14 calls

| | limit | calls |
|---|---|---|
| Sarvam TTS | ₹100 free credits | **~14** |
| Bifrost LLM | $10 virtual-key cap | ~133 |
| AssemblyAI | 5 new sessions/min on free tier | 300/hr ceiling |

All-in **₹15.60 per 3-minute call** (TTS 45%, LLM 42%, STT 13%).
500 calls ≈ ₹7,800. Both the Sarvam credit and the Bifrost cap have already
been hit once each during development.

The Bifrost cap is also why the behavioural suite cannot run. `BIFROST_EVAL_VK`
exists so the harness gets its own key and its own cap — set it, or evals will
keep taking production down with them.

### Also missing before production

- **No dialer.** Nothing in this repo initiates a call. The bot only answers a
  connection someone else opened. `CALL_MODE=outbound` only changes the script.
- **`pyproject.toml` cannot install this bot.** It declares
  `pipecat-ai[piper,runner,silero,webrtc,whisper]` but `bot.py` imports the
  assemblyai, sarvam, elevenlabs, groq and ollama services plus openai and
  python-dotenv. A clean `uv sync` produces a box that ImportErrors on startup.
  It runs today only because `./venv` happens to hold the right packages. No
  lock file either.
- **No deploy artifact of any kind** — no Dockerfile, no compose, no process
  manager, no restart-on-crash.
- **`LLM_TOOLS=off` means zero lead capture and zero human handover.**
  `record_booking_request` and `escalate_to_human` are the only structured
  output and the only route to a person, and both are disabled.
- **Observability is one text file.** `call.log`, no call id, rotation at 5 MB
  keeping 3 files. 500 calls interleave unattributably and the earliest are
  silently discarded. `runner_args.session_id` is available and unused.

---

## State of the work

**In good shape.** The conversation itself is where the effort went:

- The prompt is built from `context.json` and asserts its own contents. Facts
  come from the product owner and from screenshots of the real app.
- 14 deterministic guard rules, hardened over five rounds of LLM fuzzing
  (`evals/fuzz_guard.py`). That fuzzer found eight rules firing on sentences the
  bot *should* be allowed to say — including "KYC complete karna hai", the core
  ask of the whole call.
- Per-case call cards with a field whitelist, so a column added to the dialer's
  query cannot become something the bot says out loud.
- 16 behavioural scenarios including two adaptive-caller simulations.

**Not verified.** The last real suite run was **2026-09-19**. Ten commits have
landed since — the AI-disclosure removal, four guard rules, the opening rewrite,
the AssemblyAI turn-detection switch, the Sarvam temperature fix, and today's
greeting fix. All of it is covered by offline self-checks only. `card_united`
(the HyperVerge flow) has **never** run. Re-run the suite as soon as there is
LLM credit.

---

## Things that will bite you

Learned the expensive way. Each of these was a live-call bug.

1. **The guard replaces whole sentences, not phrases.** A rule that matches one
   clause destroys the greeting, the name and the ask with it. That is exactly
   what happened today: the developer message still ordered the AI disclosure
   after it was removed from the prompts, and the new rule ate the entire first
   sentence of every call. Any new guard rule needs a must-block AND a must-pass
   list in `_demo()`.
2. **Run `fuzz_guard.py` after any guard change.** Hand-written cases only find
   failures you already imagined.
3. **The guard does NOT run in text-mode evals.** It is a TTS text filter and
   text mode asserts upstream of it. A green `kyc_safety` measures the prompt
   alone. Only the audio scenarios exercise the guard.
4. **`domain.py` loads `.env` itself.** Import it before reading `DOMAIN`
   anywhere, or you silently get `car_spa`.
5. **Never guess a model name.** `qwen/qwen3.6-27b` was invented from memory and
   killed a whole call. Check `GET /v1/models`.
6. **Prompt growth must be paid for by a deletion.** The ceiling in
   `prompt.py`'s `_demo()` is there to force that decision, not to hold a number.
7. **STT and TTS settings are documented in `.env.example`** with the reason for
   each value. Tune ONE at a time on a real call, reading `call.log`.
8. **`voicebot/README.md` claims a telephony provider connects to `/ws`.** That
   is scaffold boilerplate and is false. Fix it when you wire a real transport.

## Suggested order

1. ~~Telephony transport + the `on_client_connected` greeting fix + hangup path
   and a max-duration timer.~~ **Done 2026-09-21** — `exotel`/`plivo` in
   `transport_params`, shared `_greet_once`, `end_call` + `CALL_MAX_SECS` /
   `CALL_IDLE_SECS` + `ProcessorUnusablePolicy.END`. Still needs a public WSS
   host and a real Exotel/Plivo number before a live leg.
2. Fix `pyproject.toml` and add a lock file, or nothing deploys.
3. Top up Sarvam and Bifrost; set `BIFROST_EVAL_VK`; re-run the suite.
4. Add a call id and a per-call record before any volume.
5. The dialer, once the 1600-series question is answered.

A supervised pilot — a human dials from a compliant number and hands the audio
over, ten calls, watched — needs only step 1 and sidesteps the dialer entirely.
That is the realistic near-term milestone.
