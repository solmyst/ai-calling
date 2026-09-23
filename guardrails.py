"""Output rules every domain shares — model failures, not business rules.

A domain's own guard (domains/<name>/guard.py) owns what that business must
never say: invented car spa prices, an insurance OTP request. What lives here is
what ANY model does wrong on ANY call, whatever it is selling: JSON or markup
read aloud, thinking out loud in English, announcing it is an AI or claiming to
be a person, a leaked speaker label, the wrong script. Both guards import these,
so a fix here reaches every domain at once.

The car spa's PriceGuard lived in this file until 2026-09-23; it is now
domains/car_spa/guard.py.
"""
import os
import re

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

_SENTENCE_RE = re.compile(r"[^.।!?]+[.।!?]?")

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

# The model writing its own scaffolding instead of a spoken turn. Caught live
# 2026-09-22 on GEMINI, not on the small model: asked for the field list it
# answered "/Tone: Natural, spoken Hindi, warm, direct." and then "*   No".
# Both reached the TTS filter, which logged them as merely "romanised" — a
# warning, not a rewrite — so the caller would have heard them read aloud.
#
# Two shapes, and both must be safe against real speech:
#   1. A label header — "/Tone:", "Style:", "Note:" — at the very start of a
#      line, in Latin script only. A Hindi turn does not open with "Word:".
#   2. A line that is ONLY a markdown bullet or list marker plus a word or two,
#      with no Devanagari at all. Real replies are sentences, not "*   No".
# Devanagari anywhere in the line exempts it, because Hinglish prose is the
# product and must never be dropped by a formatting heuristic.
_SCAFFOLD_RE = re.compile(
    r"^\s*[/#*\-]*\s*(?:tone|style|note|format|output|response|reply|answer|"
    r"instruction|constraint|rule|persona|context|task|goal|step)\s*:",
    re.IGNORECASE,
)
_BARE_BULLET_RE = re.compile(r"^\s*(?:[*\-+•]|\d+[.)])\s+\S{1,30}\s*$")

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

# --- announcing that you are an AI -------------------------------------------
# Removed from both prompts on 2026-09-21 at the product owner's instruction:
# the bot introduces itself as Monika from Park+ and does not announce what it
# is. A prompt is advice, so this is the part that guarantees it.
#
# It does NOT license claiming to be a person. Both prompts still forbid that,
# and _SAFE_NOT_AI is the answer to "आप इंसान हो?" — true, not a denial, and it
# does not use the word AI. A bot that argues it is human to a real customer is
# a different and worse thing than one that simply does not raise the subject.
#
# The word "assistant" alone is deliberately NOT a trigger: "मैं Park+ की
# calling assistant हूँ" is the sanctioned reply and must survive.
_SELF_AI_RE = re.compile(
    r"(?:मैं|main|\bI(?:'m| am)\b)[^.।!?]{0,25}?"
    r"\b(?:AI|artificial\s+intelligence|bot|बॉट|robot|रोबोट|मशीन|machine)\b"
    r"|\b(?:AI|bot|बॉट|robot|रोबोट)\s*(?:assistant|असिस्टेंट)?\s*"
    r"(?:हूँ|हूं|हु|hoon|hun)\b"
    r"|\bAI\s+assistant\b",
    re.IGNORECASE,
)

# The other half, and the reason the rule above is safe rather than deceptive.
# Both prompts have forbidden "मैं इंसान हूँ" all along and nothing enforced it.
# Not announcing what you are is a product decision; telling a customer you are
# a person when they ask outright is a lie, and this is a recorded call.
_CLAIMS_HUMAN_RE = re.compile(
    r"(?:मैं|main)\s*[^.।!?]{0,15}?(?:इंसान|इन्सान|आदमी|औरत|human|insaan|person)\s*"
    r"(?:हूँ|हूं|हु|hoon|hun)"
    r"|\bI\s*(?:'m| am)\s+(?:a\s+)?(?:human|real person|person)\b"
    r"|(?:नहीं|nahi+n?)[^.।!?]{0,12}(?:AI|bot|robot|रोबोट)[^.।!?]{0,12}(?:नहीं|nahi+n?)",
    re.IGNORECASE,
)

