"""Deterministic output guard for the post-payment KYC / proposal call.

The car spa guard checks prices and slots. None of that applies here, and the
things that DO apply cost far more when they go wrong: this call is about
identity documents, and the rules come straight from the pack's own
`safety_rules`, not from anyone's judgement.

The product shape this enforces: **the bot talks the customer into the app, it
does not collect identity on the phone.** Uploads and sensitive IDs go through
the approved digital path. So every rule below is about what the bot must not
ASK for, which is the opposite of the car spa guard — that one polices claims the
bot makes, this one polices requests the bot makes.

Why deterministic and not prompt-only: a prompt is advice, and the one turn where
the model improvises "aapka Aadhaar number bata dijiye" is a compliance incident
on a recorded call. Same reasoning as the price guard, higher stakes.
"""

import json
import re

from domain import CONTEXT_FILE

# --- asking for an OTP --------------------------------------------------------
# safety_rules: "Never ask for OTP on the call." Non-negotiable and the single
# most abuse-shaped thing a voice bot can say — it is exactly what a vishing
# call sounds like, so a customer hearing it should hang up, and Park+ should
# never be the reason they learned to trust it.
_OTP_RE = re.compile(
    r"\bOTP\b|one[\s-]?time[\s-]?password|ओटीपी|"
    r"(?:code|कोड)\s+(?:jo|जो|which|that)?\s*(?:aaya|आया|mila|मिला|received)",
    re.IGNORECASE,
)
_SAFE_OTP = (
    "OTP मैं कभी नहीं माँगूँगी सर — वो सिर्फ़ app में डालना होता है, किसी को बताना नहीं है"
)

# --- asking for an identity number by voice -----------------------------------
# The pack allows PAN/Aadhaar as `sensitive_id_voice` fields, but the product
# decision is that they are completed in the app. So the bot asks for none of
# them on the call. Requires a REQUEST shape, so the bot can still say "Aadhaar
# app में upload करना होगा" — that is the handoff, which is the whole point.
_SENSITIVE_ID = r"aadhaar|आधार|\bPAN\b|पैन|GSTIN|जीएसटी|\bCIN\b"
_ASK_SHAPE = (
    r"\?|बता\s*(?:दीजिए|दो|दें|इए)|बताइए|बोल\s*(?:दीजिए|दो)|"
    r"क्या\s+है|कितना\s+है|share\s+(?:kar|कर)|tell\s+me|what\s+is\s+your|"
    r"नंबर\s+(?:दे|बता)|number\s+(?:de|bata)"
)
_SAFE_SENSITIVE_ID = (
    "वो number मुझे फ़ोन पर नहीं चाहिए सर — app में safe तरीक़े से डाल दीजिए, "
    "link भेज देती हूँ"
)
# ...but the bot's JOB is to walk the customer through a screen that HAS a PAN
# field on it. Caught live 19:53: "स्क्रीन पर अभी कौन सा field खाली दिख रहा है सर
# — जैसे Nominee नाम, Address, या PAN card details?" was blocked and replaced,
# so the customer was never told which field to look at.
#
# The rule is about the bot asking the customer to SPEAK a number. Naming a field
# on their screen, or telling them to type it into the app, is the product. So a
# sentence that is clearly about the SCREEN is exempt.
_APP_CONTEXT = (
    r"screen|स्क्रीन|field|फ़ील्ड|फील्ड|page|पेज|section|सेक्शन|app|ऐप|"
    r"भर\s*(?:दीजिए|दो|दें|ना)|fill|डाल\s*(?:दीजिए|दो|दें)|enter|type|"
    r"खाली|blank|दिख\s*रहा|upload"
)

