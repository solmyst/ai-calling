"""What a minute of this bot actually costs, from measured usage.

Every number under MEASURED came out of the pipecat metrics in a real 5-minute
Hindi call (2026-09-13 01:11-01:17), not from an estimate. Rates were read off
the providers' own pricing pages on 2026-09-13; re-check them before quoting
these figures to anyone, especially the Groq ones — qwen3.8-27b is a preview
model and preview pricing moves.

Run it::

    python costs.py
"""
from dataclasses import dataclass

# Rupees per US dollar. Nothing here is published in a single currency — Sarvam
# prices in INR, Groq and AssemblyAI in USD — so one assumption is unavoidable.
# It is a named constant because it is the softest number in the file.
INR_PER_USD = 88.0

# --- rates, as published 2026-09-13 -----------------------------------------
# Groq LLM, USD per 1M tokens. console.groq.com/docs/models
LLM_RATES = {
    # Current default. Preview-only, and the one model here with NO prompt caching.
    "qwen/qwen3.8-27b": (0.80, 4.00, False),
    # Production, 10.7x cheaper, and caching applies — see CACHE_DISCOUNT.
    "openai/gpt-oss-20b": (0.075, 0.30, True),
    "openai/gpt-oss-120b": (0.15, 0.60, True),
}
# Groq documents automatic prefix caching at half price on the gpt-oss models.
# MEASURED 2026-09-13 on this account: three back-to-back calls with a byte
# identical system prefix all reported prompt_tokens_details = None, i.e. no
# cached tokens at all. So on the free tier this discount does NOT apply, and
# the hoped-for "cached tokens are exempt from the rate limit" does not either.
# Left here because it is real on paid tiers — but never assume it below.
CACHE_DISCOUNT = 0.50

# MEASURED free-tier ceilings — x-ratelimit-limit-tokens on a live 1-token call
# to every chat model on the account, 2026-09-13 (scratchpad/t_limits.py):
# every usable model grants 8000 tokens/minute and 1000 requests/day.
# (qwen's 429 body says "ITPM: Limit 7000" — the input-only sub-bucket inside
# the same 8000. Budget against 7000 for qwen, since input is ~97% of a turn.)
FREE_TIER_LIMIT = {"qwen/qwen3.8-27b": 7000, "openai/gpt-oss-20b": 8000,
                   "openai/gpt-oss-120b": 8000}
# This file used to say "switching model cannot buy turns". That was wrong, and
# it was the expensive kind of wrong — it sent the work at shaving the prompt
# instead of at the free 4x sitting in plain sight. The bucket is per KEY x per
# MODEL: keys measured separate 2026-09-13 (t_keys.py, key 1 at 2724 left key 2
# at 7986), models measured separate 2026-09-14 (t_models.py, qwen3.8 down 5226
# left the other three on the SAME key untouched to the token). bot.py rotates
# both, so N keys x M models is N*M budgets.

# MEASURED 2026-09-15 by exhausting it (scratchpad/t_gemini_limits.py, then the
# 429 body once the day's quota was gone). Gemini's free tier publishes a per
# minute request cap, which is the one you hit first and the one that does not
# matter — GenerateRequestsPerDayPerProjectPerModel-FreeTier is 20 requests a DAY
# per model. Per project, so extra keys on the same project change nothing.
# Was 4 until 2026-09-15, counting a "qwen/qwen3.6-27b" that does not exist on
# this account — Groq 404s it. Verify against GET /v1/models before changing.
GROQ_MODELS = 3   # = len(FALLBACK_MODELS) in bot.py

GEMINI_FREE_RPD = 20
GEMINI_FREE_MODELS = ("gemini-3.5-flash", "gemini-3.6-flash")  # = GEMINI_MODELS in bot.py
TURNS_PER_CALL = 8  # midpoint of the 6-10 a real Car Spa call runs

SARVAM_TTS_INR_PER_CHAR = 30 / 10_000  # ₹30 per 10k characters
SARVAM_STT_INR_PER_HOUR = 30.0
ASSEMBLYAI_HINDI_USD_PER_HOUR = 0.45  # Universal-3.5 Pro Realtime; Hindi is NOT
# on the $0.15/hr multilingual tier. Also bills socket-open time, so a caller
# thinking in silence is billed the same as one talking.
DEEPGRAM_NOVA3_MULTI_USD_PER_MIN = 0.0058  # bills audio, not socket time


