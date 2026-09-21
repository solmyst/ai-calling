"""Deterministic output guardrail for the car spa bot.

The system prompt tells the model never to invent a price, but prompt-only
enforcement is not reliable — in live calls this bot quoted an availability it
could not know and, on another turn, read back a slot time the customer never
asked for. This module is the layer that does not depend on the model behaving:
every rupee amount leaving the bot is checked against the real price list, and
anything else is replaced before it reaches the caller's ears.

Prices are a closed set, so this check is exact. Slot times are only *logged* when
they look invented — the bot legitimately repeats times the customer said, so
rewriting them would do more damage than good.
"""
import json
import re
from pathlib import Path

# The facts belong to a DOMAIN, not to this file. Everything below — the price
# regex, the slot parser, the booking words — is generic machinery pointed at
# whatever domains/<DOMAIN>/context.json says.
from domain import CONTEXT_FILE  # noqa: E402

# A number being said AS money, in any form this bot actually produces:
#   "₹579", "Rs 579", "579 rupaye", "579 rupees", and — since the bot speaks
#   Devanagari — "579 रुपये" / "रुपए" / "रूपये".
_RUPEE_WORD = r"(?:rupa?y?e?e?s?|rupees|rs|रुपये|रुपए|रूपये|रूपए|रुपयों)"
# No trailing \b after the rupee word: Devanagari vowel signs ("रुपये") break the
# word boundary and the whole pattern silently stops matching Hindi prices.
# The rupee word is CONSUMED, not just looked ahead at: replacing only the digits
# left the unit stranded and the bot said "...bataati hoonरुपये".
_PRICE_RE = re.compile(
    rf"(?:(?:₹|\bRs\.?\b)\s*(\d{{2,5}})|(\d{{2,5}})\s*{_RUPEE_WORD})",
    re.IGNORECASE,
)
_TIME_RE = re.compile(r"\b(\d{1,2})[:.](\d{2})\s*(AM|PM)?\b", re.IGNORECASE)

# --- times said the way this bot actually says them ---------------------------
# The digit form above never fires in practice: the prompt tells the bot to speak
# times in words ("सुबह आठ बजे"), so every real slot readback slipped past the
# check. A live call proved it — the caller asked for आठ बजे and the bot read back
# "सवा आठ बजे" (08:15), a slot that does not exist, and nothing noticed.
_HINDI_HOUR = {
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पाँच": 5, "पांच": 5, "छह": 6, "छः": 6,
    "सात": 7, "आठ": 8, "नौ": 9, "दस": 10, "ग्यारह": 11, "बारह": 12,
}
# Quarter-past / half-past / quarter-to, as minute offsets. पौने counts DOWN from
# the named hour ("पौने नौ" is 08:45), which is why it carries the hour shift.
_HINDI_FRACTION = {"सवा": (0, 15), "साढ़े": (0, 30), "साढे": (0, 30), "पौने": (-1, 45)}
_HINDI_MERIDIEM = {"सुबह": "AM", "दोपहर": "PM", "शाम": "PM", "रात": "PM"}
_HINDI_TIME_RE = re.compile(
    rf"(?:({'|'.join(_HINDI_MERIDIEM)})\s+)?"
    rf"(?:({'|'.join(_HINDI_FRACTION)})\s+)?"
    rf"({'|'.join(_HINDI_HOUR)})\s*बजे"
)


def _hindi_time_candidates(meridiem: str, fraction: str, hour: str) -> set[str]:
    """Every HH:MM a spoken Hindi time could mean, as 24h strings.

    "आठ बजे" is 08:00 or 20:00 and the speaker rarely says which, so both come
    back and the caller is given the benefit of the doubt: if either reading is a
    real published slot, the time is treated as real.
    """
    h = _HINDI_HOUR[hour]
    shift, minute = _HINDI_FRACTION.get(fraction, (0, 0))
    h = (h + shift - 1) % 12 + 1
    halves = [0, 12] if not meridiem else [0 if _HINDI_MERIDIEM[meridiem] == "AM" else 12]
    return {f"{(h % 12 + half):02d}:{minute:02d}" for half in halves}

# Spoken by a Hindi voice, so it has to be Devanagari like everything else the
# bot says — the old romanised version was read with an English mouth.
_SAFE_PRICE = "उसका price मैं confirm करके बताती हूँ"

# --- claiming a booking is done ---------------------------------------------
# The bot may only NOTE a request; a human confirms it afterwards. A caller who
# is told "book हो गया" stops watching for the confirmation and expects a cleaner,
# so this is the costliest sentence the bot can say and is worth enforcing rather
# than requesting. Split into two halves so the future tense the bot is SUPPOSED
# to use ("confirm हो जाएगा", "team confirm कर देगी") cannot match: नहीं one of the
# done-markers below is a future form.
_BOOKING_WORD = r"(?:book(?:ed|ing)?|confirm(?:ed)?|slot|स्लॉट|बुक)"
_DONE_MARKER = (
    r"(?:हो गय[ाीे]|हो गई|हो चुक[ाीे]|कर दिय[ाा]|कर दी|पक्क[ाी]|"
    r"confirmed|is booked|has been booked)"
)
# A sentence that frames the outcome as a noted request is the correct behaviour
# even though it contains a booking word and a completed verb
# ("आपकी booking request note कर दी है") — so it is exempt.
_NOTED_RE = re.compile(r"(?:note|request|नोट)", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"[^.।!?]+[.।!?]?")
_SAFE_BOOKING = (
    "मैंने आपकी request note कर ली है, team check करके confirm कर देगी"
)

