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

## The judge

Pipecat's default judge is a local Ollama (`gemma4:12b`); without one every
assertion fails `NotFoundError` and pulling it is 7.6 GB. `judge_llm.py` points
it at Park+'s own LLM instead — no download, no bill.

## Writing assertions

State ONE condition, positively. "the bot replies in Hindi about car cleaning —
and does not fall silent" failed a perfectly good turn, because whether a reply
"fell silent" is not something a judge can read off text. The judge said so in
its own reasoning.