_SAFE_NOT_AI = "मैं Park+ की calling assistant हूँ सर"

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
    if HINGLISH_REPLIES and _DEVANAGARI_RE.search(text):
        # Under REPLY_SCRIPT=hinglish the drift runs the other way: Devanagari
        # is the wrong script. Recorded only — see KycGuard.check().
        return True
    if _ROMAN_HINDI_RE.search(text):
        # ...unless romanised Hindi is what we asked for. Straight English is
        # still drift in that mode, which is what the length rule below catches.
        return not HINGLISH_REPLIES
    stripped = text.strip()
    if len(stripped) < _ENGLISH_DRIFT_MIN_CHARS:
        return False
    return not _DEVANAGARI_RE.search(stripped)

# --- speaker labels ----------------------------------------------------------
# Few-shot examples in the prompt are written as a transcript, and gpt-oss-20b
# copied the transcript's own label into what it said: the caller heard
# "M: मैं AI assistant हूँ". Reformatting the examples helps; deleting the label
# here is what guarantees it. Only an exact known label at the very start of the
# chunk is removed, so ordinary speech containing a colon is untouched.
_SPEAKER_LABEL_RE = re.compile(
    r"^\s*(?:M|C|A|U|Monika|Shreya|Assistant|Agent|Bot|You|Caller|Customer|"
    r"मोनिका|श्रेया|ग्राहक)\s*:\s*",
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
    r"lagta|lagti|lagega|sakta|sakti|sakte|gaadi|paas|liye|abhi|thoda|"
    # Added 2026-09-23 for REPLY_SCRIPT=hinglish: the sanctioned lines lean on
    # these, and "Theek hai sir" / "click kijiye" read as English without them.
    r"hoon|kijiye|lijiye|theek|haan|dikkat|dijiyega|bataiyega|"
    # ...and the everyday words a short romanised line may carry alone —
    # "Shaam ko karoon ya kal subah?" has none of the above, and the English
    # length rule below was calling it English (A/B 2026-09-23).
    r"ko|se|pe|par|phir|kab|karoon|karun|jaye|jayega|jaayegi|dekhenge|samajh|"
    r"aayi|boliyega|bolenge|dhanyavaad|aapki|aapka|mujhe|kaam)\b",
    re.IGNORECASE,
)


# --- which script the bot replies in -----------------------------------------
# Measured on 2026-09-22, not assumed: the same sentence costs 87 prompt tokens
# in Devanagari and 55 in romanised Hinglish on Park+'s Qwen tokenizer, and a
# Sarvam TTS -> Sarvam STT round trip of eight pairs came back byte-identical
# for seven of them, including pure romanised Hindi with no English in it.
#
# That falsifies the assumption this module was built on ("Sarvam pronounces
# Latin text with an English mouth"), which held for bulbul:v2 and does not
# hold for v3. REPLY_SCRIPT=hinglish therefore makes romanised Hindi the
# intended output rather than a defect. Default stays devanagari.
HINGLISH_REPLIES = (os.getenv("REPLY_SCRIPT") or "devanagari").strip().lower() == "hinglish"



# Stray Devanagari words in an otherwise romanised reply ("aapka naam RC aur
# Aadhaar par jaise है, wahi form mein daalna है" — Park+ Qwen, 2026-09-23).
# Only the commonest function words, and only when the line is mostly Latin:
# a real Devanagari line (or a filler hum) is left alone.
_STRAY_ROMAN = {
    "है": "hai", "हैं": "hain", "नहीं": "nahi", "नही": "nahi", "और": "aur",
    "में": "mein", "का": "ka", "की": "ki", "के": "ke", "को": "ko", "से": "se",
    "भी": "bhi", "तो": "toh", "हो": "ho", "था": "tha", "थी": "thi", "हूँ": "hoon",
    "हूं": "hoon", "जी": "ji", "सर": "sir", "पर": "par", "ही": "hi", "कर": "kar",
    "कि": "ki", "ये": "ye", "वो": "woh", "आप": "aap",
}
_DEVA_WORD_RE = re.compile(r"[\u0900-\u097F]+")