# --- claiming a slot or an area is available ---------------------------------
# The bot has no access to the slot calendar or the service polygon, so every
# such claim is a guess, and a caller told "कल eight बजे slot available है" plans
# their morning around it. Caught live: "हाँ जी, कल morning eight बजे slot
# available है — मैं note कर देती हूँ।" Both directions are wrong, so "available
# नहीं है" is rewritten too; the bot cannot know that either. Requires a slot/area
# word in the same sentence, so "app में available" style lines are left alone.
# Bare English "full" used to be in here and it cost a good answer on the
# 2026-09-14 20:28 call: "हमारी team trained है ... full equipment हमारी side से
# आता है, और app में slot, invoice सब clear रहता है" was rewritten into the
# note-your-preference line, because "full" and "slot" happened to share a
# sentence. "full" in Hinglish is far more often full equipment, full car, full
# detailing than a full slot, so it only counts when it is actually attached to
# one. Every other word here can only mean availability.
_AVAIL_WORD = (
    r"\b(?:un)?available\b|उपलब्ध|खाली|\bbooked\b|फ़ुल|"
    r"(?:slot|स्लॉट|बजे)\s+\w*\s*full\b"
)
_SLOT_CTX = (
    r"slot|स्लॉट|बजे|टाइम|area|एरिया|सेक्टर|sector|pincode|पिनकोड|"
    r"कल|आज|परसों|morning|evening|सुबह|शाम|दोपहर"
)
_SAFE_AVAILABILITY = (
    "मैं आपकी preference note कर लेती हूँ, team check करके confirm कर देगी"
)

# --- machine output that is not speech ---------------------------------------
# Caught live 2026-09-13 23:39: qwen returned a raw JSON error blob as its turn
# (a hallucinated Vertex AI 429, 69 completion tokens, no API error involved) and
# Sarvam read it to the caller — braces, quotes and
# "cloud.google.com/vertex-ai/docs/about/billing" out loud in a Hindi voice. No
# other guard fired: there was no price, no slot word, nothing to match. Human
# speech never contains braces, a quoted JSON key or a URL, so anything that does
# is not a turn and is dropped rather than rewritten — a second of silence beats
# reading a billing URL to a customer. ".com/" needs the slash so an email or a
# plain domain the bot may legitimately say is untouched.
_MACHINE_OUTPUT_RE = re.compile(
    r"""[{}]|"\s*:|https?://|www\.|\.com/|```|</?[a-z]+>""", re.IGNORECASE
)

# --- promising the car will not be damaged -----------------------------------
# Caught live on the same call: asked "अगर मेरी कार तोड़ दी तो कौन ज़िम्मेदार?" the
# bot answered "गाड़ी को किसी तरह का damage नहीं होता" and then "team उसका पूरा
# ध्यान रखेगी". Neither is in context — it invented a liability position on a
# recorded call. This is the one class of invention that costs more than a wrong
# price, so it is replaced, not logged.
_DAMAGE_WORD = (
    r"damage|नुकसान|टूट|तोड़|खरोंच|scratch|dent|ज़िम्मेदार|जिम्मेदार|"
    r"responsible|liable|claim|compensat|guarantee|गारंटी"
)
_SAFE_DAMAGE = (
    "ऐसा कुछ हो तो Help and Support उसे देखती है सर, मैं यहाँ से कोई promise नहीं कर सकती"
)

# --- pricing by body type ----------------------------------------------------
# Price comes from brand and model, never from hatchback/sedan/SUV — the tier
# table has no body classes in it. The prompt says so twice and the model still
# asked "आपकी car hatchback है, sedan है या SUV?" on a live call, which sends the
# caller down a path where no price exists. Replaced with the question that does
# have an answer.
_BODY_TYPE_RE = re.compile(r"hatchback|sedan|\bSUV\b|\bMUV\b", re.IGNORECASE)
# ...but only when the bot is ASKING the caller to classify their car that way,
# or pricing off it. Merely naming the shape is fine and now common: once the
# prompt became a sales script it started recommending with lines like "Creta
# जैसी SUV में अंदर का काम ज़्यादा है", and the unqualified guard rewrote that
# into "कौन सी गाड़ी है आपकी" — asking again for the car it had just named.
_BODY_TYPE_CTX = re.compile(r"\?|रुपये|price|दाम|कितने|\d{3}", re.IGNORECASE)
_SAFE_BODY_TYPE = "कौन सी गाड़ी है आपकी — brand और model?"