# --- asking for documents over the wrong channel ------------------------------
# safety_rules: never ask for images over general WhatsApp/email/chat unless that
# is the approved KYC path for the case. The bot has no way to know that from a
# voice turn, so it may not offer those channels at all — only "the app" or "the
# link", which is what the runtime actually provides.
_DOC_CHANNEL_RE = re.compile(
    r"(?:whatsapp|व्हाट्सएप|वॉट्सऐप|email|ईमेल|mail\s+kar|मेल\s+कर|"
    r"message\s+kar|भेज\s*दीजिए|send\s+me)",
    re.IGNORECASE,
)
_DOC_WORD = r"photo|फोटो|फ़ोटो|image|तस्वीर|document|दस्तावेज़|scan|aadhaar|आधार"
# "copy" was in that list and cost a real turn. Caught live 23:21: "आप अपना ही
# Email ID डाल दीजिए जिस पर आपको पॉलिसी की copy चाहिए।" was blocked, because
# "email" matched the channel and "copy" matched the document. Email Id is a
# FIELD on this form and the policy copy is what gets sent to it — the bot has to
# be able to say that. The rule is about SENDING documents to Park+ over an
# unapproved channel, so a sentence about filling the Email Id field is exempt.
_FORM_FIELD_CONTEXT = (
    r"field|फ़ील्ड|फील्ड|Email\s*(?:Id|ID)|डाल\s*(?:दीजिए|दो|दें)|भर\s*(?:दीजिए|दो|दें)|"
    r"enter|type|fill|screen|स्क्रीन|page|पेज"
)
_SAFE_DOC_CHANNEL = (
    "Documents app के KYC section में upload कीजिए सर — मैं वहीं का link भेज देती हूँ"
)

# --- declaring KYC done -------------------------------------------------------
# safety_rules: "Never mark KYC/proposal complete from verbal confirmation
# alone." The customer saying "kar diya" is not evidence; the owning system is.
# Identical in spirit to the car spa's false-booking guard and it exists for the
# same reason: a customer told they are done stops checking.
_DONE_WORD = r"KYC|केवाईसी|proposal|प्रपोजल|प्रोपोजल|verification|वेरिफिकेशन"
# गई as well as गया/गयी — "आपकी KYC हो गई है" leaked past this for a while
# because only the गय- spellings were listed. Hindi writes the feminine both
# ways and a customer told their KYC is done stops checking either way.
_DONE_MARKER = (
    r"complete|पूर[ाी]\s*हो\s*ग[यई]|हो\s*ग[यई][ाीे]?|ho\s*gay[ai]|done|"
    r"successful|सफल|अप्रूव|approved|verified|वेरीफाई"
)
_SAFE_DONE = (
    "मैं system में check करके confirm करूँगी सर — अभी complete नहीं बोल सकती"
)
# The app has a button literally labelled "Complete KYC". Telling someone to
# press it is an instruction, not a claim that their KYC is done. Caught live
# 19:53: "...अपनी policy पर click करके Complete KYC दबा दीजिए।" was rewritten
# into "मैं system में check करके confirm करूँगी", which drops the one thing the
# customer needed to hear. A sentence telling them to press or tap something is
# exempt.
# A NEGATED sentence is the opposite of a completion claim, and blocking it is
# worse than useless. Caught live 00:18, twice in one call:
#   "सर, KYC complete नहीं होगी तो आपका policy document issue नहीं हो पाएगा।"
#   "सर, अगर आप KYC complete नहीं करते हैं, तो आपकी policy issue नहीं होगी।"
# Both are correct answers to "what happens if I don't do it" and both were
# replaced with "मैं system में check करके confirm करूँगी", which answers a
# question nobody asked. Worse, the guard also rewrote "आपका KYC अभी complete
# नहीं हुआ है" — its OWN safe sentence.
#
# The rule is "never CLAIM it is done". Negation next to the completion verb is
# the opposite of that claim, so it is exempt. The negation has to be adjacent,
# so "KYC complete हो गया है, कोई दिक्कत नहीं" is still blocked.
_NEGATED_DONE = re.compile(
    r"(?:complete|पूरा|पूरी|हो|done|issue)\s*(?:नहीं|नही|nahi+n?|ना)|"
    r"नहीं\s*(?:हुआ|हुई|होगी|होगा|होती|करते|करेंगे|किया|कर\s*पाए)|"
    r"not\s+(?:complete|done|verified)",
    re.IGNORECASE,
)