def romanise_strays(text: str) -> str:
    """Under REPLY_SCRIPT=hinglish, swap stray Devanagari function words."""
    if not HINGLISH_REPLIES or not _DEVA_WORD_RE.search(text):
        return text
    latin = len(re.findall(r"[A-Za-z]", text))
    deva = len(re.findall(r"[\u0900-\u097F]", text))
    if latin < deva * 3:
        return text
    return _DEVA_WORD_RE.sub(lambda m: _STRAY_ROMAN.get(m.group(0), m.group(0)), text)

def is_hindi_speech(text: str) -> bool:
    """True when this looks like the bot actually talking to the caller.

    Devanagari used to answer this on its own, which quietly made every rule
    that asked it wrong the moment the replies are romanised: the scaffold
    dropper would have started eating real speech, and the English-goodbye
    rewrite would have fired on every line. Romanised Hindi function words are
    the same evidence in the other script, so both count.
    """
    return bool(_DEVANAGARI_RE.search(text) or _ROMAN_HINDI_RE.search(text))


def is_machine_output(text: str) -> bool:
    """True when this is not a spoken turn at all — JSON, markup, a URL.

    Exposed because two layers need the same answer: the TTS filter, to keep it
    out of the caller's ear, and the LLM service, to keep it out of the history.
    """
    if not text:
        return False
    if _MACHINE_OUTPUT_RE.search(text):
        return True
    # Prompt scaffolding the model wrote instead of speech. Never applied to a
    # line that is speech in EITHER script — Hinglish prose is the product, and
    # under REPLY_SCRIPT=hinglish every line of it is Latin.
    return any(
        not is_hindi_speech(line)
        and (_SCAFFOLD_RE.search(line) or _BARE_BULLET_RE.match(line))
        for line in text.splitlines()
        if line.strip()
    )


def keep_lead(original: str, fixed: str) -> str:
    """Re-attach the leading whitespace a sentence rewrite threw away.

    Every _fix_sentence replacement is a canned line plus a terminator, so it
    arrives with no leading space and the "".join glues it to the sentence
    before it — "...कॉलिंग एजेंट।मैं Park+ की calling assistant हूँ" reached the
    voice as one word run on 2026-09-22.
    """
    lead = original[: len(original) - len(original.lstrip())]
    if fixed and lead and not fixed[:1].isspace():
        return lead + fixed
    return fixed



def _demo():
    # The domain guards test these through their own check(); this is the
    # shared layer on its own, so a regression here names the file it is in.
    for junk in ('{"error": {"code": 429}}', "<speak>नमस्ते</speak>", "```json",
                 "/Tone: Natural, spoken Hindi, warm, direct.", "    *   No"):
        assert is_machine_output(junk), junk
    for speech in ("Creta है ना? तो करीब 499 रुपये, app में exact दिख जाएगा।",
                   "support@myparkplus.com पर लिख दीजिए।", "— हाँ सर, वही button है।",
                   "Park+ app kholkar Insurance icon par click kijiye."):
        assert not is_machine_output(speech), speech
    assert keep_lead(" दूसरा वाक्य।", "canned।") == " canned।"
    assert keep_lead("पहला वाक्य।", "canned।") == "canned।"
    assert keep_lead(" x", "") == ""
    assert _PRICE_RE.search("आपके लिए 450 रुपये लगेंगे।")
    assert _SELF_AI_RE.search("मैं AI assistant बोल रही हूँ।")
    assert not _SELF_AI_RE.search("मैं Park+ की calling assistant हूँ सर।")
    assert _SPEAKER_LABEL_RE.match("M: मैं Monika बोल रही हूँ सर।")
    assert is_hindi_speech("Theek hai sir") and is_hindi_speech("ठीक है सर")
    print("guardrails ok — shared rules")


if __name__ == "__main__":
    _demo()