# --- the model narrating its own process out loud ----------------------------
# Caught 2026-09-15 on gemini-3.6-flash, with reasoning_effort already "none":
# "I need to investigate this further. Let me check the details. Creta है ना? तो
# करीब 499 रुपये..." — the first two sentences are the model thinking, in English,
# spoken to a Hindi caller. No other guard fired: no price, no slot, no braces.
# Not a Gemini quirk either. qwen shipped the same class of failure as a JSON
# error blob, which is why _MACHINE_OUTPUT_RE exists; this is the prose version of
# it, and every model can do it.
#
# Two conditions, because either alone over-blocks. The phrase must be first
# person about its OWN process, AND the sentence must carry no Devanagari at all:
# "मैं check करके बताती हूँ" is a legitimate Hinglish line and stays, while
# "Let me check the details." is never something Monika says.
_SELF_NARRATION_RE = re.compile(
    r"\b(?:I (?:need|should|must|have) to|I'?ll check|let me (?:check|see|look|"
    r"investigate|think|confirm)|the user (?:is|has|wants|asked|said)|"
    r"first,? I|okay,? so I)\b",
    re.IGNORECASE,
)
_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")

#: A chunk with no Devanagari at all and more than this many characters is the
#: model answering in English, not an English noun inside a Hindi sentence.
#: "Aadhar Front Image" is 18 characters and legitimate; a sentence is longer.
_ENGLISH_DRIFT_MIN_CHARS = 25


def is_script_drift(text: str) -> bool:
    """Is this the model answering in the wrong script?

    Two shapes, and the second was missed for a long time because the first
    looked like the whole problem:

    1. Romanised Hindi — "Aapko kaun sa package chahiye". _ROMAN_HINDI_RE
       catches it by its function words, none of which is a real English word.
    2. Straight English — "Good afternoon. I'm Monika calling from Park+
       Insurance about your vehicle." There is not one romanised Hindi word in
       that, so rule 1 never fires, and it is further from the script than any
       drift rule 1 catches. Observed for real on a Park+/Ornith fallback turn.

    Both are a problem for the same mechanical reason: Sarvam pronounces Latin
    text with an English mouth. Callers on this line are speaking Hindi.

    The length floor keeps legitimate English nouns safe. The bot says "Complete
    KYC", "Aadhar Front Image" and "Next" constantly, and a TTS filter sees
    CHUNKS rather than whole turns, so a short Latin-only chunk is ordinary.
    """
    if _ROMAN_HINDI_RE.search(text):
        return True
    stripped = text.strip()
    return len(stripped) >= _ENGLISH_DRIFT_MIN_CHARS and not _DEVANAGARI_RE.search(stripped)

# --- speaker labels ----------------------------------------------------------
# Few-shot examples in the prompt are written as a transcript, and gpt-oss-20b
# copied the transcript's own label into what it said: the caller heard
# "M: मैं AI assistant हूँ". Reformatting the examples helps; deleting the label
# here is what guarantees it. Only an exact known label at the very start of the
# chunk is removed, so ordinary speech containing a colon is untouched.
_SPEAKER_LABEL_RE = re.compile(
    r"^\s*(?:M|C|A|U|Monika|Assistant|Agent|Bot|You|Caller|Customer|मोनिका|ग्राहक)\s*:\s*",
    re.IGNORECASE,
)

# --- script drift ------------------------------------------------------------
# Hindi must reach Sarvam in Devanagari; romanised Hindi is pronounced with an
# English mouth. The prompt says so and the model still drifted by turn three of
# a live call ("Aapko kaun sa package chahiye"). These are romanised Hindi
# function words — none of them is a real English word, so they separate drift
# from the English nouns that legitimately stay English (service, slot, booking).
_ROMAN_HINDI_RE = re.compile(
    r"\b(?:aap(?:ko|ki|ka|se)?|hai|hain|kar(?:te|ke|na|ni)?|kaun|kya|kyun|"
    r"nahi+n?|chahiye|mein|bhi|toh|hoga|hogi|honge|karenge|karengi|bata(?:iye|do)?|"
    r"dijiye|dete|deti|raha|rahi|rahe|sirf|wala|wali|usme|isme|yeh|woh|jaise|"
    r"lagta|lagti|lagega|sakta|sakti|sakte|gaadi|paas|liye|abhi|thoda)\b",
    re.IGNORECASE,
)


# --- quoting a price for a car the caller never named -------------------------
# Caught live 17:09 on 2026-09-18. The caller asked three times about lipstick
# marks and never once answered "which car". The bot said "लगभग ₹499 (Hyundai
# Creta के लिए)" — it picked a car and quoted its price. 499 is a REAL tier
# price, so every existing guard passed it: the number was fine, the subject was
# invented. A caller with a BMW hears 499 and is later charged 959.
#
# Price here is a function of brand and model, so a price before the car is known
# is never right, whatever number it is. This is the one guard that needs the
# CALLER's side of the conversation, which is why PriceGuard now has
# note_caller() and why bot.py hands the same instance to both the TTS filter and
# the call observer.
_GENERIC_CAR_WORDS = re.compile(r"गाड़ी|गाडी|car|कार", re.IGNORECASE)