_UI_ACTION = (
    r"दबा\s*(?:दीजिए|दो|दें|इए)|tap|click|press|button|बटन|option|विकल्प|"
    r"select|चुन|खोल\s*(?:िए|ो)|open|जाइए|जाके|जाकर"
)

# --- promising issuance or money ----------------------------------------------
# safety_rules: "No promises of issuance timing or refund approval." A policy
# date the bot invents is the thing the customer plans around.
_PROMISE_RE = re.compile(
    r"(?:policy|पॉलिसी|issue|इशू|जारी|refund|रिफंड|पैसे|amount|claim|क्लेम)",
    re.IGNORECASE,
)
_PROMISE_MARKER = re.compile(
    r"\b(?:today|tomorrow|आज|कल|परसों|within|में\s*ही|तुरंत|immediately|"
    r"\d+\s*(?:hours?|days?|घंटे|दिन)|guarantee|गारंटी|पक्का|मिल\s*जाएग[ाी]|"
    r"हो\s*जाएग[ाी])\b",
    re.IGNORECASE,
)
_SAFE_PROMISE = (
    "उसका timing मैं यहाँ से confirm नहीं कर सकती सर — team update कर देगी"
)

# --- inventing an authority or a money consequence ----------------------------
# Both verbatim from the 00:50 call, on the commonest objection of all ("अभी
# टाइम नहीं है, न करूँ तो क्या?"):
#
#   "KYC complete किए बिना IRDAI के नियमों के मुताबिक बीमा कंपनी पॉलिसी issue नहीं कर सकती"
#   "बिना KYC के insurer से पॉलिसी डॉक्यूमेंट रिलीज़ ही नहीं होगा, पेमेंट stuck रह जाएगा"
#
# Neither is in context.json. The bot reached for a scarier reason than the true
# one and invented a regulation, then a stuck payment. Citing a regulator to
# pressure someone into acting, on a recorded call, is the worst thing in this
# file: it is false, it is coercive, and it is quotable in a complaint.
#
# There is no exemption. The bot never has a legitimate reason to name a
# regulator or to tell a customer their money is at risk — the true answer is
# _SAFE_AUTHORITY, which is also what the prompt now scripts.
_AUTHORITY_RE = re.compile(
    r"\bIRDAI?\b|आईआरडीए|\bRBI\b|आरबीआई|regulator|रेगुलेटर|"
    r"(?:के\s+)?नियम(?:ों)?\s+के\s+(?:मुताबिक|अनुसार)|"
    r"as\s+per\s+(?:the\s+)?(?:law|regulation)|क़ानून|कानून|"
    r"mandat(?:ory|ed)\s+by|सरकार\s+(?:के|ने)",
    re.IGNORECASE,
)
# "payment हो चुका है" must survive — it is the line that proves the call is
# real. Only a payment paired with a LOSS word is a fabricated consequence.
_MONEY_AT_RISK_RE = re.compile(
    r"(?:payment|पेमेंट|पैसा|पैसे|amount|रक़म|रकम|refund|रिफंड|premium|प्रीमियम)"
    r"[^.।!?]{0,40}"
    r"(?:stuck|अटक|फँस|फंस|block|ब्लॉक|ज़ब्त|जब्त|डूब|लैप्स|lapse|"
    r"वापस\s+नहीं|waste|बर्बाद|ज़ाया)",
    re.IGNORECASE,
)
_SAFE_AUTHORITY = (
    "सर, payment तो हो चुका है — बस KYC complete हुए बिना policy issue नहीं हो पाती"
)

_SENTENCE_RE = re.compile(r"[^.।!?]+[.।!?]?")