@dataclass
class Usage:
    """Per-minute usage. Defaults are the measured call."""

    label: str
    in_tokens: float
    out_tokens: float
    tts_chars: float
    stt_minutes: float = 1.0


# --- MEASURED: 305s call, 10 LLM turns ---------------------------------------
_MIN = 305 / 60
BEFORE = Usage("before (measured)", 40_914 / _MIN, 823 / _MIN, 2_721 / _MIN)

# --- AFTER the prompt cut: 3167 -> 2027 tokens of system prompt, resent every
# turn. 10 turns x 1140 tokens saved. Output and TTS unchanged by that edit;
# the shorter-turn instructions should cut TTS chars too, but that is a
# behaviour change and is not claimed here until it is measured.
AFTER = Usage("after prompt cut", (40_914 - 10 * 1140) / _MIN, 823 / _MIN, 2_721 / _MIN)


def llm_usd_per_min(u: Usage, model: str, cached_frac: float = 0.0) -> float:
    rate_in, rate_out, cacheable = LLM_RATES[model]
    if not cacheable:
        cached_frac = 0.0
    effective_in = u.in_tokens * (1 - cached_frac * CACHE_DISCOUNT)
    return effective_in / 1e6 * rate_in + u.out_tokens / 1e6 * rate_out


def report() -> None:
    print(f"FX assumption: {INR_PER_USD:.0f} INR/USD\n")
    print(f"{'':32}{'USD/min':>10}{'INR/min':>10}")

    def row(label, usd, indent=0):
        print(f"{' ' * indent + label:32}{usd:>10.5f}{usd * INR_PER_USD:>10.3f}")

    for u in (BEFORE, AFTER):
        print(f"\n{u.label}: {u.in_tokens:,.0f} in + {u.out_tokens:,.0f} out "
              f"tok/min, {u.tts_chars:,.0f} TTS chars/min")
        tts = u.tts_chars * SARVAM_TTS_INR_PER_CHAR / INR_PER_USD
        stt = u.stt_minutes * ASSEMBLYAI_HINDI_USD_PER_HOUR / 60
        for model in LLM_RATES:
            llm = llm_usd_per_min(u, model)
            row(f"LLM {model}", llm, 2)
        row("TTS sarvam bulbul:v3", tts, 2)
        row("STT assemblyai (hindi)", stt, 2)
        row("STT deepgram nova-3 alt", DEEPGRAM_NOVA3_MULTI_USD_PER_MIN, 2)
        row("STT sarvam alt", SARVAM_STT_INR_PER_HOUR / 60 / INR_PER_USD, 2)

    print("\n--- stack totals, per minute of call ---")
    stacks = {
        "as it runs today": (BEFORE, "qwen/qwen3.8-27b", 0.0, ASSEMBLYAI_HINDI_USD_PER_HOUR / 60),
        "+ prompt cut (done)": (AFTER, "qwen/qwen3.8-27b", 0.0, ASSEMBLYAI_HINDI_USD_PER_HOUR / 60),
        "+ gpt-oss-20b": (AFTER, "openai/gpt-oss-20b", 0.0, ASSEMBLYAI_HINDI_USD_PER_HOUR / 60),
        # No caching row: measured as not applying here (see CACHE_DISCOUNT).
        "+ deepgram STT": (AFTER, "openai/gpt-oss-20b", 0.0, DEEPGRAM_NOVA3_MULTI_USD_PER_MIN),
    }
    base = None
    for label, (u, model, cached, stt) in stacks.items():
        total = llm_usd_per_min(u, model, cached) + stt + (
            u.tts_chars * SARVAM_TTS_INR_PER_CHAR / INR_PER_USD
        )
        base = base or total
        print(f"{label:32}{total:>10.5f}{total * INR_PER_USD:>10.3f}"
              f"   {total / base:>5.0%} of today")

    # The binding constraint is not money, it is the free-tier minute. Stated as
    # turns/minute, because that is what the caller experiences: run out and the
    # bot simply stops answering.
    print("\n--- free tier: how many turns fit in a minute ---")
    # Measured against Groq's own prompt_tokens by scratchpad/t_tokens.py, which
    # breaks the turn into its parts rather than guessing at a total:
    #   system prompt 3044 + tool schemas 528 + 16-msg history 496 + scaffold 13.
    # The prompt grew 2072 -> 3044 when it became a sales script (WHY ANYONE SAYS
    # YES, the objection bank, the eight-step order). Paid for by the bucket
    # rotation below, not by hope: 8 buckets at 4081 tokens still clears a call.
    # The tool schemas were the surprise — ~500 tokens of JSON resent every turn,
    # never audited until they were measured. Re-run that script after touching
    # the prompt, the tools, or the history cap; do not edit this number by hand.
    #
    # This is the TYPICAL turn. What rate limited the 2026-09-14 20:30 call was the
    # worst one: a caller rambling on an open mic produced 400+ char turns, and the
    # old 16-MESSAGE cap let the history reach ~1080 tokens, for a 3586-token turn.
    # bot.py now budgets the history in tokens (400), so the worst turn is bounded
    # at ~3013 instead of climbing until the call dies.
    per_turn = 4081
    for model, limit in FREE_TIER_LIMIT.items():
        cost = per_turn if model.startswith("qwen") else per_turn + 140
        print(f"{model:24} limit {limit:>5} → {limit / cost:>4.1f} turns/min "
              f"at {cost} tokens/turn")
    # MEASURED 2026-09-14, scratchpad/t_models.py: the bucket is per KEY x per
    # MODEL, not per key. Burning qwen3.8 by 5226 tokens on one key left
    # qwen3.6, gpt-oss-20b and gpt-oss-120b on that same key untouched to the
    # token. bot.py rotates (key, model), so the budget multiplies both ways.
    per_bucket = 7000 / per_turn
    print(f"\nA real Car Spa call needs 6-10 turns/min. One bucket is {per_bucket:.1f}.")
    print("Buckets are per KEY x per MODEL, and bot.py rotates both:")
    for keys in (1, 2, 3):
        for models in (1, GROQ_MODELS):
            n = keys * models
            print(f"  {keys} key(s) x {models} model(s) = {n:>2} buckets → "
                  f"{n * per_bucket:>4.1f} turns/min")
    today = 2 * GROQ_MODELS * per_bucket   # 2 keys in .env x FALLBACK_MODELS in bot.py
    print(f"Today: 2 keys x {GROQ_MODELS} models = {today:.0f} turns/min, "
          f"~{today / TURNS_PER_CALL:.0f}x what a call needs.")

    # Gemini is in the rotation too, and its ceiling is a DAY, not a minute —
    # which is the only reason it gets its own block instead of another row above.
    print("\n--- gemini (free tier), the other provider in the rotation ---")
    print(f"{'requests/day per model':28}{GEMINI_FREE_RPD:>6}"
          f"   (GenerateRequestsPerDayPerProjectPerModel-FreeTier, measured)")
    gem_calls = GEMINI_FREE_RPD * len(GEMINI_FREE_MODELS) / TURNS_PER_CALL
    print(f"{'x models in bot.py':28}{GEMINI_FREE_RPD * len(GEMINI_FREE_MODELS):>6}"
          f"   requests/day, i.e. ~{gem_calls:.0f} whole calls")
    groq_rpd = 1000 * 2 * GROQ_MODELS
    print(f"{'groq, same measure':28}{groq_rpd:>6}"
          f"   requests/day (1000 x 2 keys x {GROQ_MODELS} models) = "
          f"{groq_rpd / GEMINI_FREE_RPD / len(GEMINI_FREE_MODELS):.0f}x")
    print("So Gemini is emergency reserve, not capacity. It covers the turns Groq")
    print("cannot, on a provider that fails independently, and is spent for the day.")
    print("Billing on the Google project is what would turn it into a real bucket.")


