# AI Calling — How It Works & Build Plan

*A practical build doc, not a theory doc. Goal: understand the stack, then ship an MVP with open source components.*

---

## 1. What "AI Calling" actually is

It's not IVR ("press 1 for billing"). It's a **real-time voice agent**: the AI listens continuously, understands intent, decides what to say, and speaks back — with natural interruption handling — over a phone line or web call.

Under the hood it's always the same loop, chaining independent AI models together in real time:

```
Caller speaks
   → Telephony layer (carries the audio)
      → STT — Speech-to-Text (audio → words)
         → LLM — reasoning (words → decision + response text)
            → TTS — Text-to-Speech (response text → audio)
               → Telephony layer (plays audio back)
```

The entire engineering problem is **latency stacking**. Each hop adds 100–300ms. Past ~700-800ms of dead air, a human perceives the call as broken. So the real skill in this space isn't "call an LLM" — it's keeping a 4-model chain fast, handling barge-in (user interrupts mid-sentence), and managing turn-taking, in real time, over an unreliable phone line.

### Components you need beyond the core loop
- **Turn detection / interruption handling** — stop the bot talking the instant the user speaks
- **Conversation state** — what's been said, what data's been extracted, when to end/transfer
- **Human handoff** — non-negotiable past FAQ-tier use cases
- **Compliance** — call recording disclosure, DND/consent registries (in India: TRAI DND + DLT registration for outbound — this trips up almost everyone who copies a US playbook)

---

## 2. The stack — your real decisions

Four independent choices. You can mix and match; nothing locks you in if you use an open framework.

| Layer | What it does | Notable options (2026) |
|---|---|---|
| **Orchestration framework** | Wires STT→LLM→TTS together, handles turn-taking/interruption/telephony transport | **Pipecat** (open source, Python, ~13k GitHub stars, widest provider library) · LiveKit Agents (open source, WebRTC-native, better at high concurrency) · Vapi/Retell (managed, not open source) |
| **STT** | Audio → text | Deepgram, AssemblyAI, OpenAI Whisper (open weights, self-hostable), Soniox |
| **LLM** | Decides what to say | GPT-4o-mini / GPT-realtime, Claude, open-weight models (Qwen, Llama) if self-hosting |
| **TTS** | Text → audio | **ElevenLabs** (best quality, low-latency "Flash" tier), Cartesia, Inworld TTS-2, Coqui/XTTS (open source, self-hostable, lower quality) |
| **Telephony** | Actual phone line / SIP | Twilio, Plivo, Telnyx, Daily (WebRTC) |

### Why Pipecat is the right call for you specifically
- Open source (Apache-2.0 style), Python-first — matches your engineering background
- 100+ provider integrations already wired in — **ElevenLabs is a one-line swap**, so you're not locked into any single vendor
- Self-hosted, so you own the data and the economics (no per-minute platform tax on top of your model costs)
- Has a managed hosting option (Pipecat Cloud) for when you want to stop operating infra and just ship — good escape hatch later
- Trade-off: no drag-and-drop builder, you write the orchestration logic. For an engineer building to understand the space, that's the point, not a downside.

**Alternative if you outgrow it:** LiveKit Agents — pick this if you need native multi-party calls, or hit concurrency past a few hundred simultaneous calls, since it's built directly on a WebRTC media server rather than sitting on top of one.

---

## 3. MVP architecture (recommended starting stack)

```
Twilio (telephony/SIP)
   → Pipecat (orchestration, self-hosted, Python)
      → Deepgram (STT — fast, cheap, good Indian-English support)
         → GPT-4o-mini or Claude Haiku (LLM — cheap, fast enough for chat-level reasoning)
            → ElevenLabs Flash (TTS — lowest-latency tier, good voice quality)
```

Why this combo: every piece is swappable independently, cost stays low while you validate, and latency is competitive (~500-700ms range achievable with this pairing per third-party benchmarks).

**Don't self-host the LLM or TTS models for the MVP.** Self-hosting buys you cost savings at scale, but adds infra ops (GPU provisioning, model serving) that will slow you down before you've even validated the idea. Swap to self-hosted later if unit economics demand it.