class KycGuard:
    """Rewrites any sentence that breaks a KYC calling safety rule.

    Same interface as the car spa's PriceGuard so the TTS filter and the call
    observer do not care which domain is loaded: `check()`, `note_caller()`, and
    a COUNTERS table naming what to log when a rule fires.
    """

    COUNTERS = (
        ("otp_asks", "error", "BLOCKED an OTP request"),
        ("sensitive_id_asks", "error", "BLOCKED asking for an ID number by voice"),
        ("wrong_channel_asks", "error", "BLOCKED a document request over whatsapp/email"),
        ("false_completions", "error", "rewrote a KYC/proposal claimed as complete"),
        ("promises", "error", "rewrote an issuance/refund promise"),
        ("invented_authority", "error",
         "rewrote an invented regulator rule or money-at-risk claim"),
        ("machine_output", "error", "DROPPED non-speech output"),
        ("self_narration", "error", "DROPPED the model thinking out loud"),
    )

    def __init__(self, ctx: dict | None = None):
        ctx = ctx or json.loads(CONTEXT_FILE.read_text())
        self.insurers = ctx["insurers"]
        self.upload_only = set(ctx["field_groups"]["upload_only"])
        self.otp_asks: list[str] = []
        self.sensitive_id_asks: list[str] = []
        self.wrong_channel_asks: list[str] = []
        self.false_completions: list[str] = []
        self.promises: list[str] = []
        self.invented_authority: list[str] = []
        self.machine_output: list[str] = []
        self.self_narration: list[str] = []

    def note_caller(self, text: str) -> bool:
        """Nothing the CALLER says unlocks anything on this call.

        Present because the observer calls it for every domain. The car spa
        needed it — a price is gated on the caller naming a car. Here every rule
        is about what the BOT may ask for, which no customer utterance changes.
        """
        return False

    def check(self, text: str) -> str:
        """Return text safe to speak, recording anything that was suppressed."""
        # Reuse the shared non-speech and thinking-out-loud rules; they are
        # model failures, not domain rules, and both were caught on live calls.
        from guardrails import _MACHINE_OUTPUT_RE, _SELF_NARRATION_RE, _DEVANAGARI_RE

        if _MACHINE_OUTPUT_RE.search(text):
            self.machine_output.append(text.strip())
            return ""
        out = []
        for sentence in _SENTENCE_RE.findall(text):
            if _SELF_NARRATION_RE.search(sentence) and not _DEVANAGARI_RE.search(sentence):
                self.self_narration.append(sentence.strip())
                continue
            out.append(self._fix_sentence(sentence))
        return "".join(out)

    def _fix_sentence(self, sentence: str) -> str:
        terminator = sentence[len(sentence.rstrip(".।!?")):] or "।"

        if _OTP_RE.search(sentence):
            self.otp_asks.append(sentence.strip())
            return _SAFE_OTP + terminator

        if (
            re.search(_SENSITIVE_ID, sentence, re.IGNORECASE)
            and re.search(_ASK_SHAPE, sentence, re.IGNORECASE)
            and not re.search(_APP_CONTEXT, sentence, re.IGNORECASE)
        ):
            self.sensitive_id_asks.append(sentence.strip())
            return _SAFE_SENSITIVE_ID + terminator

        if (
            _DOC_CHANNEL_RE.search(sentence)
            and re.search(_DOC_WORD, sentence, re.IGNORECASE)
            and not re.search(_FORM_FIELD_CONTEXT, sentence, re.IGNORECASE)
        ):
            self.wrong_channel_asks.append(sentence.strip())
            return _SAFE_DOC_CHANNEL + terminator

        if (
            re.search(_DONE_WORD, sentence, re.IGNORECASE)
            and re.search(_DONE_MARKER, sentence, re.IGNORECASE)
            and not re.search(_UI_ACTION, sentence, re.IGNORECASE)
            and not _NEGATED_DONE.search(sentence)
        ):
            self.false_completions.append(sentence.strip())
            return _SAFE_DONE + terminator

        if _AUTHORITY_RE.search(sentence) or _MONEY_AT_RISK_RE.search(sentence):
            self.invented_authority.append(sentence.strip())
            return _SAFE_AUTHORITY + terminator

        if _PROMISE_RE.search(sentence) and _PROMISE_MARKER.search(sentence):
            self.promises.append(sentence.strip())
            return _SAFE_PROMISE + terminator

        return sentence


#: What domain.build_guard() constructs.
GUARD = KycGuard