def _demo():
    # The arithmetic that the headline claims rest on.
    assert abs(BEFORE.in_tokens - 8049) < 1, BEFORE.in_tokens  # the 429s explained
    assert AFTER.in_tokens < 8000 < BEFORE.in_tokens, "prompt cut must clear the TPM limit"

    # gpt-oss-20b is the cheap one, and caching only ever helps a cacheable model.
    q = llm_usd_per_min(AFTER, "qwen/qwen3.8-27b", cached_frac=0.75)
    g = llm_usd_per_min(AFTER, "openai/gpt-oss-20b", cached_frac=0.75)
    assert g < q / 5, (g, q)
    assert llm_usd_per_min(AFTER, "qwen/qwen3.8-27b", 0.75) == llm_usd_per_min(
        AFTER, "qwen/qwen3.8-27b", 0.0
    ), "qwen has no prompt caching — a discount here would be a lie"

    # TTS really is the biggest line once the LLM is not the qwen one.
    tts = AFTER.tts_chars * SARVAM_TTS_INR_PER_CHAR / INR_PER_USD
    assert tts > g * 10, (tts, g)
    print("costs ok")




# --- getting to Re 1 per minute -----------------------------------------------
# The product owner's target, 2026-09-21. Everything below is measured, not
# assumed: reply length and turn count come from call.log (174 bot turns, mean
# 144 characters), the LLM prompt size from the tokeniser, the rates from the
# constants above and from each vendor's published price page.