---

## 4. Build plan — phased

### Phase 0: Scope to one flow (1-2 days)
Pick **one narrow, well-defined call flow** — not a general-purpose assistant. Examples: "check order status," "book an appointment," "collect a payment reminder callback." Building broad first is the #1 way these projects stall.

### Phase 1: Local prototype (3-5 days)
- Set up Pipecat locally, wire Deepgram → GPT-4o-mini → ElevenLabs
- Test over WebRTC in browser first (skip telephony entirely) — cheaper to iterate, no phone number needed yet
- Nail the system prompt: strict scope, explicit "don't know" behavior, extraction of the 2-3 data points you actually need from the call

### Phase 2: Add telephony (2-3 days)
- Wire Twilio (or Plivo if cost-sensitive for India) as the SIP/PSTN layer
- Get a real phone number, make real test calls
- Build interruption handling and test it aggressively — talk over the bot on purpose, this is where most demos fall apart

### Phase 3: Guardrails (3-5 days)
- Human handoff trigger (keyword-based is fine for v1: "agent," "human," repeated confusion)
- Call logging + transcript storage for debugging and QA
- Basic consent/recording disclosure at call start (compliance, not optional)

### Phase 4: Pilot (1-2 weeks)
- Run it on a real, narrow use case with real users/customers
- Track: completion rate (did the call achieve its goal without human handoff), average handle time, latency (p50/p95), and where in the flow calls break

**Total to a real pilot: ~3-4 weeks**, working solo, given your background. That's aggressive but realistic for one flow.

---

## 5. Cost reality check (so you don't get surprised)

Rough per-minute cost at MVP stack (Deepgram + GPT-4o-mini + ElevenLabs Flash + Twilio):
- STT: ~$0.01-0.015/min
- LLM: ~$0.01-0.02/min (varies with context length)
- TTS: ~$0.02-0.05/min (ElevenLabs is priced per character, budget accordingly)
- Telephony: ~$0.01-0.02/min

**Ballpark: $0.06-0.12/min all-in** at low volume — comparable to what managed platforms charge, except you're not paying their margin on top, and you keep full control of the pipeline. This only wins economically once you're past pilot volume; at 10 test calls, don't optimize for cost, optimize for learning.

---

## 6. What "shipping to market" actually requires (beyond the tech)

Your prompt says "build to understand and ship" — worth being blunt: the tech above is now genuinely commoditized. Every platform in this space ships roughly the same STT→LLM→TTS loop. **Your differentiation has to be the vertical, not the pipeline.**

Questions to answer before calling this a product, not a prototype:
- **Who specifically has this problem and can't solve it with Retell/Vapi/Bland today?** (a narrow vertical, a regulatory requirement, a language/dialect gap, a data-residency constraint)
- **What's the wedge?** Given your Park+ context — Indian-language/Hinglish code-switching handling, DND/DLT compliance baked in, and India-specific telephony (Airtel/Jio SIP quirks, call quality on 2G/3G) are all gaps the big US platforms handle poorly. That's a real wedge, not a vague one.
- **Retention/usage model**: is this a per-call tool (low retention, commodity pricing pressure) or does it plug into a workflow (CRM, support desk, collections system) where switching cost is real?

If you can't answer "who can't get this from Retell/Vapi today," build it for the learning, not for the market — that's a fine reason to build it, just don't confuse a good learning project with a fundable product.

---

## 7. Edge cases you will hit (plan for these now, not after)

- Background noise / bad phone lines degrading STT accuracy
- Users speaking Hindi/English mid-sentence (code-switching) — test this explicitly, most STT/TTS stacks handle it worse than advertised
- Silence/no input handling (don't let the bot just hang)
- Call drops mid-flow — need to resume or gracefully fail, not just lose the interaction
- Regulatory: recorded-call disclosure, DND registry checks for outbound in India

---

## Sources
- Pipecat vs LiveKit Agents comparison — forasoft.com, soniox.com (July 2026)
- Open-source voice agent framework rankings — techsy.io (July 2026)
- Voice AI platform latency/pricing benchmarks — retellai.com, techsy.io, builts.ai (2026)
