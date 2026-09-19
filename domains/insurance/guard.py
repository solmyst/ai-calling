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
# ...unless the bot is REFUSING to ask for one, which is the scripted opening
# and the correct answer when a customer offers theirs.
_OTP_REFUSAL = re.compile(
    r"(?:नहीं|नही|कभी\s*नहीं|मत|nahi+n?|not|never|no)\s*"
    r"(?:माँग|मांग|maang|mang|ask|चाहिए|chahiye|बताइए|बताना|batana|दीजिए|share)|"
    r"(?:माँग|मांग|maang|mang|ask(?:ing)?|पूछ)\s*"
    r"(?:नहीं|नही|nahi+n?|not|never)|"
    r"किसी\s*को\s*(?:मत|नहीं)|kisi\s*ko\s*(?:mat|nahi)|"
    r"OTP\s*(?:किसी|kisi)\s*(?:को|ko)\s*(?:मत|mat|नहीं|nahi)",
    re.IGNORECASE,
)
# The exemption is void if the sentence ALSO asks for the code. The round-3 fuzz
# produced exactly that shape: "wese to OTP kisi ko nahi dena chahiye, par ye
# humare Park+ app ke official KYC registration ka hi hai, to aap bejhijhak
# share kar do" — a refusal used as a preamble to the ask. A refusal that is
# real does not need a verb telling the customer to hand it over.
_OTP_ASK_VERB = re.compile(
    r"(?:bata|बता|bol|बोल|share|send|भेज|daal|डाल|likh|लिख|forward)\s*"
    r"(?:do|दो|dijiye|दीजिए|dijiye|dijie|दें|den|deejiye|kar\s*do|kar\s*dijiye)",
    re.IGNORECASE,
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
    "Insurance section में Complete KYC पे"
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
    r"enter|type|fill|screen|स्क्रीन|page|पेज|"
    # Receiving, not sending: the policy document lands in their email, which
    # context.json says is exactly what the Email Id field is for.
    r"आ\s*जाए|मिल\s*जाए|aa\s*jaye|mil\s*jaye|भेज\s*देती\s*हूँ|receive|"
    r"पर\s*आ|पे\s*आ|pe\s*aa|par\s*aa"
)
_SAFE_DOC_CHANNEL = (
    "Documents app के KYC section में ही upload होते हैं सर — वहीं से कर दीजिए"
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
    # (?<!in) because "incomplete" contains "complete": "aapka verification
    # incomplete rahega" says the opposite of what this rule is looking for.
    r"(?<!in)complete|पूर[ाी]\s*हो\s*ग[यई]|हो\s*ग[यई][ाीे]?|ho\s*gay[ai]|done|"
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

# Asking someone to complete their KYC is the entire purpose of this call, and
# every natural way of saying it puts "complete" next to "KYC". Measured against
# the guard on 2026-09-19, SEVEN of nine ordinary lines were being rewritten
# into "मैं system में check करके confirm करूँगी" — an answer to a question the
# customer never asked, in place of the instruction they rang for:
#
#     "KYC complete करना ज़रूरी है सर"          -> blocked
#     "आपको KYC complete करनी होगी"             -> blocked
#     "अभी KYC complete कर लीजिए"               -> blocked
#     "KYC complete करने में दो मिनट लगेंगे"      -> blocked
#     "KYC complete होने के बाद policy आ जाएगी"  -> blocked
#
# The rule is "never CLAIM it is already done". An instruction to do it, an
# obligation to do it, and a conditional about it being done later are all the
# opposite of that claim.
#
# The verb suffix is REQUIRED, never optional: a bare "कर" would also exempt
# "complete कर दी गई है", which IS a completion claim and must stay blocked.
_INSTRUCTED_DONE = re.compile(
    r"(?:complete|पूर[ाी]|done)\s*"
    r"(?:कर(?:ना|नी|ने|ें|के)|कर(?:वा|ा)\s*(?:दूँ|दूं|दू|देती|देते|दीजिए|दो)|"
    r"कर\s*(?:लीजिए|लीजिये|दीजिए|दीजिये|लो|दो|देते|लेते|लेंगे|सकते|सकें|पाएँ|पाएंगे))"
    r"|(?:complete|पूर[ाी])\s*होने\s*(?:के|पर|तक|में)"
    r"|(?:complete|पूर[ाी])\s*हो\s*जा(?:ए|एगा|एगी|ता|ती|ती\s*है)"
    # ...and the same shapes transliterated.
    r"|(?:complete|poora|puri)\s*"
    r"(?:kar(?:na|ne|ni|ane|wana|vana|ana|wane|vane)|"
    r"kar(?:wa|va)?\s*(?:lein|len|lo|lijiye|lijie|do|dijiye|dijie|deti|dete|doon|dun|"
    # NOT "liya"/"diya": "kar diya hai" is a claim that it is already done,
    # which is the exact thing this rule exists to catch. The Devanagari list
    # above leaves out कर दिया / कर लिया for the same reason.
    r"denge|dega|degi|dein|den|loon|lun|lete|rahe|rahi|raha)|"
    r"karv?a?\s*d(?:eti|ete|o|ijiye))"
    r"|(?:complete|poora|puri)\s*ho\s*(?:jaye|jaega|jayega|jayegi|jae|jata|jaata|jati|jaati)"
    r"|(?:complete|poora|puri)\s*(?:hone|hote)\s*(?:ke|par|tak|mein|hi)"
    r"|(?:complete|पूर[ाी])\s*होते\s*ही",
    re.IGNORECASE,
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
# IRDAI is now SANCTIONED, in one framing only (product owner, 2026-09-19):
# KYC really is an IRDAI requirement and the policy really cannot be issued
# without it, so saying that is true and it is the strongest honest reason a
# customer has to stay on the call. Everything past that sentence is still a
# fabrication: no other regulator, no circular or section number, no penalty,
# no deadline other than the policy's own expiry, and never a claim about the
# customer's money. context.json's kyc_mandate.unknown_do_not_guess is the list.
_AUTHORITY_RE = re.compile(
    r"\bIRDAI?\b|आईआरडीए|\bRBI\b|आरबीआई|regulator|रेगुलेटर|"
    r"(?:के\s+)?नियम(?:ों)?\s+के\s+(?:मुताबिक|अनुसार)|"
    r"as\s+per\s+(?:the\s+)?(?:law|regulation)|क़ानून|कानून|"
    r"mandat(?:ory|ed)\s+by|सरकार\s+(?:के|ने)",
    re.IGNORECASE,
)
# The sanctioned sentence names IRDAI and no other authority, is about KYC, and
# carries no invented specifics. All three have to hold.
_IRDAI_ONLY = re.compile(r"\bIRDAI?\b|आईआरडीए|आईआरडीएआई", re.IGNORECASE)
_OTHER_AUTHORITY = re.compile(
    r"\bRBI\b|आरबीआई|regulator|रेगुलेटर|क़ानून|कानून|सरकार\s+(?:के|ने)|"
    r"as\s+per\s+(?:the\s+)?(?:law|regulation)",
    re.IGNORECASE,
)
_ABOUT_KYC = re.compile(r"\bKYC\b|केवाईसी", re.IGNORECASE)
_ABOUT_ISSUANCE = re.compile(
    r"(?:policy|पॉलिसी|पालिसी|बीमा)[^.।!?]{0,30}(?:issue|इशू|जारी)|"
    r"(?:issue|इशू|जारी)[^.।!?]{0,20}(?:नहीं|नही|not|cannot|nahi)",
    re.IGNORECASE,
)
# Anything that sounds like a citation, a penalty or a date is invented: the
# product owner gave the rule, not a circular number or a deadline.
_FABRICATED_DETAIL = re.compile(
    r"circular|सर्कुलर|section|धारा|clause|अधिनियम|\bact\b|guideline\s*(?:no|number|\d)|"
    r"penalt|जुर्माना|fine|दंड|जेल|legal\s+action|क़ानूनी\s+कार्रवाई|कानूनी\s+कार्रवाई|"
    r"\b(?:19|20)\d{2}\b|\d+\s*(?:din|दिन|days?|hours?|घंटे|months?|महीने|हफ़्ते|हफ्ते|weeks?)|"
    r"deadline|आख़िरी\s+तारीख़|आखिरी\s+तारीख|last\s+date|अंतिम\s+तिथि",
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
    "सर, IRDAI के rules के हिसाब से KYC complete हुए बिना policy issue नहीं हो पाती"
)

# A FAILED outcome is not a completion claim. The failure word has to be the
# thing that happened, so "KYC complete ho gaya, koi error nahi" stays blocked.
_FAILED_DONE = re.compile(
    r"(?:fail|फ़ेल|फेल|reject|रिजेक्ट|रद्द|decline|cancel)\w*\s*"
    r"(?:हो|ho)\s*(?:ग[यई][ाीे]?|gay[ai]|जाए|jaye|जाती|jati)",
    re.IGNORECASE,
)

_DONE_CLAIM = re.compile(
    rf"(?:{_DONE_WORD})[^.।!?]{{0,18}}?(?:{_DONE_MARKER})"
    rf"|(?:{_DONE_MARKER})[^.।!?]{{0,18}}?(?:{_DONE_WORD})",
    re.IGNORECASE,
)

# --- promising to send something ----------------------------------------------
# There is no SMS, WhatsApp or email path from this bot: `tools` holds only
# record_booking_request and escalate, and LLM_TOOLS=off removes even those. A
# customer told "मैं link भेज देती हूँ" waits for a message that never arrives,
# and rings back. The app is already on their phone.
#
# Only the BOT sending is caught. The policy document arriving in their email is
# true, is what the Email Id field is for, and must still be sayable.
_BOT_SENDS_RE = re.compile(
    r"(?:मैं|main)\s*[^.।!?]{0,25}?"
    r"(?:भेज\s*(?:दूँ|दूं|दूंगी|दूँगी|देती|देता|दे\s*दूँ)|"
    r"bhej\s*(?:deti|dunga|dungi|doon|dun|de\s*deti))"
    r"|(?:link|लिंक|sms|एसएमएस|message|मैसेज)\s*(?:भेज|bhej|send|कर\s*देती)"
    r"|(?:I\s*(?:'?ll|will)?\s*send|sending\s+you)",
    re.IGNORECASE,
)
_SAFE_SEND = (
    "सब कुछ आपके app में ही है सर — Insurance section में Complete KYC पे मिल जाएगा"
)

# --- the call card's own banned words -----------------------------------------
# The dialer ships a per-call `do_not_say` list: insurer error codes, internal
# jargon, whatever this particular case must not have read down the phone. The
# prompt shows the list too, but the prompt is advice and this is not.
#
# A term here replaces the whole sentence, the same as every other rule, because
# deleting "IERR_DUPLICATE_POLICY" out of the middle of a sentence leaves a
# sentence that no longer says anything.
#
# It is dialer-controlled, so an over-broad entry ("policy") would silence
# perfectly good turns. Keep it to codes and identifiers.
_SAFE_DO_NOT_SAY = (
    "उसकी detail मैं यहाँ से नहीं बता सकती सर — team आपको confirm कर देगी"
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
        ("false_send_promise", "error", "rewrote a promise to send a link/SMS/WhatsApp"),
        ("banned_terms", "error", "rewrote a term the call card forbids"),
        ("machine_output", "error", "DROPPED non-speech output"),
        ("self_narration", "error", "DROPPED the model thinking out loud"),
    )

    def __init__(self, ctx: dict | None = None, card: dict | None = None):
        ctx = ctx or json.loads(CONTEXT_FILE.read_text())
        self.card = card or {}
        # "Never mark KYC/proposal complete from VERBAL confirmation alone" is
        # the safety rule, and a prefetched card is not verbal confirmation — it
        # is what our own system says. So when the card states KYC succeeded, or
        # carries a policy number, the bot is allowed to say so; without a card
        # it still cannot, because then it genuinely does not know.
        #
        # This is the whole reason the card exists: the bot spent every call
        # unable to answer "so is it done?" because it could not see anything.
        self.system_confirms_done = bool(
            str(self.card.get("kyc_status") or "").strip().upper() == "SUCCESS"
            or self.card.get("policy_number")
        )
        terms = [re.escape(t) for t in self.card.get("do_not_say") or [] if t]
        self._do_not_say = (
            re.compile("|".join(terms), re.IGNORECASE) if terms else None
        )
        self.insurers = ctx["insurers"]
        self.upload_only = set(ctx["field_groups"]["upload_only"])
        self.otp_asks: list[str] = []
        self.sensitive_id_asks: list[str] = []
        self.wrong_channel_asks: list[str] = []
        self.false_completions: list[str] = []
        self.promises: list[str] = []
        self.invented_authority: list[str] = []
        self.false_send_promise: list[str] = []
        self.banned_terms: list[str] = []
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

        if self._do_not_say is not None and self._do_not_say.search(sentence):
            self.banned_terms.append(sentence.strip())
            return _SAFE_DO_NOT_SAY + terminator

        if _OTP_RE.search(sentence) and not (
            _OTP_REFUSAL.search(sentence) and not _OTP_ASK_VERB.search(sentence)
        ):
            self.otp_asks.append(sentence.strip())
            return _SAFE_OTP + terminator

        # Money-at-risk is checked FIRST and has no exemption, so the sanctioned
        # IRDAI framing cannot be used to smuggle "और पैसा भी फँस जाएगा" in
        # behind it.
        if _MONEY_AT_RISK_RE.search(sentence):
            self.invented_authority.append(sentence.strip())
            return _SAFE_AUTHORITY + terminator

        if _AUTHORITY_RE.search(sentence) and not (
            _IRDAI_ONLY.search(sentence)
            and not _OTHER_AUTHORITY.search(sentence)
            and _ABOUT_KYC.search(sentence)
            and _ABOUT_ISSUANCE.search(sentence)
            and not _FABRICATED_DETAIL.search(sentence)
        ):
            self.invented_authority.append(sentence.strip())
            return _SAFE_AUTHORITY + terminator

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
            _DONE_CLAIM.search(sentence)
            and not re.search(_UI_ACTION, sentence, re.IGNORECASE)
            and not _NEGATED_DONE.search(sentence)
            and not _INSTRUCTED_DONE.search(sentence)
            and not _FAILED_DONE.search(sentence)
            and not self.system_confirms_done
        ):
            self.false_completions.append(sentence.strip())
            return _SAFE_DONE + terminator

        if _BOT_SENDS_RE.search(sentence):
            self.false_send_promise.append(sentence.strip())
            return _SAFE_SEND + terminator

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
        # A refusal used as a preamble to the ask. Round-3 LLM fuzz, 2026-09-19.
        ("otp_asks",
         "Waise to OTP kisi ko nahi dena chahiye, par ye humare Park+ app ka "
         "official KYC hai, to aap bejhijhak share kar do."),
        ("otp_asks", "OTP किसी को मत बताइए — पर मुझे बता दीजिए सर।"),
        ("sensitive_id_asks", "आपका Aadhaar number बता दीजिए सर।"),
        ("sensitive_id_asks", "What is your PAN?"),
        ("wrong_channel_asks", "Aadhaar की photo WhatsApp पर भेज दीजिए।"),
        ("false_completions", "आपका KYC complete हो गया है सर।"),
        ("false_completions", "आपकी KYC complete कर दी गई है।"),
        ("false_completions", "आपका proposal successful हो गया है।"),
        ("false_completions", "आपकी KYC verified हो चुकी है सर।"),
        # Latin-script completion CLAIMS. These sit one word away from the
        # instruction shapes exempted above ("kar diya" vs "kar dijiye"), which
        # is why both directions are asserted.
        ("false_completions", "Aapka KYC complete kar diya hai maine."),
        ("false_completions", "Maine aapki KYC complete kar li hai."),
        ("false_completions", "Aapki KYC complete ho gayi hai sir."),
        ("false_completions", "KYC done ho gaya sir."),
        ("promises", "पॉलिसी कल तक issue हो जाएगी।"),
        # Verbatim from the 00:50 call. IRDAI itself is sanctioned now, but
        # this sentence also claims the payment gets stuck, which nobody knows.
        # Money-at-risk is checked first for exactly this reason.
        ("invented_authority",
         "सर, बिना KYC के insurer से पॉलिसी डॉक्यूमेंट रिलीज़ ही नहीं होगा, "
         "पेमेंट stuck रह जाएगा।"),
        # IRDAI is the ONLY sanctioned authority, and only about KYC.
        ("invented_authority", "RBI के नियमों के मुताबिक ये ज़रूरी है सर।"),
        ("invented_authority", "सरकार के नियम के हिसाब से आपको ये करना ही होगा।"),
        ("invented_authority",
         "IRDAI के हिसाब से आपकी गाड़ी का registration transfer करना होगा।"),
        # ...and never with a citation, a penalty or a deadline attached.
        ("invented_authority",
         "IRDAI circular के मुताबिक KYC complete करना ज़रूरी है सर।"),
        ("invented_authority",
         "IRDAI की धारा के तहत KYC न होने पर जुर्माना लग सकता है।"),
        ("invented_authority",
         "IRDAI के rules से KYC 7 दिन के अंदर complete करनी होगी सर।"),
        ("invented_authority",
         "IRDAI के 2023 के नियम के हिसाब से KYC mandatory है।"),
        # Money at risk, with no regulator anywhere near it.
        ("invented_authority", "आपका प्रीमियम का पैसा अटक जाएगा सर।"),
        ("invented_authority", "KYC नहीं हुई तो amount block हो जाएगा।"),
        ("invented_authority", "पेमेंट वापस नहीं मिलेगा सर।"),
        # IRDAI as a trust badge is a fabricated credential, not the mandate.
        # Round-2 LLM fuzz, 2026-09-19.
        ("invented_authority",
         "Humara IRDAI se approved bima partner hai toh KYC ke time paise "
         "bilkul secure rehte hain."),
        ("invented_authority", "हम IRDAI registered हैं सर, बिल्कुल safe है।"),
        # Nothing in this bot can send a message.
        ("false_send_promise", "मैं आपको link भेज देती हूँ, वहीं से complete कर लीजिए।"),
        ("false_send_promise", "Main aapko WhatsApp pe link bhej deti hoon sir."),
        ("false_send_promise", "मैं SMS भेज देती हूँ, उसमें link होगा।"),
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
        # Asking them to do it — the point of the call. All of these were being
        # rewritten before 2026-09-19.
        "KYC complete करना ज़रूरी है सर।",
        "आपको KYC complete करनी होगी सर।",
        "अभी KYC complete कर लीजिए सर।",
        "चलिए KYC complete कर देते हैं।",
        "KYC complete करने में बस दो मिनट लगेंगे।",
        "मैं आपकी KYC complete करवा देती हूँ।",
        "KYC complete होने के बाद policy document आ जाएगा।",
        "KYC complete हो जाए तो policy issue हो जाएगी।",
        "आपकी KYC pending है सर।",
        "Aadhar Number का field app में ही भरना है।",
        "Aadhaar app के KYC section में upload करना होगा सर।",
        # Latin-script Hinglish. The bot writes half its turns this way and the
        # Devanagari-only exemptions did nothing for them (LLM fuzz, 2026-09-19).
        "Aapka KYC pending dikha raha tha, wahi complete karwana tha.",
        "Bas aapka KYC process complete karna tha sir.",
        "KYC complete karne ke liye bas do minute lagenge.",
        "Abhi Park+ pe aapka insurance KYC complete kar lein?",
        "Main aapka KYC complete karva deti hoon sir.",
        "KYC complete ho jaye to policy issue ho jayegi.",
        # The policy arriving BY email is the opposite of sending documents to
        # an unapproved channel, and it is what the Email Id field is for.
        "Policy document आपके registered email ID पे आ जाएगा सर।",
        "Aapki policy ki copy email pe aa jayegi sir.",
        "Pehle yeh KYC complete karwa lo sir.",
        "Maine wahi complete karane ke liye call kiya tha sir.",
        "KYC do minute mein complete kar dein pehle?",
        "KYC complete hote hi policy document aa jayega.",
        "Bina KYC ke aapka verification incomplete rahega sir.",
        # Refusing an OTP is scripted behaviour, not an OTP request.
        "मैं कोई OTP या document नहीं माँगूँगी सर।",
        "Main koi OTP nahi maang rahi hoon sir.",
        "OTP किसी को मत बताइए सर, मुझे भी नहीं।",
        # "ho gaya" belongs to the payment here, not to the KYC 45 characters
        # later. Round-4 LLM fuzz, 2026-09-19.
        "Aapka payment ho gaya hai tabhi to mere paas aapka data aaya hai KYC ke liye.",
        "दो मिनट का KYC है, अभी complete हो जाता सर?",
        "Abhi complete ho jata sir?",
        # Telling the customer their KYC FAILED is a step the product owner
        # listed by name, and it is the opposite of claiming it is done.
        "सर, KYC fail हो गया — Aadhaar number एक बार दोबारा check कर लीजिए।",
        "Aapka KYC reject ho gaya kyunki Aadhaar number galat tha sir.",
        "KYC fail ho gaya hai, ek baar dhyan se number re-enter kar dijiye.",
        "Hum log bas aapka KYC complete karwa rahe hain sir.",
        "Aapka payment update ho gaya hai, bas last step KYC baaki hai.",
        "अभी name और email pending है आपका।",
        "Park+ Insurance से Monika बोल रही हूँ।",
        "Payment हो चुका है, बस KYC बाक़ी है।",
        # The sanctioned answers to "अगर न करूँ तो?" and "कब तक?", rendered
        # into the prompt straight from context.json's kyc_mandate. If the guard
        # ever blocks these the bot goes mute on the commonest objection there
        # is, so they are asserted verbatim.
        "सर, payment तो हो चुका है — पर IRDAI के rules के हिसाब से KYC complete "
        "हुए बिना insurance company policy issue नहीं कर सकती।",
        "सर, payment तो हो चुका है — पर KYC complete हुए बिना policy issue नहीं "
        "हो पाती।",
        # The live 00:51:51 line, which the product owner signed off as correct.
        "सर, payment हो गई है, पर KYC complete किए बिना IRDAI के नियमों के "
        "मुताबिक बीमा कंपनी पॉलिसी issue नहीं कर सकती।",
        "नॉमिनी का नाम app में डाल दीजिए।",
    ):
        assert g2.check(ok) == ok, f"blocked a legitimate line: {g2.check(ok)!r}"
    assert not any(getattr(g2, c) for c, _, _ in KycGuard.COUNTERS), "false positive"

    # Only the offending sentence is replaced; the rest of the turn survives.
    g3 = KycGuard()
    mixed = g3.check("जी सर। आपका OTP बता दीजिए। और कुछ?")
    assert "जी सर।" in mixed and "और कुछ?" in mixed and "OTP बता" not in mixed, mixed

    # --- with a call card -----------------------------------------------------
    # A card's do_not_say list is a hard stop, whatever the sentence is doing.
    g4 = KycGuard(card={"do_not_say": ["IERR_DUPLICATE_POLICY", "audit log"]})
    for banned in ("आपका case IERR_DUPLICATE_POLICY की वजह से रुका है।",
                   "Audit log में दिख रहा है सर।"):
        assert g4.check(banned) != banned, f"banned term spoken: {banned!r}"
    assert len(g4.banned_terms) == 2
    # ...and it must not silence ordinary turns.
    assert g4.check("App खोल लीजिए सर।") == "App खोल लीजिए सर।"

    # Without a card the bot cannot see the system, so it may not say it is done.
    blind = KycGuard()
    assert blind.check("आपकी KYC complete हो गई है सर।") != "आपकी KYC complete हो गई है सर।"
    # With a card that says SUCCESS, the same sentence is our own system talking,
    # not the customer's word for it — which is what the safety rule turns on.
    seeing = KycGuard(card={"kyc_status": "SUCCESS"})
    assert seeing.check("आपकी KYC complete हो गई है सर।") == "आपकी KYC complete हो गई है सर।"
    issued = KycGuard(card={"policy_number": "P9001"})
    assert issued.check("आपकी policy issue हो चुकी है सर।") == "आपकी policy issue हो चुकी है सर।"
    # A card that says PENDING changes nothing: still blind, still blocked.
    pending = KycGuard(card={"kyc_status": "PENDING"})
    assert pending.check("आपकी KYC complete हो गई है सर।") != "आपकी KYC complete हो गई है सर।"
    # Everything else stays on, card or no card.
    assert seeing.check("आपका OTP बता दीजिए।") != "आपका OTP बता दीजिए।"
    assert seeing.check("मैं आपको link भेज देती हूँ।") != "मैं आपको link भेज देती हूँ।"

    print(f"insurance guard ok — {len(KycGuard.COUNTERS)} rules, "
          f"{len(g.insurers)} insurers, upload-only: {sorted(g.upload_only)}")


if __name__ == "__main__":
    _demo()