def car_terms(ctx: dict) -> set[str]:
    """Brand and model spellings that count as the caller naming their car.

    The tier table's example cars are the authoritative part; the rest are models
    people actually own in Gurugram. Same list the STT is biased toward, so these
    are the spellings a transcript is most likely to carry.
    """
    terms = set()
    for tier in ctx["pricing"]["premium_tier_prices_inr"]:
        car = tier["example_car"]
        terms.add(car.lower())
        terms.update(part.lower() for part in car.split())
    terms.update(
        w.lower() for w in (
            "Swift", "Baleno", "WagonR", "Alto", "Brezza", "Ertiga", "Dzire",
            "i20", "i10", "Venue", "Verna", "Nexon", "Punch", "Harrier",
            "Scorpio", "Thar", "XUV700", "Bolero", "Seltos", "Sonet", "Innova",
            "Fortuner", "Amaze", "City", "Maruti", "Suzuki", "Hyundai", "Tata",
            "Mahindra", "Kia", "Toyota", "Honda", "Renault", "Skoda", "Nissan",
            "Volkswagen", "BMW", "Audi", "Mercedes", "Jeep", "MG",
            # Devanagari for the ones a Hindi caller most often says outright.
            # The STT is keyterm-biased toward the Latin spellings above, so this
            # is the fallback, not the main path — a miss here costs one extra
            # "कौन सी गाड़ी है आपकी", never a wrong price.
            "क्रेटा", "स्विफ्ट", "बलेनो", "ऑल्टो", "वैगनआर", "नेक्सॉन", "थार",
            "स्कॉर्पियो", "सिटी", "वेन्यू", "वर्ना", "ब्रेज़ा", "इनोवा",
            "मारुति", "हुंडई", "टाटा", "महिंद्रा", "होंडा", "टोयोटा", "किआ",
        )
    )
    return terms


_SAFE_NO_CAR = "पहले ये बता दीजिए सर — कौन सी गाड़ी है आपकी, brand और model?"


def is_machine_output(text: str) -> bool:
    """True when this is not a spoken turn at all — JSON, markup, a URL.

    Exposed because two layers need the same answer: the TTS filter, to keep it
    out of the caller's ear, and the LLM service, to keep it out of the history.
    """
    return bool(text) and bool(_MACHINE_OUTPUT_RE.search(text))


def valid_prices(ctx: dict) -> set[int]:
    """Every rupee figure the bot is allowed to say out loud.

    Real pricing is per vehicle tier T1-T9, and only Full Car Spa Premium has
    published numbers — so the allowed set is those nine prices plus the Instant
    service fee. Anything else (including any price for Basic or Exterior Only,
    which are genuinely undocumented) is an invention and gets replaced.
    """
    allowed = {t["price"] for t in ctx["pricing"]["premium_tier_prices_inr"]}
    allowed.add(ctx["instant_booking"]["fee_inr"])
    # Durations get spoken as plain numbers near the word "minute", not as money,
    # so they are not part of this set — the regex only matches rupee contexts.
    return allowed


def valid_slot_hhmm(ctx: dict) -> set[str]:
    """The published slot windows, normalised to 24h HH:MM."""
    out = set()
    for w in ctx["slots"]["typical_windows"]:
        t = w.strip().upper()
        hh, rest = t.split(":", 1)
        mm, ampm = rest[:2], rest[-2:]
        h = int(hh) % 12 + (12 if ampm == "PM" else 0)
        out.add(f"{h:02d}:{mm}")
    return out


