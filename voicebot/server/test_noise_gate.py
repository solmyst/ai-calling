"""What counts as a turn, and what is just a noise the caller made.

    python test_noise_gate.py

The line this draws is narrow on purpose. A dropped backchannel costs nothing;
a dropped ANSWER costs the call, because "हाँ" is the whole reply to "page खुल
गया?" and the bot would sit there waiting for it. So the Hindi set holds only
sounds that carry no information, and every one-word answer is asserted to
survive.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bot import NoiseGate  # noqa: E402

# Noises. "ओह" is verbatim from the 14:55 call, where it arrived two seconds
# after a real question and earned a whole second reply — the bot answered
# twice in a row with nobody having asked anything.
NOISE = [
    "ओह", "ओह!", "हम्म", "अरे", "अच्छा", "अच्छा।", "ओह अच्छा", "हम्म हम्म",
    "", "   ",
    "uh", "um", "hmm", "thank you", "thanks for watching",
    # The same sounds as Park+'s ASR spells them. It returns romanised Hindi,
    # not Devanagari, so with PARKPLUS_STT_URL set these are the ONLY spellings
    # that ever arrive.
    "oh", "ohh", "achha", "acha", "arre", "umm", "oh achha",
]

# Turns. Every one of these is a real reply and must reach the model.
TURNS = [
    # One-word answers. These are why the Hindi set stays tiny.
    "हाँ", "नहीं", "ठीक है", "हो गया", "नहीं दिख रहा",
    # Verbatim from the 14:55 call.
    "हाँ बताओ आगे बताओ कर दिया मैंने",
    "मेरे को तो नहीं दिख रहा कंप्लीट के वैसे के बटन कहाँ पर है?",
    "हम्म ठीक है कर दिया वो मैंने आगे बताओ",
    "अच्छा तो मेरा KYC हो गया ना अब? पॉलिसी कब तक आ जाएगी?",
    "ठीक है ये नॉमिनी में किसका नाम डालना है",
    # A backchannel word that starts a real sentence is a real turn.
    "अच्छा ये बताओ इसमें क्या क्या लगेगा",
    "ओह तो अब क्या करूँ",
    # Romanised one-word ANSWERS. Every one of these is a complete reply to
    # "page khul gaya?" and dropping one leaves the bot waiting for something
    # the caller has already said.
    "haan", "nahi", "theek hai", "ho gaya", "ok", "ji haan",
    "nahi dikh raha", "haan bataao aage",
    "achha ye batao isme kya kya lagega",
]


def _demo():
    for text in NOISE:
        assert NoiseGate._is_noise(text), f"should have been dropped: {text!r}"
    for text in TURNS:
        assert not NoiseGate._is_noise(text), f"a real turn was dropped: {text!r}"

    # The bug that made half the Hindi set unreachable: [^\w\s] deletes
    # Devanagari combining marks, because Python's \w excludes category Mn. So
    # "अच्छा" normalised to "अचछ" and matched nothing in the set.
    import re
    assert re.sub(r"[^\w\s]", "", "अच्छा") != "अच्छा", \
        "if this ever stops being true the punctuation strip can be simplified"

    print(f"noise gate ok — {len(NOISE)} noises dropped, {len(TURNS)} turns kept")


if __name__ == "__main__":
    _demo()