TARGET_INR_PER_MIN = 1.0
CALL_MIN = 3.0                 # the three real calls in call.log ran 178/145/172s
BOT_TURNS = 9                  # MONIKA lines in one 3-minute call
REPLY_CHARS = 144              # MEASURED mean over the 145 INSURANCE turns in
                               # call.log. NOT 182 — that is the blend with the
                               # car spa era, whose replies average 225 and are
                               # a different product with a different prompt.
LLM_IN_PER_TURN = 4056         # system prompt (3556, measured) + card + history
BIFROST_USD_PER_MTOK = 1.03    # implied by the $10 cap against 9.67M tokens
PLIVO_INR_PER_MIN = 0.38       # published


def _call_inr(*, llm_free=False, stt_free=False, tts_free=False,
              reply_chars=REPLY_CHARS, turns=BOT_TURNS, call_min=CALL_MIN,
              cached_frac=0.0):
    """Rupees for one call under a given set of levers."""
    llm = 0.0 if llm_free else (
        turns * LLM_IN_PER_TURN * (1 - cached_frac) / 1e6
        * BIFROST_USD_PER_MTOK * INR_PER_USD
    )
    stt = 0.0 if stt_free else call_min / 60 * ASSEMBLYAI_HINDI_USD_PER_HOUR * INR_PER_USD
    tts = 0.0 if tts_free else turns * reply_chars * SARVAM_TTS_INR_PER_CHAR
    tel = call_min * PLIVO_INR_PER_MIN
    return llm, stt, tts, tel


def target_report() -> None:
    """What each lever is worth, and which combinations reach Re 1/min."""
    def line(label, parts, note=""):
        total = sum(parts)
        per_min = total / CALL_MIN
        hit = "  <-- TARGET" if per_min <= TARGET_INR_PER_MIN else ""
        print(f"  {label:<44} Rs {total:5.2f}/call  Rs {per_min:4.2f}/min{hit}")
        if note:
            print(f"  {'':<44} {note}")

    print(f"\nTarget: Rs {TARGET_INR_PER_MIN:.0f}/min "
          f"= Rs {TARGET_INR_PER_MIN * CALL_MIN:.0f} for a {CALL_MIN:.0f}-minute call\n")

    base = _call_inr()
    names = ("LLM (Bifrost/Gemini)", "STT (AssemblyAI)", "TTS (Sarvam)", "telephony (Plivo)")
    print("  where it goes today:")
    for n, v in zip(names, base):
        print(f"    {n:<40} Rs {v:5.2f}  {v / sum(base) * 100:4.0f}%")
    print()
    line("today", base)
    print()
    line("+ Park+ LLM (self-hosted, no per-token bill)", _call_inr(llm_free=True))
    line("+ Park+ STT (self-hosted)", _call_inr(llm_free=True, stt_free=True))
    line("+ replies 144 -> 110 chars", _call_inr(llm_free=True, stt_free=True, reply_chars=110))
    line("+ replies 144 -> 80 chars", _call_inr(llm_free=True, stt_free=True, reply_chars=80))
    print()
    print("  keeping Gemini (quality) and leaning on caching instead:")
    for frac in (0.0, 0.5, 0.75, 0.9):
        line(f"  prompt cache hit {frac:.0%}, Park+ STT, 110-char replies",
             _call_inr(stt_free=True, reply_chars=110, cached_frac=frac))
    print()
    print("  the floor, if TTS also goes local (Piper):")
    line("  Park+ LLM + Park+ STT + Piper TTS", _call_inr(llm_free=True, stt_free=True, tts_free=True))
    print(f"\n  telephony alone is Rs {CALL_MIN * PLIVO_INR_PER_MIN / CALL_MIN:.2f}/min "
          f"and cannot be optimised away.")


if __name__ == "__main__":
    _demo()
    print()
    report()
    target_report()
