# Headless evals

Test the whole pipeline — STT, LLM, guardrails, TTS — with no browser, no
microphone and no phone call.

Every bug found on 2026-09-18 presented identically on a live call ("the bot
said nothing") and took a browser, a mic and a round trip with the user to
diagnose. All of them fail these scenarios in seconds:

| Bug | How it showed up here |
|---|---|
| STT `sample_rate` pinned to 16000, so 24 kHz audio transcribed as silence | no `llm_response` |
| `STTSettings` left `NOT_GIVEN` | error at startup |
| `chat_template_kwargs` sent as a top-level kwarg | every turn dies |
| `qwen/qwen3.6-27b` does not exist | call dies from turn five |
| the greeting guard leaking across calls | second run sits in silence |
| STT flush waiting on the turn strategy that was waiting on the STT | `smoke_audio` turn 1 times out |

That last one is why `smoke_audio.yaml` exists. `smoke.yaml` runs in **text**
modality: the user's turns are injected as text and the STT never runs, so it
passed for hours while every live call sat silent. Only the audio scenario
exercises VAD, turn detection and the real ASR.

## Run them

Two terminals. First, the bot, in eval mode:

```bash
cd voicebot/server && ../../venv/bin/python bot.py -t eval
```

Then, from the same directory:

```bash
PYTHONPATH="$PWD/evals" ../../venv/bin/pipecat eval run evals/smoke.yaml -v        # text: fast
PYTHONPATH="$PWD/evals" ../../venv/bin/pipecat eval run evals/smoke_audio.yaml -v  # audio: the real path
```

`--bot-url ws://localhost:7899` if you moved the bot off the default port, which
you need when a normal `bot.py` is already holding 7860.

## The whole suite

One worker serves every connection in eval mode, so the LLM context, the guard's
counters and the `greeted` flag all carry over between scenarios — a run that
names a Creta leaves prices unlocked for the next one, and the second scenario
in a batch never hears an opening. Either restart the bot between scenarios, or
let the suite do it: it spawns a fresh bot per scenario, on its own port.

```bash
cd voicebot/server/evals
DOMAIN=insurance PYTHONPATH=. ../../../venv/bin/pipecat eval suite suite_insurance.yaml
```

Exit code is 0 only if every scenario passes. `DOMAIN` is inherited by the
spawned bots, which is why the manifest covers one domain at a time.

## Call-card scenarios

`cards/*.json` are prefetched call cards, the JSON the dialer hands the bot
before it rings. `runner_body:` in the manifest is per-BOT, not per-scenario —
which is also what a real call is: one card, one dial — so each card gets its
own spawn entry. To drive one by hand:

```bash
python bot.py -t eval --runner-body evals/cards/duplicate.json   # a PATH, not inline JSON
```

`cards/duplicate.json` is the product owner's worked example: KYC already done,
vehicle already insured elsewhere. The bot must not mention KYC at all. See
`domains/insurance/CALL_CARD.md` for the contract.

## What these do NOT cover

`pipecat eval` in **text** modality asserts on `llm_response`, which is the
model's text on its way OUT of the LLM. The guardrails are a `BaseTextFilter`
inside the TTS service, further downstream — so **in text mode the guard never
runs, and these scenarios measure the PROMPT alone.** A green `kyc_safety` says
the prompt kept the bot out of trouble; it says nothing about the guard.

That is the right split — two independent layers, tested independently — but it
is easy to misread. The guard is covered by:

```bash
DOMAIN=insurance ../../../venv/bin/python -m domains.insurance.guard   # its own assertions
../../../venv/bin/python fuzz_guard.py out.json                        # 270 LLM-written turns
```

`fuzz_guard.py` asks the live model for the turns it would really produce across
45 situations and prints everything the guard rewrote. Every line it prints is a
judgement call to read, not a failure. Five rounds of it on 2026-09-19 found
eight rules firing on sentences the bot *should* be allowed to say — including
"KYC complete karna hai", the core ask of the entire call.

The audio scenarios (`kyc_audio`, `smoke_audio`) DO run the guard, because the
text reaches the TTS.

## Keys, and not taking production down

The judge and the simulated caller are LLM traffic too, and by default they bill
to the same Bifrost virtual key the bot calls on. On 2026-09-19 that key hit its
cap mid-session — 2,043 bot turns and 2,037 judge calls, 9.7M input tokens — and
the **bot** was the thing left with nothing to answer with.

Set `BIFROST_EVAL_VK` to a second key so the harness cannot starve the phone
line. Unset, the judge warns once per run. `JUDGE_BACKEND=parkplus` forces the
judge off Bifrost entirely, which is how you tell "the key is spent" apart from
"the bot is broken" — they look identical otherwise.

## The judge

Pipecat's default judge is a local Ollama (`gemma4:12b`); without one every
assertion fails `NotFoundError` and pulling it is 7.6 GB. `judge_llm.py` points
it at Park+'s own LLM instead — no download, no bill.

## Writing assertions

State ONE condition, positively. "the bot replies in Hindi about car cleaning —
and does not fall silent" failed a perfectly good turn, because whether a reply
"fell silent" is not something a judge can read off text. The judge said so in
its own reasoning.