class PriceGuard:
    """Replaces any rupee amount that is not a real Park+ price.

    Invented prices are the failure with the worst consequence here — the customer
    acts on what they were quoted — and the valid set is small and closed, so this
    can be enforced exactly rather than asked for politely.
    """

    def __init__(self, ctx: dict | None = None):
        ctx = ctx or json.loads(CONTEXT_FILE.read_text())
        self.allowed = valid_prices(ctx)
        self.slots = valid_slot_hhmm(ctx)
        self.cars = car_terms(ctx)
        # False until the CALLER names a car. Nothing the BOT says can set it —
        # that is the whole point, since the bot naming a car is exactly the
        # failure being prevented.
        self.car_known = False
        self.priced_before_car: list[str] = []
        self.blocked: list[int] = []
        self.odd_times: list[str] = []
        self.false_confirmations: list[str] = []
        self.availability_claims: list[str] = []
        self.damage_promises: list[str] = []
        self.body_type_asks: list[str] = []
        self.machine_output: list[str] = []
        self.self_narration: list[str] = []
        self.romanised: list[str] = []
        self.labels: list[str] = []

    def note_caller(self, text: str) -> bool:
        """Record what the caller said. True only on the turn a car is FIRST named.

        The transition, not the running state: callers say the car once and then
        keep talking, and a method that kept returning True would make the log
        announce the unlock on every later turn. It also lets the observer stay
        domain-agnostic — it logs the transition without knowing what was gated.

        Only a brand or model counts. "मेरी गाड़ी" is not a car — it is the
        reason the bot still has to ask.
        """
        if self.car_known or not text:
            return False
        words = set(re.findall(r"[\w\u0900-\u097F]+", text.lower()))
        if words & self.cars:
            self.car_known = True
            return True
        return False

    def check(self, text: str) -> str:
        """Return text safe to speak, recording anything that was suppressed.

        Returns "" for a chunk that is not speech at all; the TTS service skips
        a filter that returns empty, so nothing is spoken for it.
        """
        if _MACHINE_OUTPUT_RE.search(text):
            self.machine_output.append(text.strip())
            return ""

        label = _SPEAKER_LABEL_RE.match(text)
        if label:
            self.labels.append(label.group(0).strip())
            text = text[label.end():]

        cleaned = "".join(
            self._fix_sentence(s) for s in _SENTENCE_RE.findall(text)
        )

        for m in _TIME_RE.finditer(cleaned):
            h, mm, ampm = int(m.group(1)), m.group(2), (m.group(3) or "").upper()
            if ampm:
                h = h % 12 + (12 if ampm == "PM" else 0)
            if f"{h:02d}:{mm}" not in self.slots:
                self.odd_times.append(m.group(0))

        for m in _HINDI_TIME_RE.finditer(cleaned):
            if not _hindi_time_candidates(*m.groups("")) & self.slots:
                self.odd_times.append(m.group(0).strip())

        # Script drift is recorded, never rewritten: transliterating mid-call
        # would mangle the English words that are supposed to stay English.
        # The count is here so drift is a number we can watch, not a vibe.
        if is_script_drift(text):
            self.romanised.append(text)

        return cleaned

    def _fix_sentence(self, sentence: str) -> str:
        """Replace a whole sentence that breaks a rule, rather than splicing.

        Substituting just the offending words left the rest of the sentence
        grammatically stranded around the replacement ("आपके लिए उसका price मैं
        confirm करके बताती हूँ लगेंगे") — which is read out loud, so it has to be a
        sentence a person would actually say. A sentence carrying both a real and
        an invented price loses the real one too; saying less is the safe way to
        be wrong here.
        """
        terminator = sentence[len(sentence.rstrip(".।!?")):] or "।"

        # Dropped, not rewritten: there is no safe sentence to say in place of the
        # model thinking out loud, and the real answer usually follows in the next
        # sentence. Runs first so the rest of the rules never see it.
        if _SELF_NARRATION_RE.search(sentence) and not _DEVANAGARI_RE.search(sentence):
            self.self_narration.append(sentence.strip())
            return ""

        bad = [
            int(m.group(1) or m.group(2))
            for m in _PRICE_RE.finditer(sentence)
            if int(m.group(1) or m.group(2)) not in self.allowed
        ]
        if bad:
            self.blocked.extend(bad)
            return _SAFE_PRICE + terminator

        # A REAL price is still wrong when it is a price for nobody's car. Runs
        # after the invented-price rule so a sentence with both is reported as
        # the invention, which is the more serious of the two.
        if not self.car_known and _PRICE_RE.search(sentence):
            self.priced_before_car.append(sentence.strip())
            return _SAFE_NO_CAR

        if (
            re.search(_BOOKING_WORD, sentence, re.IGNORECASE)
            and re.search(_DONE_MARKER, sentence, re.IGNORECASE)
            and not _NOTED_RE.search(sentence)
        ):
            self.false_confirmations.append(sentence.strip())
            return _SAFE_BOOKING + terminator

        if re.search(_AVAIL_WORD, sentence, re.IGNORECASE) and re.search(
            _SLOT_CTX, sentence, re.IGNORECASE
        ):
            self.availability_claims.append(sentence.strip())
            return _SAFE_AVAILABILITY + terminator

        if re.search(_DAMAGE_WORD, sentence, re.IGNORECASE):
            self.damage_promises.append(sentence.strip())
            return _SAFE_DAMAGE + terminator

        if _BODY_TYPE_RE.search(sentence) and _BODY_TYPE_CTX.search(sentence):
            self.body_type_asks.append(sentence.strip())
            return _SAFE_BODY_TYPE

        return sentence