def _demo():
    g = KycGuard()

    # The five rules, each in the shape a model actually produces.
    blocked = [
        ("otp_asks", "सर आपको जो OTP आया है वो बता दीजिए।"),
        ("otp_asks", "Please share the one-time password."),
        ("sensitive_id_asks", "आपका Aadhaar number बता दीजिए सर।"),
        ("sensitive_id_asks", "What is your PAN?"),
        ("wrong_channel_asks", "Aadhaar की photo WhatsApp पर भेज दीजिए।"),
        ("false_completions", "आपका KYC complete हो गया है सर।"),
        ("promises", "पॉलिसी कल तक issue हो जाएगी।"),
        # Both verbatim from the 00:50 call.
        ("invented_authority",
         "सर, payment हो गई है, पर KYC complete किए बिना IRDAI के नियमों के "
         "मुताबिक बीमा कंपनी पॉलिसी issue नहीं कर सकती।"),
        ("invented_authority",
         "सर, बिना KYC के insurer से पॉलिसी डॉक्यूमेंट रिलीज़ ही नहीं होगा, "
         "पेमेंट stuck रह जाएगा।"),
    ]
    for counter, line in blocked:
        before = len(getattr(g, counter))
        out = g.check(line)
        assert len(getattr(g, counter)) == before + 1, f"{counter} missed: {line!r}"
        assert out != line, f"not rewritten: {line!r}"

    # ...and the lines the bot MUST still be able to say, because they are the
    # product: pointing the customer at the app. The first two are VERBATIM from
    # the 19:53 call, where the guard rewrote both and left the customer with no
    # instruction at all.
    g2 = KycGuard()
    for ok in (
        "App में नीचे Insurance section पर tap कीजिए, फिर अपनी policy पर click "
        "करके Complete KYC दबा दीजिए।",
        "स्क्रीन पर अभी कौन सा field खाली दिख रहा है सर — जैसे Nominee नाम, "
        "Address, या PAN card details?",
        "PAN Number वाले field में अपना PAN भर दीजिए सर।",
        "आप अपना ही Email ID डाल दीजिए जिस पर आपको पॉलिसी की copy चाहिए।",
        # Verbatim from the 00:18 call — the bot answering "what if I don't
        # complete it", which is a question customers really ask.
        "सर, KYC complete नहीं होगी तो आपका policy document issue नहीं हो पाएगा।",
        "सर, अगर आप KYC complete नहीं करते हैं, तो आपकी policy issue नहीं होगी।",
        "आपका KYC अभी complete नहीं हुआ है।",
        "Aadhar Number का field app में ही भरना है।",
        "Aadhaar app के KYC section में upload करना होगा सर।",
        "मैं आपको link भेज देती हूँ, वहीं से complete कर लीजिए।",
        "अभी name और email pending है आपका।",
        "Park+ Insurance से Monika बोल रही हूँ।",
        "Payment हो चुका है, बस KYC बाक़ी है।",
        # The sanctioned answer to "अगर न करूँ तो?", the one the prompt now
        # scripts. It names the payment AND the consequence, so it brushes past
        # both new patterns and must survive them.
        "सर, payment तो हो चुका है — पर KYC complete हुए बिना policy issue नहीं "
        "हो पाती।",
        "नॉमिनी का नाम app में डाल दीजिए।",
    ):
        assert g2.check(ok) == ok, f"blocked a legitimate line: {g2.check(ok)!r}"
    assert not any(getattr(g2, c) for c, _, _ in KycGuard.COUNTERS), "false positive"

    # Only the offending sentence is replaced; the rest of the turn survives.
    g3 = KycGuard()
    mixed = g3.check("जी सर। आपका OTP बता दीजिए। और कुछ?")
    assert "जी सर।" in mixed and "और कुछ?" in mixed and "OTP बता" not in mixed, mixed

    print(f"insurance guard ok — {len(KycGuard.COUNTERS)} rules, "
          f"{len(g.insurers)} insurers, upload-only: {sorted(g.upload_only)}")


if __name__ == "__main__":
    _demo()
