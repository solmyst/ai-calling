# Park+ Car Spa AI Calling Bot — Context Pack & Stage 1 Build Spec

*This is the spec Codex builds from. Business data below is scraped from Park+ (Sept 2026) — verify against live pricing before any real customer-facing use, since offers/slots change.*

---

## 1. Business context (source of truth for the bot)

### Service area
- Doorstep car spa — technician comes to the customer's address (not a drive-in center)
- Primary city: **Gurugram (Gurgaon)**
- Availability depends on society/area coverage — bot should always confirm the customer's area/pincode before assuming service is available

### Services & pricing (INR)

| Package | Duration | Hatchback | Sedan | SUV/MUV |
|---|---|---|---|---|
| Full Car Spa Premium | 90 min | ₹479 (MRP ₹749) | ₹579 (MRP ₹849) | ₹679 (MRP ₹949) |
| Interior Only | 50 min | ₹500 (MRP ₹1000) | ₹604 (MRP ₹1208) | ₹780 (MRP ₹1560) |
| Exterior Only | 40 min | ₹319 (MRP ₹399) | ₹419 (MRP ₹499) | ₹489 (MRP ₹599) |

**What's included:**
- *Full Car Spa Premium*: foam wash, tyre cleaning & polish, exterior wax, glass cleaning, vacuum, leather seat cleaning, dashboard polish & wipe, cladding cleaning & polish, interior deep cleaning
- *Interior Only*: vacuum, leather seat cleaning, dashboard polish & wipe, interior deep cleaning
- *Exterior Only*: foam wash, tyre cleaning & polish, exterior wax, glass cleaning

**Subscription:** 6 Full Car Spa Premium washes + 1 free = **₹3,534** (vs ₹4,123 one-off), ~₹505/wash, valid **6 months**.

### Slots
- Typical windows (IST): **5:30 AM, 8:00 AM, 10:30 AM, 1:00 PM, 3:30 PM, 6:00 PM**
- Same-day slots can be priced higher than next-day
- Availability is area-dependent and time-of-day dependent — bot should never invent an available slot, only offer from what's actually confirmed as open (or, for MVP, say "let me note your preferred slot and confirm availability")

### Policies
- Reschedule: up to 3 times; free if ≥2 hours before slot start; ₹100 fee if within 2 hours
- **Cancellations are not permitted** — this is a policy customers will push back on; the bot needs a firm, polite way to hold this line
- Support: support@myparkplus.com

---

## 2. Guardrails (v1 — lead-capture mode, no live booking)

The bot's job: **understand the request, quote accurate info, and capture booking intent** for a human/system to confirm. It does not claim a booking is final.

| Rule | Why |
|---|---|
| Never say "your booking is confirmed" | No backend integration yet — false confirmation = broken trust on day one |
| Never invent a price, slot, or service not in the context above | Hallucinated info here directly costs the customer money/time |
| Never waive or negotiate the ₹100 reschedule fee or the no-cancellation policy | Not the bot's call to make exceptions |
| If asked about anything outside car spa (FASTag, challan, other Park+ services) | Say it's outside what this line handles, offer to note it for a callback — don't try to answer |
| If the customer's area/pincode isn't confirmed serviceable | Say so plainly, don't assume coverage |
| End of call (or end of intent capture) | Read back: service, vehicle type, price quoted, preferred slot, address/area, phone number — so the customer can correct any error before it's logged |
| Escalation triggers | Repeated confusion (2+ failed clarification attempts), explicit request for a human, complaint/anger, any question the bot can't answer from context above |
| Language | Respond naturally in whatever mix of Hindi/English the customer uses — don't force pure Hindi or pure English if they code-switch |
| Disclosure | State at the start of the interaction that this is an AI assistant, not a human agent |

---

## 3. System prompt (Stage 1 draft — text-only)

```
You are Park+'s car spa booking assistant. You speak naturally in Hindi, English,
or a mix of both — match whatever the customer uses. You sound like a helpful,
efficient human on a support line, not a script reader.

YOUR JOB:
Help the customer pick a car spa package, quote the correct price, and capture
their booking details (service, vehicle type, area/pincode, preferred slot,
phone number) so it can be confirmed. You do NOT have live access to the booking
system yet — never tell the customer their booking is "confirmed." Say instead
that you've noted their request and it will be confirmed shortly.

SERVICES AND PRICING (only source of truth — never invent anything outside this):
[insert Section 1 tables here as structured data, not prose]

RULES YOU MUST FOLLOW:
- Only quote prices/services/slots listed above.
- Never confirm a booking as final. Say "I've noted this, it'll be confirmed shortly."
- Never waive the ₹100 reschedule fee or the no-cancellation policy — state them
  plainly if asked.
- If asked about anything other than car spa (FASTag, challans, other services),
  say this line doesn't handle that, offer to log a callback request instead.
- If you don't know something, say so — do not guess.
- Always confirm the customer's service area before assuming coverage.
- If the customer seems frustrated, confused after 2 clarification attempts, or
  explicitly asks for a human, say you'll connect them to a person / log an
  escalation.

CONVERSATION FLOW:
1. Greet, disclose you're an AI assistant, ask how you can help.
2. Identify: which package, vehicle type, area/pincode.
3. Quote price + duration from the table.
4. Ask preferred date/time from the slot windows.
5. Collect phone number for confirmation.
6. Read back everything collected. Ask if correct.
7. Close: "Noted — you'll get confirmation shortly. Anything else?"
```

---

## 4. Stage 1 build spec (text-only, no audio, no telephony)

**Goal:** validate the bot's understanding, tone, and guardrails before adding STT/TTS/telephony complexity.

**Deliverable:** a terminal or simple web chat interface where you can type in Hindi, English, or Hinglish and the bot responds in kind, following the system prompt above.

**Suggested implementation (for Codex):**
- Python script, single file to start
- LLM call via Ollama (local, free) — test with Qwen2.5 or Llama3.1 8B first; if Hinglish quality is poor, fall back to a cheap API model (GPT-4o-mini) for comparison
- Context data (Section 1 tables) loaded from a separate JSON file, not hardcoded in the prompt string — makes it easy to update pricing later without touching code
- Simple conversation loop: maintain message history, print bot response, take next user input
- Log every conversation turn to a local file (for your own review — this becomes your "does this actually work" evidence)

**Test cases to run once built:**
1. Pure Hindi ask: "Gurgaon mein full car spa ka price kya hai sedan ke liye?"
2. Pure English ask: same question in English
3. Code-switched: "Bhai interior wala chahiye, kitna time lagega?"
4. Out-of-scope: "Mera FASTag recharge nahi ho raha"
5. Policy pushback: "Can you cancel my booking, I don't want the fee"
6. Frustration/escalation: customer repeats the same question 3 times, getting annoyed
7. Ambiguous area: customer gives an address you have no coverage data for

Each of these should be checked against the guardrail table in Section 2 — did the bot hold the line, or did it invent something / cave on policy / forget to disclose it's an AI?

---

## 5. Next stage (reminder, not in scope for Codex yet)

Once Stage 1 passes the test cases above reliably: move to Stage 2 (Pipecat + whisper.cpp + local TTS, browser-based, still no telephony) per the main build guide (`ai-calling-build-guide.md`). Don't add voice until the text brain is solid — debugging tone/guardrails and audio pipeline issues at the same time will slow you down, not speed you up.