def _demo():
    # This file is the CAR SPA's guard and its context.json is the only one with
    # a "pricing" block. .env pins DOMAIN=insurance for live calls, so a bare
    # `python guardrails.py` died on `KeyError: 'pricing'` — a confusing way to
    # learn you needed an env var, especially at the start of a launch day.
    import domain
    if domain.ACTIVE != "car_spa":
        raise SystemExit(
            f"guardrails.py is the car spa's guard, but DOMAIN={domain.ACTIVE!r}.\n"
            f"  run:  DOMAIN=car_spa python guardrails.py\n"
            f"  the insurance guard is:  DOMAIN=insurance python -m domains.insurance.guard"
        )

    ctx = json.loads(CONTEXT_FILE.read_text())

    def guard_mid_call():
        """A guard at the point a real call quotes a price: the car is known.

        Prices are gated on the caller having named a car (see _SAFE_NO_CAR), so
        a fixture that quotes one without a caller turn is testing a state the
        bot is never in. The gate itself is tested separately, on virgin guards.
        """
        g = PriceGuard(ctx)
        assert g.note_caller("Creta है मेरे पास"), "fixture car must be recognised"
        return g
    g = guard_mid_call()

    # Real tier prices pass through untouched.
    ok = "Creta के लिए 499 रुपये, और BMW X4 के लिए 959 रुपये।"
    assert g.check(ok) == ok, g.check(ok)
    # Instant service fee is real too.
    assert g.check("Instant का 200 रुपये extra लगता है।").count("200") == 1

    # The old website prices are fiction now — they must not reach the caller.
    for fake in (479, 579, 679, 604, 3534):
        out = g.check(f"आपके लिए {fake} रुपये लगेंगे।")
        assert str(fake) not in out, (fake, out)
        assert _SAFE_PRICE in out

    # A made-up discount never reaches the caller, and the unit goes with it —
    # replacing only the digits used to leave "...बताती हूँरुपये" to be read out.
    bad = g.check("आपके लिए 450 रुपये लगेंगे।")
    assert "450" not in bad and _SAFE_PRICE in bad, bad
    assert "रुपये" not in bad, bad
    assert 450 in g.blocked
    assert g.check("Aapke liye 450 rupaye kar dete hain.").count("450") == 0

    # Symbol forms are caught too.
    assert "299" not in g.check("Sirf ₹299 mein ho jayega.")
    assert "349" not in g.check("Rs 349 only.")

    # A slot the bot invented is flagged (not rewritten).
    g2 = guard_mid_call()
    g2.check("Maine 07:15 AM ka slot note kar liya.")
    assert g2.odd_times == ["07:15 AM"], g2.odd_times
    g3 = guard_mid_call()
    g3.check("08:00 AM ka slot theek rahega?")
    assert g3.odd_times == [], g3.odd_times

    # Spoken Hindi times — the form the bot actually uses, and the form the live
    # "caller said आठ, bot said सवा आठ" drift arrived in.
    for real in (
        "सुबह आठ बजे — note कर लिया मैंने।",       # 08:00
        "साढ़े दस बजे आ जाएँगे।",                   # 10:30
        "एक बजे का slot note कर लिया।",            # 13:00, via the PM reading
        "शाम छह बजे ठीक रहेगा?",                   # 18:00
        "साढ़े पाँच बजे सुबह वाला?",                # 05:30
    ):
        gt = guard_mid_call()
        gt.check(real)
        assert gt.odd_times == [], (real, gt.odd_times)
    for invented in (
        ("सवा आठ बजे note कर लिया।", "सवा आठ बजे"),      # 08:15 — the live bug
        ("पौने नौ बजे आ जाएँगे।", "पौने नौ बजे"),          # 08:45
        ("सुबह दस बजे कर देते हैं।", "सुबह दस बजे"),       # 10:00, not 10:30
        ("दोपहर तीन बजे?", "दोपहर तीन बजे"),             # 15:00, not 15:30
    ):
        gt = guard_mid_call()
        gt.check(invented[0])
        assert gt.odd_times == [invented[1]], (invented, gt.odd_times)

    # A booking claimed as done is rewritten; the correct future phrasings are not.
    g4 = guard_mid_call()
    for claim in (
        "आपकी booking confirm हो गई है।",
        "Slot book हो गया आपका।",
        "Your booking is confirmed.",
        "बुक कर दिया मैंने।",
    ):
        out = g4.check(claim)
        assert "note कर ली" in out, (claim, out)
    assert len(g4.false_confirmations) == 4, g4.false_confirmations

    # Claiming a slot or an area is free — or taken — is rewritten either way.
    ga = guard_mid_call()
    for claim in (
        "हाँ जी, कल morning eight बजे slot available है।",   # the live violation
        "उस area में service उपलब्ध है।",
        "सुबह आठ बजे का slot booked है, दूसरा ले लीजिए।",
        "That slot is unavailable.",
        "कल का slot full है सर।",
    ):
        out = ga.check(claim)
        assert _SAFE_AVAILABILITY in out, (claim, out)
    assert len(ga.availability_claims) == 5, ga.availability_claims

    # ...but a real answer that merely contains both words is left alone. Verbatim
    # from the 2026-09-14 20:28 call, where the guard ate it.
    gk = guard_mid_call()
    kept = (
        "हमारी team trained है, इसलिए detailing और interior की quality consistent "
        "आती है — full equipment हमारी side से आता है, और app में slot, invoice सब "
        "clear रहता है।"
    )
    assert gk.check(kept) == kept, gk.check(kept)
    assert not gk.availability_claims, gk.availability_claims

    # Machine output is dropped, not spoken. Both chunks are verbatim from the
    # 2026-09-13 23:39 call, exactly as Sarvam received them.
    gm = guard_mid_call()
    for junk in (
        '[{\n  "error": {\n    "code": 429,\n    "message": "Resource exhausted.',
        'Please go to cloud.google.com/vertex-ai/docs/about/billing for more '
        'details.",\n    "status": "RESOURCE_EXHAUSTED"\n  }\n}',
        "<speak>नमस्ते</speak>",
        "```json",
    ):
        assert gm.check(junk) == "", junk
    assert len(gm.machine_output) == 4, gm.machine_output
    # Ordinary speech with punctuation is not machine output.
    for speech in (
        "Creta है ना? तो करीब 499 रुपये, app में exact दिख जाएगा।",
        "support@myparkplus.com पर लिख दीजिए।",
        "सुबह आठ बजे — लिख लिया मैंने।",
    ):
        assert gm.check(speech) == speech, speech

    # A liability promise the bot has no basis for is replaced. Both claims are
    # verbatim from the same call.
    gd = guard_mid_call()
    for promise in (
        "हम experienced team भेजते हैं और सारी precautions लेते हैं; गाड़ी को किसी "
        "तरह का damage नहीं होता।",
        "अगर भले ही कोई गड़बड़ी हो, team उसका पूरा ध्यान रखेगी और नुकसान की भरपाई होगी।",
        "Don't worry, we are fully responsible for any scratch.",
    ):
        out = gd.check(promise)
        assert _SAFE_DAMAGE in out, (promise, out)
    assert len(gd.damage_promises) == 3, gd.damage_promises

    # Asking the car's body type is replaced with the question that has an answer.
    gb = guard_mid_call()
    out = gb.check("आपकी car hatchback है, sedan है या SUV?")
    assert out == _SAFE_BODY_TYPE, out
    assert gb.body_type_asks, gb.body_type_asks
    assert gb.check("कौन सी गाड़ी है आपकी — brand और model?") == (
        "कौन सी गाड़ी है आपकी — brand और model?"
    )
    # Pricing off the body type is the same mistake without the question mark.
    # 499 is a REAL tier price, so the bad-price guard above lets it through and
    # this rule is the only one that can fire — which is the point of the test.
    gp = guard_mid_call()
    # No terminator appended — unlike the other rules, this replacement is
    # already a question and ends in its own "?".
    assert gp.check("SUV का 499 रुपये पड़ता है।") == _SAFE_BODY_TYPE
    assert gp.body_type_asks, gp.body_type_asks

    # But naming the shape while recommending is NOT the mistake, and the sales
    # prompt made it common. Verbatim from qwen3.8 on the bench, 2026-09-14 —
    # the old unqualified guard rewrote this into "कौन सी गाड़ी है आपकी", asking
    # again for the car it had just named.
    gk = guard_mid_call()
    ok = "Creta जैसी SUV में अंदर का काम ज़्यादा होता है सर।"
    assert gk.check(ok) == ok, gk.check(ok)
    assert not gk.body_type_asks, gk.body_type_asks

    # --- the model thinking out loud -----------------------------------------
    # Verbatim from gemini-3.6-flash, 2026-09-15, reasoning_effort="none". The
    # English narration is dropped and the Hindi answer behind it survives.
    gn = guard_mid_call()
    leaked = ("I need to investigate this further. Let me check the details. "
              "Creta है ना? तो करीब 499 रुपये।")
    out = gn.check(leaked)
    assert "I need to" not in out and "Let me check" not in out, out
    assert "499" in out and "Creta है ना?" in out, out
    assert len(gn.self_narration) == 2, gn.self_narration
    assert not gn.blocked, gn.blocked          # 499 is real and must survive

    # Hinglish that merely CONTAINS an English verb is normal speech, not
    # narration — the Devanagari is what separates them.
    gn2 = guard_mid_call()
    for ok_line in (
        "मैं check करके बता देती हूँ सर।",
        "Team confirm कर देगी आपको।",
        "Let me know करा दीजिए तो मैं note कर लूँ।",
    ):
        assert gn2.check(ok_line) == ok_line, gn2.check(ok_line)
    assert not gn2.self_narration, gn2.self_narration

    # --- a real price for a car nobody named ---------------------------------
    # Verbatim from the 17:09 call on 2026-09-18. The caller asked about lipstick
    # marks three times and never answered "which car"; the bot quoted Creta's
    # price anyway. 499 is real, so no other guard fired.
    gc = PriceGuard(ctx)
    assert not gc.car_known
    leak = "लगभग ₹499 (Hyundai Creta के लिए) का होता है।"
    out = gc.check(leak)
    assert "499" not in out, out
    assert out == _SAFE_NO_CAR, out
    assert gc.priced_before_car == [leak.rstrip("।")] or gc.priced_before_car, gc.priced_before_car
    assert not gc.blocked, "499 is a real price — this is not an invented-price hit"

    # The caller naming the car unlocks it, and only the CALLER can.
    gc2 = PriceGuard(ctx)
    assert gc2.note_caller("मेरी गाड़ी गंदी है") is False, "गाड़ी is not a model"
    # True on the TRANSITION only. The observer logs on this, and a method that
    # kept returning True would announce the unlock on every later turn — and
    # the observer used to read .car_known directly, which crashed every
    # insurance call with "'KycGuard' object has no attribute 'car_known'".
    gtrans = PriceGuard(ctx)
    assert gtrans.note_caller("Creta है") is True, "first mention must report True"
    assert gtrans.note_caller("Creta है") is False, "already known — not a transition"
    assert gtrans.note_caller("हाँ ठीक है") is False
    assert gtrans.car_known is True
    assert gc2.check("Creta के लिए 499 रुपये।") == _SAFE_NO_CAR
    assert gc2.note_caller("Creta है मेरे पास") is True
    ok_now = "Creta के लिए 499 रुपये।"
    assert gc2.check(ok_now) == ok_now, gc2.check(ok_now)

    # Devanagari spelling from the caller counts too.
    gc3 = PriceGuard(ctx)
    assert gc3.note_caller("क्रेटा है जी") is True
    assert gc3.check("499 रुपये पड़ेगा।") == "499 रुपये पड़ेगा।"

    # A brand on its own is enough to start talking price.
    gc4 = PriceGuard(ctx)
    assert gc4.note_caller("Hyundai की है") is True

    # An INVENTED price before the car is still reported as the invention, which
    # is the more serious of the two findings.
    gc5 = PriceGuard(ctx)
    assert gc5.check("1500 रुपये लगेंगे।") == _SAFE_PRICE + "।"
    assert gc5.blocked == [1500] and not gc5.priced_before_car

    # Everything that is not a price is untouched before the car is known.
    gc6 = PriceGuard(ctx)
    for line in ("नमस्ते सर, Monika बोल रही हूँ Park+ से।",
                 "करीब 110 मिनट लगते हैं सर।",
                 "कौन सी गाड़ी है आपकी — brand और model?"):
        assert gc6.check(line) == line, gc6.check(line)
    assert not gc6.priced_before_car, gc6.priced_before_car

    g5 = guard_mid_call()
    for ok_line in (
        "मैंने आपकी booking request note कर दी है।",
        "Team check करके confirm कर देगी।",
        "App में exact price confirm हो जाएगा।",
        "सुबह आठ बजे — note कर लिया मैंने।",
        "Creta के लिए 499 रुपये।",
    ):
        assert g5.check(ok_line) == ok_line, ok_line
    assert g5.false_confirmations == [], g5.false_confirmations

    # Only the offending sentence is replaced; the rest of the turn survives.
    g6 = guard_mid_call()
    mixed = g6.check("अच्छा जी। Slot book हो गया। और कुछ?")
    assert "अच्छा जी।" in mixed and "और कुछ?" in mixed and "book हो गया" not in mixed

    # Romanised Hindi is counted, not rewritten. English nouns are not drift.
    g7 = guard_mid_call()
    drift = "Aapko kaun sa package chahiye — Basic ya Premium?"
    assert g7.check(drift) == drift
    assert g7.romanised == [drift], g7.romanised
    # English NOUNS inside a Hindi sentence are the house style, not drift.
    g8 = guard_mid_call()
    g8.check("आपको कौन सा package चाहिए — Basic, Premium, या Exterior Only?")
    assert g8.romanised == [], g8.romanised
    # A whole sentence in English is a different thing, and it used to be
    # asserted clean here alongside the line above — which read as "English is
    # fine" when what was meant was "English nouns are fine". It carries no
    # romanised Hindi, so the function-word list never fired on it, and Sarvam
    # reads it to a Hindi caller in an English mouth. Counted, never rewritten.
    g8b = guard_mid_call()
    english = "Your full car spa booking slot and address, please."
    assert g8b.check(english) == english
    assert g8b.romanised == [english], g8b.romanised
    # ...but a short Latin chunk is the bot's ordinary vocabulary. The TTS
    # filter sees chunks, not whole turns.
    g8c = guard_mid_call()
    for chunk in ("Full Car Spa Premium", "Basic", "Exterior Only"):
        g8c.check(chunk)
    assert g8c.romanised == [], g8c.romanised

    # A leaked few-shot speaker label is removed, real speech is not.
    g9 = guard_mid_call()
    assert g9.check("M: मैं AI assistant हूँ सर।") == "मैं AI assistant हूँ सर।"
    assert g9.check("Monika: जी बताइए।") == "जी बताइए।"
    assert g9.labels == ["M:", "Monika:"], g9.labels
    g10 = guard_mid_call()
    for untouched in (
        "मैं AI assistant हूँ सर।",
        "Creta है ना? तो करीब 499 रुपये।",
        "सुबह आठ बजे: लिख लिया मैंने।",  # a colon mid-speech is not a label
    ):
        assert g10.check(untouched) == untouched, untouched
    assert g10.labels == [], g10.labels

    print("guardrails ok — allowed prices:", sorted(g.allowed))


if __name__ == "__main__":
    _demo()
