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

import io
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
# Two forms, picked in check() by whether the turn already refused somewhere.
# The model usually opens with its own correct refusal and only the SECOND
# sentence invents an app-OTP step; re-refusing there made the customer hear
# the refusal twice (benchmark 2026-09-22, safety_probes turn 1). A turn with
# no refusal in it at all still has to carry one — this is an ID path.
_SAFE_OTP = "OTP किसी को मत बताइए सर — इस KYC में उसकी ज़रूरत ही नहीं पड़ती"
_SAFE_OTP_FACT_ONLY = "इस KYC में OTP की ज़रूरत ही नहीं पड़ती सर"
# ...unless the bot is REFUSING to ask for one, which is the scripted opening
# and the correct answer when a customer offers theirs.
_OTP_REFUSAL = re.compile(
    r"(?:नहीं|नही|कभी\s*नहीं|मत|nahi+n?|not|never|no)\s*"
    r"(?:माँग|मांग|maang|mang|ask|चाहिए|chahiye|बताइए|बताना|batana|दीजिए|share)|"
    r"(?:माँग|मांग|maang|mang|ask(?:ing)?|पूछ)\s*"
    r"(?:नहीं|नही|nahi+n?|not|never)|"
    r"किसी\s*को\s*(?:भी\s*|ही\s*)?(?:मत|नहीं|नही)|"
    r"kisi\s*ko\s*(?:bhi\s*)?(?:mat|nahi)|"
    # ...and negation AFTER the verb: "माँगने की जगह नहीं", "माँगती नहीं हूँ".
    r"(?:माँग|मांग|maang|mang)\w*[^.।!?]{0,18}(?:नहीं|नही|nahi+n?)|"
    r"(?:ask|need)\w*[^.।!?]{0,18}(?:not|never|no\b)|"
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
# Asking whether they FILLED PAN/Aadhaar is not asking them to say the numbers.
# _ASK_SHAPE contains a bare "?", so "सर, आपने PAN और Aadhaar भर दिए थे?" — the
# disambiguating question the Complete KYC rule needs — was being rewritten into
# "वो number मुझे फ़ोन पर नहीं चाहिए", which answers something nobody asked.
_ASKED_IF_FILLED = re.compile(
    r"भर\s*(?:दिए|दी|दिया|लिए|ली)|डाल\s*(?:दिए|दी|दिया)|"
    r"fill\s*(?:ed|kiya|kar\s*(?:diya|di))|entered|"
    r"(?:complete|पूरा|पूरी)\s*(?:कर|हो)",
    re.IGNORECASE,
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
# PAN and "copy" were missing, so "PAN card की copy email कर दीजिए" — asking for
# an identity document by email — went straight through (2026-09-22).
_DOC_WORD = (
    r"photo|फोटो|फ़ोटो|image|तस्वीर|document|डॉक्यूमेंट|दस्तावेज़|scan|"
    r"aadhaar|aadhar|आधार|\bPAN\b|पैन|copy|कॉपी|कार्ड\s*की"
)
# "copy" was in that list and cost a real turn. Caught live 23:21: "आप अपना ही
# Email ID डाल दीजिए जिस पर आपको पॉलिसी की copy चाहिए।" was blocked, because
# "email" matched the channel and "copy" matched the document. Email Id is a
# FIELD on this form and the policy copy is what gets sent to it — the bot has to
# be able to say that. The rule is about SENDING documents to Park+ over an
# unapproved channel, so a sentence about filling the Email Id field is exempt.
_FORM_FIELD_CONTEXT = (
    r"field|फ़ील्ड|फील्ड|Email\s*(?:Id|ID)|"
    # LISTING the form fields is not asking for documents. Park+ answered "क्या
    # डॉक्यूमेंट चाहिए" with "नाम, जन्मतिथि, ईमेल, पता … भरें — फिर PAN और
    # Aadhaar वाला फॉर्म भरना है" and the doc-channel rule saw "ईमेल" + "Aadhaar"
    # and replaced a correct answer with one about uploading (live call 14:08,
    # 2026-09-22). The exemption knew भर दीजिए/दो/दें but not भरें or भरना.
    r"डाल\s*(?:दीजिए|दो|दें|ना|नी)|भर\s*(?:दीजिए|दो|दें|ना|नी|के)|भरें|भरनी|"
    r"फ़ॉर्म|फॉर्म|form|"
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
    r"(?:complete|पूरा|पूरी|हो|done|issue)\s*(?:नहीं|नही|nahi+n?|ना\b)|"
    r"नहीं\s*(?:हुआ|हुई|होगी|होगा|होती|करते|करेंगे|किया|कर\s*पाए)|"
    r"\bnot\s+(?:complete|done|verified)|"
    # "Your payment is done, but the KYC is still pending" is the OPPOSITE of a
    # completion claim, yet "done" plus "KYC" made false_completions fire and
    # inject a Hindi line into an English reply (2026-09-22, code_switch 0).
    r"(?:still\s+)?pending|बाक़ी\s*है|बाकी\s*है|अटक",
    re.IGNORECASE,
)

_UI_ACTION = (
    r"दबा\s*(?:दीजिए|दो|दें|इए)|tap|click|press|button|बटन|option|विकल्प|"
    r"select|चुन|खोल\s*(?:िए|ो)|open|जाइए|जाके|जाकर|"
    r"Complete\s*KYC"
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
    # लें / ले / लूँ are the subjunctive "shall we complete it now?" — an
    # invitation, not a claim. Gemini's "अभी आपके insurance की KYC complete कर
    # लें?" was rewritten into a nonsense answer on 2026-09-22 because only the
    # polite लीजिए form was listed. कर ली / कर लिया stay OUT: those are past
    # tense and are exactly what this rule catches.
    # देंगे / दें is the CUSTOMER's future action — "जैसे ही आप app में KYC
    # complete कर देंगे" — not a claim. The transliterated branch below already
    # listed denge; this one did not.
    r"कर\s*(?:लीजिए|लीजिये|दीजिए|दीजिये|लो|दो|देते|लेते|लेंगे|लें|ले|लूँ|लूं|"
    r"देंगे|देंगी|दें|सकते|सकें|पाएँ|पाएंगे))"
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
# SPLIT by script, and the Devanagari half carries NO trailing \b. Most of these
# words end in a vowel sign (े ी ा ं), which is category Mn and therefore not \w,
# so \b after them can never match: 8 of the 13 markers here were dead on
# 2026-09-22 and this rule had been letting "policy 24 से 48 घंटे में आ जाएगी"
# straight through to the caller. Same trap as _ENGAGED_RE and _LABEL_FIXES.
_PROMISE_MARKER = re.compile(
    r"\b(?:today|tomorrow|within|immediately|guarantee|"
    r"\d+\s*(?:hours?|days?))\b"
    # NOT "में ही": it was dead too, and it means "in X itself" far more often
    # than "within" — it fired on the approved "सब कुछ आपके app में ही होगा".
    # Real timing is already covered by the duration alternative below.
    r"|(?:आज|कल|परसों|तुरंत|गारंटी|पक्का)"
    r"|(?:\d+|एक|दो|तीन|चार|पाँच|पांच|कुछ)\s*(?:घंटे|घंटो|दिन|दिनों)",
    # "मिल जाएगा" / "हो जाएगी" were in this list and dead, so nobody noticed they
    # do not belong: they are plain future tense, and the SANCTIONED line "बस KYC
    # होते ही आपकी policy issue हो जाएगी" contains one. A promise is a TIME or a
    # certainty claim; future tense on its own is how the product describes
    # itself. Reviving them turned that approved sentence into a false positive.
    re.IGNORECASE,
)
_SAFE_PROMISE = (
    "वो मैं यहाँ से confirm नहीं कर सकती सर — team update कर देगी"
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
# Sending a case to our own team, and the sanctioned WhatsApp KYC link, are the
# two "भेज" sentences that are real. Everything else is still a promise of a
# message that never arrives.
_SEND_EXEMPT = re.compile(
    r"team\s*(?:को|ko)\s*(?:भेज|bhej|assign|forward)|"
    r"(?:भेज|bhej)[^.।!?]{0,12}(?:team|टीम)|"
    r"(?:WhatsApp|व्हाट्सएप|वॉट्सऐप)[^.।!?]{0,40}(?:KYC|link|लिंक)|"
    r"(?:KYC|link|लिंक)[^.।!?]{0,40}(?:WhatsApp|व्हाट्सएप|वॉट्सऐप)",
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

# --- stating an amount of money ----------------------------------------------
# Borrowed wholesale from the car spa's price guard, because the failure is the
# same one with a bigger number on it: a figure the bot cannot verify, said out
# loud, that the customer then plans around.
#
# The difference is that the car spa HAS a price list and this bot has none. The
# premium, the amount paid and any refund were deliberately kept off the call
# card — "a bot that quotes money it cannot verify is how a call becomes a
# refund dispute" — so there is no rupee figure this bot is ever right about.
# Every one of them is invented. Nothing legitimate is lost by refusing them
# all: "दो मिनट" is a time, not an amount, and _PRICE_RE does not match it.
_SAFE_MONEY = (
    "उसका exact amount मैं यहाँ से confirm नहीं कर सकती सर — team बता देगी"
)

# --- English goodbye / English-only close (15:22 call) ------------------------
# Ornith closed with "Thank you सर! Have a good day." Prompt says Hindi only;
# this makes it stick. A sentence that is mostly Latin AND looks like a closing
# gets rewritten. Mixed Hindi+English instructional sentences stay.
_ENGLISH_CLOSE_RE = re.compile(
    r"(?:have\s+a\s+(?:good|nice|great)\s+day|good\s+(?:day|bye|night)|"
    r"thank\s*you(?:\s+so\s+much)?|thanks(?:\s+a\s+lot)?|"
    r"\bgoodbye\b|\bbye\b(?:\s*bye)?|"
    r"take\s+care|see\s+you|talk\s+to\s+you\s+later)",
    re.IGNORECASE,
)
# --- English words Sarvam mispronounces in Devanagari -------------------------
# Only the two that actually come out wrong: bulbul reads "एप" as "ep", not
# "app", and "डीओबी" as three Hindi letters instead of D-O-B. पॉलिसी, बटन, पेज,
# इंश्योरेंस and नॉमिनी are ordinary spoken Hindi and the guard's own sanctioned
# lines use them — rewriting those would fight approved copy, which is why the
# wider version of this map was reverted on 2026-09-22. Park+'s model (3.3B
# active) still transliterates with the rule first in the prompt, so this is a
# deterministic rewrite. \b does not work on Devanagari, hence the bare
# alternation.
_LABEL_FIXES = {"एप": "app", "ऐप": "app", "डीओबी": "DOB"}
_LABEL_RE = re.compile("|".join(sorted(_LABEL_FIXES, key=len, reverse=True)))

# --- coercive phrasing --------------------------------------------------------
# The product owner's rule is "we can't be rude to the user", and the prompt
# spells out the exact wording to avoid: gentle "बस इतना बता दूँ", never
# "आपको करना ही पड़ेगा". Park+'s model produced that banned string verbatim on
# a garbled-input turn (benchmark 2026-09-22, noise_garble turn 1) — when it
# cannot parse the caller it falls back to pressure. Advice in the prompt did
# not hold, so the rewrite is deterministic. The replacement states the same
# real requirement in the sanctioned shape and still asks for a time.
_COERCION_RE = re.compile(
    r"(?:करना|कराना|भरना|देना)\s*(?:ही\s*)?पड़ेगा|"
    r"(?:करना|कराना)\s*ही\s*होगा|"
    r"मजबूर|majboor|"
    r"वरना\s*(?:policy|पॉलिसी|आपकी)|"
    r"you\s*(?:have|must)\s*to\s*do\s*(?:it|this)\s*now",
    re.IGNORECASE,
)
_SAFE_SOFT_REQUIREMENT = (
    "बस इतना बता दूँ सर, KYC हो जाने पर ही आपकी policy बन पाएगी — "
    "दो मिनट का काम है, बताइए कब करवा दें?"
)

# --- pushing the app before they agreed ---------------------------------------
# Product owner, 2026-09-22, after a live call: "जब तक वो ना बोले कि हाँ, कि
# process बताओ मुझे, तब तक मत बोलो कि Park+ app खोल दो." Every answer ended with
# the app line, which is what made the call feel like being herded.
#
# The prompt rule for it does not hold, and that is not the model's fault: the
# whole document exists to get them into the app (WHAT THIS CALL IS FOR, MATCH
# rows 11 and 14, the opening line), so one bullet cannot outvote it.
#
# NO sentence counting. A first attempt counted sentences per turn and reset on
# note_caller; the counter drifted whenever check() ran without a turn boundary
# and the guard ate a real instruction. The only state here is one latching
# boolean, so the worst case is a push that should have been spoken is dropped,
# never an instruction deleted because a count slipped.
_APP_PUSH_RE = re.compile(
    r"(?:Park\+\s*)?app\s*(?:को\s*)?खोल|app\s*open\s*(?:कर|कीजिए)|"
    r"(?:Insurance|इंश्योरेंस)\s*(?:वाले\s*|वाला\s*)?(?:icon|आइकन)|"
    r"(?:icon|आइकन)\s*(?:पर|पे)\s*(?:click|क्लिक)|"
    r"open\s*the\s*Park\+\s*app|Park\+\s*app\s*(?:में|पर)\s*(?:जा|आ)",
    re.IGNORECASE,
)
# Topics where "put it in the app" IS the answer, not a push. Someone reading
# their Aadhaar down the phone gets told where it actually goes; dropping that
# left them with "मुझे मत बताइए" and nowhere to put it (benchmark 2026-09-22).
_APP_IS_THE_ANSWER = frozenset({"aadhaar", "fill_for_me", "details", "nominee"})

# They said yes, asked how, or reported progress — from here the app line is
# wanted, not pushed. Deliberately generous: a miss here means the bot cannot
# tell a willing customer what to do, which is worse than one extra push.
_ENGAGED_RE = re.compile(
    # NO \b on the Devanagari branch. हाँ ends in U+0901 and है in U+0948, both
    # combining marks, which are not \w — so \b after them never matches and the
    # whole "they said yes" branch silently died. Same trap as _LABEL_FIXES.
    r"(?:^|\s)(?:हाँ|हा|जी|ठीक\s*है|चलो|ठीक)|"
    r"(?:^|\s)(?:ok(?:ay)?|yes|haan|theek|sure)\b|"
    r"क्या\s*(?:करना|करूँ|करू|करें|होगा)|कैसे\s*(?:करना|करूँ|करें|होगा|होता)|"
    r"(?:process|प्रोसेस|प्रक्रिया)\s*(?:बता|क्या|कैसे)|"
    r"(?:आगे|अब)\s*(?:क्या|बता|बताओ|बताइए)|"
    r"खोल\s*(?:लिया|दिया|रहा)|खुल\s*(?:गया|गयी|गई)|मिल\s*गया|कर\s*दिया|"
    r"दिख\s*रहा|बता(?:ओ|इए|ना)\b|"
    r"what\s*(?:do|should|exactly)|how\s*do\s*i|tell\s*me",
    re.IGNORECASE,
)

# --- the customer's name on every single line ---------------------------------
# Product owner, three times: "एक-दो बारी नाम use कर देना है। हर line पे नहीं
# देना है", and the live calls kept doing it anyway — "Anush जी" opened eleven
# consecutive turns on 2026-09-22. A prompt rule did not hold across three
# attempts, so this counts and strips.
#
# Allowance is TWO uses per call, including the greeting. Drift here is benign
# in both directions: a missed reset strips more (which is the ask), and a
# double count strips one sooner. Nothing is ever deleted except the vocative.
_NAME_ALLOWANCE = 2


def _vocative_re(first_name: str) -> re.Pattern | None:
    """Match "<name> जी" / "<name>" used to address them, not to state a fact.

    NO \\b after the Devanagari honorific: जी ends in a vowel sign and \\b
    cannot match there. The name itself may be in either script.
    """
    first = first_name.strip().split()[0] if first_name.strip() else ""
    if len(first) < 2:
        return None
    n = re.escape(first)
    return re.compile(
        # Leading address: "Anush जी, बाकी..." / "अनूष जी — ..."
        rf"^\s*{n}\s*(?:जी|ji)?\s*[,—:-]\s*"
        # ...or trailing/inline: "...हो जाएगा Anush जी।"
        rf"|\s*,?\s*{n}\s*(?:जी|ji)(?=[\s,.।!?]|$)",
        re.IGNORECASE,
    )


# Stating their name is an ANSWER ("आपका नाम Anush Gupta है"), not a vocative.
_NAME_IS_THE_ANSWER = re.compile(
    r"(?:आपका|आपक[ीे]|your)\s*(?:पूरा\s*)?(?:नाम|name)|"
    r"(?:नाम|name)\s*(?:है|hai|is)",
    re.IGNORECASE,
)

# --- the same sanctioned line twice in one call -------------------------------
# "Never say a sentence you already said" is a prompt rule that has now failed
# three times on Park+: it answered two consecutive "बाद में" turns with the
# identical callback line. The model cannot reliably track what it already said
# even with the line sitting in its own context, so the second use is swapped
# here for a different wording of the SAME answer.
#
# Only these pairs, and only a swap — nothing is ever dropped, so the worst case
# is the caller hears the alternate when the original would have been fine.
# No "सर" in the alternates: the line they replace already has one, and two in
# one sentence sounds like a form letter. Keyed by PATTERN because the model
# writes the English words in either script — Park+ said "कॉल" where the
# sanctioned line says "call", and a literal key missed it entirely.
_ALTERNATES = (
    (re.compile(r"शाम\s*को\s*(?:call|कॉल)\s*करूँ\s*या\s*कल\s*सुबह", re.I),
     "बस बता दीजिए कब करना है, उसी time call कर लूँगी"),
    # Widened 2026-09-22: 1b now just asks "कब call करूँ?" (open, so it can
    # accept whatever time the caller names — see prompt.py row 1b), and that
    # same tail question also closes row 1a. Narrower wording tied to the old
    # "बाद में आपको कब call करूँ" phrasing stopped matching when 1b changed.
    (re.compile(r"कब\s*(?:call|कॉल)\s*करूँ", re.I),
     "बस बता दीजिए कब करना है, उसी time call कर लूँगी"),
    (re.compile(r"अभी\s*2\s*(?:minute|मिनट)\s*में\s*करवा\s*देती\s*हूँ", re.I),
     "2 minute का ही काम है सर"),
)

# --- "I clicked Complete KYC" is AMBIGUOUS -------------------------------------
# Product owner, 2026-09-22, corrected twice. There are TWO Complete KYC buttons:
#   1. on the insurance home page — opens the flow, nothing is filled yet;
#   2. on the KYC page once PAN and Aadhaar are in — this one SUBMITS.
# So "Complete KYC पे click कर दिया" means either "I just started" or "I just
# finished", and the two need opposite answers.
#
# Park+ assumes the second and says "आपकी तरफ़ का काम हो गया … policy WhatsApp
# और mail पे आ जाएगी". Half the time that tells someone sitting in front of an
# empty form they are done; they hang up and nothing is ever submitted.
#
# Guessing the other way is just as wrong, so the guard does not guess: it asks
# one short question that is correct whichever button they pressed.
_CLICKED_BUTTON_RE = re.compile(
    r"(?:complete\s*kyc|कंप्लीट\s*के?वाईसी|कम्पलीट\s*के?वाईसी)"
    r"[^.।!?]{0,25}(?:पे|पर|par|pe)?\s*(?:click|क्लिक|दबा|press|tap)"
    r"|(?:click|क्लिक|दबा)[^.।!?]{0,25}(?:complete\s*kyc|कंप्लीट\s*के?वाईसी)",
    re.IGNORECASE,
)
# ...but "submit कर दिया" / "सब भर दिया" in the SAME line means they went on and
# finished, and then the done answer is right.
_ALSO_SUBMITTED_RE = re.compile(
    r"submit|सबमिट|सब\s*(?:कुछ\s*)?भर|भर\s*(?:के|कर)\s*(?:दिया|दी)|"
    r"पूरा\s*भर|सारी\s*details\s*भर",
    re.IGNORECASE,
)
_SAFE_AFTER_BUTTON = (
    "सर, एक बात confirm कर लूँ — PAN और Aadhaar की details भर दी थीं आपने? "
    "अगर हाँ तो काम हो गया, नहीं तो वो form भर दीजिए"
)

_SAFE_CLOSE = "धन्यवाद, thank you for choosing Park+"
# The sanctioned close itself contains "thank you" and only a 7-character
# Devanagari run ("धन्यवाद"), one short of _ENGLISH_CLOSE_RE's own 8-char
# exemption — caught live 2026-09-22 before it ever shipped: without this, the
# guard would rewrite its own sanctioned line back to itself on every close.
def _roman_hindi(text: str) -> bool:
    """Romanised Hindi function words — "this line is Hindi, in Latin letters"."""
    from guardrails import _ROMAN_HINDI_RE
    return bool(_ROMAN_HINDI_RE.search(text))


_SANCTIONED_CLOSE_RE = re.compile(
    # Both spellings of the same sanctioned line: under REPLY_SCRIPT=hinglish
    # the bot writes "Dhanyavaad", and without this the close rule rewrites its
    # own approved closing line back into Devanagari on every call.
    r"(?:धन्यवाद|dhanyav?aa?d)[,،]?\s*thank\s*you\s*for\s*choosing",
    re.IGNORECASE,
)

# --- waiting-line dump when the customer asked a real question ----------------
# 15:45 / 17:23: Ornith answered "details बता दो" and "दो मिनट लगेंगे?" with the
# form-open waiting script. That script is for silence after the form opens, not
# for questions. When note_caller marked the last turn as a question topic, a
# waiting-line sentence is rewritten to the short safe redirect for that topic.
_WAITING_LINE_RE = re.compile(
    r"form\s*खुल\s*गया\s*है|"
    r"आराम\s*से\s*सारी\s*details\s*complete|"
    r"मैं\s*line\s*पे\s*ही\s*हूँ",
    re.IGNORECASE,
)
# The "I genuinely do not know" deflection, in the shapes the prompt teaches it.
_DONT_KNOW_RE = re.compile(
    r"(?:exact\s*)?(?:जवाब|answer)\s*(?:मुझे\s*)?(?:पता\s*)?(?:नहीं|नही)|"
    r"मुझे\s*(?:इसका\s*)?(?:exact\s*)?(?:पता|मालूम)\s*(?:नहीं|नही)|"
    r"team\s*(?:confirm|check)\s*करके|"
    r"(?:don'?t|do not)\s*know",
    re.IGNORECASE,
)

_SAFE_BY_TOPIC = {
    "time": "सर, दो मिनट ही लगेंगे, अभी करवा देती हूँ।",
    # A refund ask has a real answer — customer support. The bot used to say
    # "मुझे इसका exact जवाब पता नहीं है, team confirm करके बता देगी", which
    # leaves the customer nowhere (live call 2026-09-22, product owner).
    "refund": 'सर, policy cancel या refund की request आप Park+ customer support पर कर सकते हैं — वो लोग यही handle करते हैं।',
    "details": (
        "खाली वाले भरें — owner's name, email, address, nominee। पहले से भरे "
        "सिर्फ check। KYC पे PAN + Aadhaar app में — number मुझे मत बताइए।"
    ),
    "nominee": (
        "नॉमिनी परिवार या भरोसेमंद व्यक्ति का नाम — claim उन्हीं को। "
        "RC वाला owner-name nominee में नहीं। Age उनकी असली age।"
    ),
    "aadhaar": (
        "सर, Aadhaar और PAN app के KYC form में भरना है — number मुझे call पे "
        "मत बताइए।"
    ),
    "fill_for_me": (
        "मैं call पे details नहीं भर सकती सर — app में आपको ही डालना है।"
    ),
    "busy": (
        "सर, 2 minute लगेंगे। अभी 2 minute में करवा देती हूँ। "
        "अगर possible नहीं है तो कब call करूँ?"
    ),
}

# Caller-topic detectors for note_caller. First match wins; order matters.
_CALLER_TOPIC_PATTERNS = (
    ("fill_for_me", re.compile(
        r"भर\s*(?:दो|दें|दीजिए|दे)|"
        r"(?:तुम|आप|you)\s*[^.।!?]{0,12}(?:भर|डाल|fill)|"
        r"(?:भर|डाल|fill)[^.।!?]{0,12}(?:तुम|आप|you)|"
        r"(?:मेरी|meri)\s*(?:details|डिटेल्स)\s*(?:भर|डाल|तुम|आप)|"
        r"(?:details|डिटेल्स)\s*(?:तुम|आप)\s*(?:भर|डाल)",
        re.IGNORECASE,
    )),
    ("nominee", re.compile(
        r"नॉमिनी|nominee|नॉमिनी\s*की\s*(?:age|एज|उम्र)",
        re.IGNORECASE,
    )),
    ("aadhaar", re.compile(
        r"आधार|aadhaar|aadhar|\bPAN\b|पैन|केवाईसी\s*वाले|KYC\s*वाले",
        re.IGNORECASE,
    )),
    ("time", re.compile(
        r"कितना\s*(?:टाइम|समय|देर)|कितनी\s*देर|how\s*long|"
        r"दो\s*मिनट\s*(?:से\s*)?(?:ज़्यादा|ज्यादा|लग)",
        re.IGNORECASE,
    )),
    ("details", re.compile(
        r"क्या[\s\-]*क्या|details\s*बता|डिटेल्स\s*बता|क्या\s*भरना|"
        r"details\s*(?:कैसे|क्या)|डिटेल्स\s*(?:कैसे|क्या)",
        re.IGNORECASE,
    )),
    # They clicked the button that OPENS the form — not the end of the call.
    ("clicked_kyc_button", re.compile(
        r"(?:complete\s*kyc|कंप्लीट\s*के?वाईसी|कम्पलीट\s*के?वाईसी)"
        r"[^.।!?]{0,25}(?:click|क्लिक|दबा|press|tap)"
        r"|(?:click|क्लिक|दबा)[^.।!?]{0,25}(?:complete\s*kyc|कंप्लीट\s*के?वाईसी)",
        re.IGNORECASE,
    )),
    # Refund / cancellation. Ahead of "busy" because "policy नहीं चाहिए, बाद में
    # देखता हूँ" is a refund question wearing a scheduling coat.
    ("refund", re.compile(
        r"refund|रिफंड|रिफ़ंड|पैसे?\s*(?:वापस|वापिस|रिटर्न)|paise\s*wapas|"
        r"(?:policy|पॉलिसी)[^.।!?]{0,20}(?:(?:नहीं|नही)\s*चाहिए|चाहिए\s*(?:नहीं|नही))|"
        r"(?:(?:नहीं|नही)\s*चाहिए|चाहिए\s*(?:नहीं|नही))[^.।!?]{0,20}(?:policy|पॉलिसी)|"
        r"cancel|कैंसिल|कैन्सिल|रद्द",
        re.IGNORECASE,
    )),
    ("busy", re.compile(
        r"(?:अभी\s*)?(?:टाइम|समय)\s*नहीं|बाद\s*में|फ्री\s*नहीं|"
        r"call\s*(?:later|बाद)|later\s*call",
        re.IGNORECASE,
    )),
    ("bye", re.compile(
        r"\bbye\b|बाय|धन्यवाद|thank\s*you|थैंक|ठीक\s*है\s*(?:बाय|bye)",
        re.IGNORECASE,
    )),
)

_SAFE_TIME_ONLY = "सर, दो मिनट ही लगेंगे, अभी करवा देती हूँ।"


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
        ("money_amounts", "error", "rewrote a rupee figure this bot cannot know"),
        ("self_ai", "error", "rewrote the bot announcing it is an AI"),
        ("english_close", "error", "rewrote an English goodbye"),
        ("wrong_script", "error", "rewrote waiting-line / IRDAI-on-time mismatch"),
        ("labels", "warning", "stripped a speaker label the model wrote"),
        ("romanised", "warning", "answered in romanised Hindi instead of Devanagari"),
        ("machine_output", "error", "DROPPED non-speech output"),
        ("self_narration", "error", "DROPPED the model thinking out loud"),
        ("coercion", "error", "rewrote a line that pressured the customer"),
        ("unasked_push", "error", "DROPPED an app push they had not asked for"),
        ("extra_name", "warning", "trimmed the customer's name off a later line"),
        ("repeated_line", "warning", "reworded a sanctioned line it had already said"),
        ("premature_done", "error", "rewrote 'you are done' said to someone mid-form"),
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
        self.money_amounts: list[str] = []
        self.self_ai: list[str] = []
        self.english_close: list[str] = []
        self.wrong_script: list[str] = []
        self.labels: list[str] = []
        self.romanised: list[str] = []
        self.machine_output: list[str] = []
        self.self_narration: list[str] = []
        self.coercion: list[str] = []
        self.unasked_push: list[str] = []
        self.extra_name: list[str] = []
        self.repeated_line: list[str] = []
        self.premature_done: list[str] = []
        # Caller clicked Complete KYC and did NOT say they submitted.
        self._caller_clicked_only = False
        self._said_after_button = False
        # Sanctioned lines already used this call — see _ALTERNATES.
        self._used_lines: set[str] = set()
        # Built from the call card, so a call without a name simply never trims.
        self._name_re = _vocative_re(str((self.card or {}).get("customer_name") or ""))
        self._name_uses = 0
        # Last caller topic, so a waiting-line / IRDAI dump can be rewritten to
        # the script that actually answers what they asked (15:18, 15:45, 17:23).
        self.last_caller_topic: str | None = None
        # Whether that line was entirely English — see _caller_spoke_english.
        self._caller_english = False
        self._turn_refused_otp = False
        # Has the customer agreed to do it now, or asked how? See _APP_PUSH_RE.
        self._engaged = False
        # Whether the "I am Park+'s calling assistant" line was already said
        # this turn, so a second self-description is dropped, not repeated.
        self._said_not_ai = False
        self._said_close = False

    def note_caller(self, text: str) -> bool:
        """Record what the caller just asked, so _fix_sentence can match scripts.

        Returns False always — nothing the caller says unlocks money/ID rules
        here (unlike car spa). The observer still calls this every turn.
        Clears the topic when nothing matches, so a prior nominee ask cannot
        poison the next turn's guard rewrite.
        """
        self._caller_english = self._caller_spoke_english(text)
        self._turn_refused_otp = False
        # Latches on and never off: once they are in, they are in.
        self._said_not_ai = False
        self._said_close = False
        self._caller_clicked_only = bool(
            _CLICKED_BUTTON_RE.search(text) and not _ALSO_SUBMITTED_RE.search(text)
        )
        self._said_after_button = False
        if _ENGAGED_RE.search(text):
            self._engaged = True
        for topic, pat in _CALLER_TOPIC_PATTERNS:
            if pat.search(text):
                self.last_caller_topic = topic
                return False
        self.last_caller_topic = None
        return False

    def _caller_spoke_english(self, text: str) -> bool:
        """True when the caller's line had no Devanagari at all.

        The prompt tells the bot to answer an all-English line in English, so
        an English reply to one is correct and must not be logged as script
        drift — Gemini did exactly that on both code_switch turns and the
        romanised counter made a working feature look like a defect.
        """
        return bool(re.search(r"[A-Za-z]", text)) and not re.search(
            r"[\u0900-\u097F]", text
        )

    def check(self, text: str) -> str:
        """Return text safe to speak, recording anything that was suppressed."""
        # Reuse the shared non-speech and thinking-out-loud rules; they are
        # model failures, not domain rules, and both were caught on live calls.
        from guardrails import (
            _DEVANAGARI_RE,
            _SELF_NARRATION_RE,
            _SPEAKER_LABEL_RE,
            is_hindi_speech,
            is_machine_output,
            is_script_drift,
            keep_lead,
        )

        # The function, not the bare regex — it also catches prompt scaffolding
        # ("/Tone: ...", a lone "*   No"), which a Gemini turn produced live on
        # 2026-09-22 and which the regex alone let through to the voice.
        if is_machine_output(text):
            self.machine_output.append(text.strip())
            return ""

        # The model copies the transcript label out of its own few-shot examples
        # and the caller hears "Shreya: जी सर". Stripped, not blocked — the
        # sentence after the label is usually fine.
        label = _SPEAKER_LABEL_RE.match(text)
        if label:
            self.labels.append(label.group(0).strip())
            text = text[label.end():]

        # Script drift is RECORDED, never rewritten, for the reason the car spa
        # guard gives: transliterating mid-call would mangle the English words
        # that are supposed to stay English (KYC, app, policy, payment). The
        # count makes drift a number to watch. Not hypothetical here — an Ornith
        # fallback turn came back as "**Good afternoon, Rahul जी.** I'm Shreya
        # calling from Park+ Insurance", entirely in English, with markdown.
        # Sentences arrive one call at a time and in order, so a refusal in
        # sentence one is remembered for sentence two. note_caller clears it at
        # the start of each turn. See _SAFE_OTP.
        if _OTP_REFUSAL.search(text):
            self._turn_refused_otp = True

        if is_script_drift(text) and not getattr(self, "_caller_english", False):
            self.romanised.append(text.strip())

        out = []
        for sentence in _SENTENCE_RE.findall(text):
            # Unsolicited app push: they have not said yes and have not asked
            # how, so this is the bot herding rather than answering.
            #
            # Only a sentence that is MOSTLY the push. Gemini answered "वीकल
            # नंबर बता सकते हो?" with the answer and the push joined by an
            # em-dash, all one sentence; dropping it left the turn empty and the
            # caller heard silence. A rule that removes speech must never be
            # able to remove the answer with it.
            push = (
                _APP_PUSH_RE.search(sentence)
                if not self._engaged
                and self.last_caller_topic not in _APP_IS_THE_ANSWER
                else None
            )
            if push:
                body = len(re.sub(r"\s", "", sentence))
                span = len(re.sub(r"\s", "", sentence[push.start():]))
                if body and span / body >= 0.6:
                    self.unasked_push.append(sentence.strip())
                    continue
            if _SELF_NARRATION_RE.search(sentence) and not is_hindi_speech(sentence):
                self.self_narration.append(sentence.strip())
                continue
            fixed = self._label_fix(self._fix_sentence(sentence))
            fixed = self._vary_repeat(fixed)
            out.append(keep_lead(sentence, self._trim_name(fixed)))
        return "".join(out)

    def _vary_repeat(self, sentence: str) -> str:
        """Second use of a sanctioned line gets its alternate wording."""
        for idx, (pat, alt_text) in enumerate(_ALTERNATES):
            m = pat.search(sentence)
            if m:
                key, alt = idx, alt_text
                break
        else:
            return sentence
        if key not in self._used_lines:
            self._used_lines.add(key)
            return sentence
        self.repeated_line.append(sentence.strip())
        rest = sentence[m.end():]
        # The line being replaced is a question; the alternate is a statement,
        # so the inherited "?" has to go or it is spoken with a rising tone.
        if rest[:1] == "?" and not alt.endswith("?"):
            rest = "।" + rest[1:]
        return sentence[: m.start()] + alt + rest

    def _trim_name(self, sentence: str) -> str:
        """Let the name through twice a call, then strip the vocative."""
        if self._name_re is None or not self._name_re.search(sentence):
            return sentence
        if _NAME_IS_THE_ANSWER.search(sentence):
            return sentence
        self._name_uses += 1
        if self._name_uses <= _NAME_ALLOWANCE:
            return sentence
        trimmed = self._name_re.sub(" ", sentence, count=1)
        trimmed = re.sub(r"\s{2,}", " ", trimmed)
        # Removing a trailing vocative leaves the space in front of it, so
        # "...पत्र है Anush जी।" became "...पत्र है ।" — the voice pauses on that.
        trimmed = re.sub(r"\s+([,.।!?])", r"\1", trimmed).strip()
        trimmed = re.sub(r"^[,—:-]\s*", "", trimmed)
        if not trimmed or len(trimmed) < 4:
            return sentence
        # Sentence-initial letter may now be lowercase mid-line; Devanagari has
        # no case so this only ever touches a Latin opener.
        self.extra_name.append(sentence.strip())
        return trimmed[0].upper() + trimmed[1:] if trimmed[0].islower() else trimmed

    def _label_fix(self, sentence: str) -> str:
        """Put transliterated screen labels back into Latin letters."""
        fixed = _LABEL_RE.sub(lambda m: _LABEL_FIXES[m.group(0)], sentence)
        if fixed != sentence:
            self.labels.append(sentence.strip())
        return fixed

    def _closing(self, terminator: str) -> str:
        """The sanctioned close, once per turn — several rules reach for it."""
        if self._said_close:
            return ""
        self._said_close = True
        return _SAFE_CLOSE if _SAFE_CLOSE[-1:] in ".।!?" else _SAFE_CLOSE + terminator

    def _fix_sentence(self, sentence: str) -> str:
        terminator = sentence[len(sentence.rstrip(".।!?")):] or "।"

        def safe(line: str) -> str:
            """Canned line + the sentence's terminator, without doubling it.

            Several sanctioned lines already end in a danda, and appending one
            gave "...handle करते हैं।।" — the voice pauses twice on that.
            """
            return line if line[-1:] in ".।!?" else line + terminator

        # Ambiguous "I clicked Complete KYC" — see _CLICKED_BUTTON_RE. Ask which
        # button rather than assert either answer.
        if (
            self._caller_clicked_only
            and (_DONE_CLAIM.search(sentence)
                 or re.search(r"काम\s*हो\s*गया|तरफ़?\s*का\s*काम|notification|"
                              r"WhatsApp\s*(?:और|aur)\s*mail", sentence, re.I))
        ):
            self.premature_done.append(sentence.strip())
            if self._said_after_button:
                return ""
            self._said_after_button = True
            return safe(_SAFE_AFTER_BUTTON)

        if self._do_not_say is not None and self._do_not_say.search(sentence):
            self.banned_terms.append(sentence.strip())
            return safe(_SAFE_DO_NOT_SAY)

        # English goodbye — before authority checks so "Thank you" does not
        # fall through as a harmless romanised warning.
        if (
            _ENGLISH_CLOSE_RE.search(sentence)
            and not re.search(r"[\u0900-\u097F]{8,}", sentence)
            and not _roman_hindi(sentence)
            and not _SANCTIONED_CLOSE_RE.search(sentence)
        ):
            self.english_close.append(sentence.strip())
            return self._closing(terminator)

        # Time question answered with IRDAI / waiting line (15:18, 17:23).
        # Only when note_caller marked the turn as a time ask — the sanctioned
        # IRDAI mandate line also contains "दो मिनट" and must survive on busy.
        if self.last_caller_topic == "time" and (
            _IRDAI_ONLY.search(sentence)
            or _WAITING_LINE_RE.search(sentence)
            or re.search(r"payment\s*तो\s*हो|पेमेंट\s*तो\s*हो", sentence, re.I)
        ):
            self.wrong_script.append(sentence.strip())
            return safe(_SAFE_TIME_ONLY)

        # "मुझे exact जवाब पता नहीं है, team बता देगी" in answer to a REFUND or
        # cancellation question. It has a real answer — Park+ customer support —
        # and the deflection leaves the customer with nowhere to go (live call
        # 2026-09-22). Only for this topic; everywhere else the line is correct.
        if self.last_caller_topic == "refund" and _DONT_KNOW_RE.search(sentence):
            self.wrong_script.append(sentence.strip())
            return safe(_SAFE_BY_TOPIC["refund"])

        # Waiting-line dump after a real question (details / nominee / etc.).
        topic = self.last_caller_topic
        if (
            topic in _SAFE_BY_TOPIC
            and topic not in ("busy", "bye")
            and _WAITING_LINE_RE.search(sentence)
        ):
            self.wrong_script.append(sentence.strip())
            return safe(_SAFE_BY_TOPIC[topic])

        if topic == "bye" and (
            _WAITING_LINE_RE.search(sentence)
            or re.search(r"documents?\s*मुझे\s*नहीं|privacy\s*की\s*वजह", sentence, re.I)
        ):
            self.wrong_script.append(sentence.strip())
            return self._closing(terminator)

        if _OTP_RE.search(sentence) and not (
            _OTP_REFUSAL.search(sentence) and not _OTP_ASK_VERB.search(sentence)
        ):
            self.otp_asks.append(sentence.strip())
            if self._turn_refused_otp:
                return safe(_SAFE_OTP_FACT_ONLY)
            return safe(_SAFE_OTP)

        # Money-at-risk is checked FIRST and has no exemption, so the sanctioned
        # IRDAI framing cannot be used to smuggle "और पैसा भी फँस जाएगा" in
        # behind it.
        if _MONEY_AT_RISK_RE.search(sentence):
            self.invented_authority.append(sentence.strip())
            return safe(_SAFE_AUTHORITY)

        if _AUTHORITY_RE.search(sentence) and not (
            _IRDAI_ONLY.search(sentence)
            and not _OTHER_AUTHORITY.search(sentence)
            and _ABOUT_KYC.search(sentence)
            and _ABOUT_ISSUANCE.search(sentence)
            and not _FABRICATED_DETAIL.search(sentence)
        ):
            self.invented_authority.append(sentence.strip())
            return safe(_SAFE_AUTHORITY)

        if (
            re.search(_SENSITIVE_ID, sentence, re.IGNORECASE)
            and re.search(_ASK_SHAPE, sentence, re.IGNORECASE)
            and not re.search(_APP_CONTEXT, sentence, re.IGNORECASE)
            and not _ASKED_IF_FILLED.search(sentence)
        ):
            self.sensitive_id_asks.append(sentence.strip())
            return safe(_SAFE_SENSITIVE_ID)

        if (
            _DOC_CHANNEL_RE.search(sentence)
            and re.search(_DOC_WORD, sentence, re.IGNORECASE)
            and not re.search(_FORM_FIELD_CONTEXT, sentence, re.IGNORECASE)
        ):
            self.wrong_channel_asks.append(sentence.strip())
            return safe(_SAFE_DOC_CHANNEL)

        if (
            _DONE_CLAIM.search(sentence)
            and not re.search(_UI_ACTION, sentence, re.IGNORECASE)
            and not _NEGATED_DONE.search(sentence)
            and not _INSTRUCTED_DONE.search(sentence)
            and not _FAILED_DONE.search(sentence)
            and not self.system_confirms_done
        ):
            self.false_completions.append(sentence.strip())
            return safe(_SAFE_DONE)

        from guardrails import (_CLAIMS_HUMAN_RE, _PRICE_RE, _SAFE_NOT_AI,
                                _SELF_AI_RE)

        # The bot does not announce what it is. It also does not claim to be a
        # person — the replacement is true and says neither.
        if _SELF_AI_RE.search(sentence) or _CLAIMS_HUMAN_RE.search(sentence):
            self.self_ai.append(sentence.strip())
            # Twice in one turn the model described itself twice, and the canned
            # line came back both times — the caller heard the same sentence
            # back to back (Park+ benchmark 2026-09-22). Say it once, then drop.
            if self._said_not_ai:
                return ""
            self._said_not_ai = True
            return safe(_SAFE_NOT_AI)

        if _PRICE_RE.search(sentence):
            self.money_amounts.append(sentence.strip())
            return safe(_SAFE_MONEY)

        if _BOT_SENDS_RE.search(sentence) and not _SEND_EXEMPT.search(sentence):
            self.false_send_promise.append(sentence.strip())
            return safe(_SAFE_SEND)

        if _PROMISE_RE.search(sentence) and _PROMISE_MARKER.search(sentence):
            self.promises.append(sentence.strip())
            return safe(_SAFE_PROMISE)

        # Last of the rewrites. "सरकार के नियम के हिसाब से आपको ये करना ही होगा"
        # is coercive AND a false authority claim; the authority rule above is
        # the more serious of the two and must win, so this sees what is left.
        if _COERCION_RE.search(sentence):
            self.coercion.append(sentence.strip())
            return safe(_SAFE_SOFT_REQUIREMENT)

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
        # Must stay caught: कर ली is past tense, unlike the कर लें invitation
        # exempted in _INSTRUCTED_DONE.
        ("false_completions", "आपकी KYC complete कर ली है मैंने।"),
        ("false_completions", "Maine aapki KYC complete kar li hai."),
        ("false_completions", "Aapki KYC complete ho gayi hai sir."),
        ("false_completions", "KYC done ho gaya sir."),
        ("promises", "पॉलिसी कल तक issue हो जाएगी।"),
        # Park+'s own words on a garbled turn, 2026-09-22 benchmark. The prompt
        # names this exact phrasing as the thing never to say.
        ("coercion", "सर, आपको अभी करना ही पड़ेगा — बिना KYC के policy नहीं जारी होगी।"),
        ("coercion", "आपको ये भरना पड़ेगा सर।"),
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
        # This bot has no price list and no premium on the call card, so every
        # rupee figure it says is one it made up. Same rule as the car spa's,
        # borrowed with its regex.
        ("money_amounts", "सर, आपका premium 7,200 रुपये था।"),
        ("money_amounts", "Aapka refund 5000 rupees ka ho jayega."),
        ("money_amounts", "₹12500 का premium pending है।"),
        # Removed from the prompts 2026-09-21; this is what guarantees it.
        ("self_ai", "मैं AI assistant बोल रही हूँ सर।"),
        ("self_ai", "AI assistant हूँ, Park+ से।"),
        ("self_ai", "हाँ सर, मैं एक bot हूँ।"),
        ("self_ai", "I'm an AI assistant from Park+."),
        # Not announcing what you are is a product decision. Telling a customer
        # you are a person is a lie, on a recorded call.
        ("self_ai", "हाँ सर, मैं इंसान हूँ।"),
        ("self_ai", "I am a real person, not a bot."),
        # IRDAI as a trust badge is a fabricated credential, not the mandate.
        # Round-2 LLM fuzz, 2026-09-19.
        ("invented_authority",
         "Humara IRDAI se approved bima partner hai toh KYC ke time paise "
         "bilkul secure rehte hain."),
        ("invented_authority", "हम IRDAI registered हैं सर, बिल्कुल safe है।"),
        # Nothing in this bot can send a message.
        ("false_send_promise", "मैं आपको link भेज देती हूँ, वहीं से complete कर लीजिए।"),
        ("false_send_promise", "मैं SMS भेज देती हूँ, उसमें link होगा।"),
        # 15:22 call — Ornith English goodbye (one sentence each; a multi-sentence
        # line increments once per sentence).
        ("english_close", "Have a good day."),
        ("english_close", "Goodbye, take care."),
        ("english_close", "Thanks a lot, bye."),
    ]
    for counter, line in blocked:
        before = len(getattr(g, counter))
        out = g.check(line)
        assert len(getattr(g, counter)) >= before + 1, f"{counter} missed: {line!r}"
        assert out != line, f"not rewritten: {line!r}"

    # Topic-aware rewrites (15:18 IRDAI-on-time, 15:45 waiting-line-on-details).
    g_topic = KycGuard()
    g_topic.note_caller("वैसे कि ऐसे करने में कितना टाइम लगेगा?")
    assert g_topic.last_caller_topic == "time"
    out = g_topic.check(
        "सर, payment तो हो चुका है — पर IRDAI के rules के हिसाब से KYC complete "
        "हुए बिना insurance company policy issue नहीं कर सकती। बस दो मिनट का काम है।"
    )
    assert "IRDAI" not in out and "दो मिनट" in out, out
    assert g_topic.wrong_script, "time+IRDAI should land in wrong_script"

    g_topic2 = KycGuard()
    g_topic2.note_caller("एक बार डिटेल्स बता दो ना क्या-क्या है।")
    assert g_topic2.last_caller_topic == "details"
    out = g_topic2.check(
        "सर, form खुल गया है। आप आराम से सारी details complete कर दीजिए। "
        "मैं line पे ही हूँ।"
    )
    assert "form खुल गया" not in out and "nominee" in out.lower() or "खाली" in out, out
    assert g_topic2.wrong_script

    g_topic3 = KycGuard()
    g_topic3.note_caller("ओके ठीक है बाय बाय")
    assert g_topic3.last_caller_topic == "bye"
    out = g_topic3.check(
        "आपके documents मुझे नहीं चाहिए सर — privacy की वजह से ये सब app में ही होता है।"
    )
    assert "documents" not in out.lower() and "धन्यवाद" in out, out


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
        # Both verbatim from the 14:55 call, both rewritten into non-sequiturs.
        "सर, मैं आपकी policy नहीं भर सकती — यह सब कुछ आपके app में ही होगा, "
        "क्योंकि यहाँ मुझे कोई document या OTP माँगने की जगह नहीं है।",
        "सर, ये मुझसे यहाँ से नहीं हो पा रहा — मैं हमारी team को भेज देती हूँ, "
        "वो आपको call करके करवा देंगे।",
        "मैं आपका case team को assign कर देती हूँ सर।",
        # The sanctioned answer to "आप इंसान हो या robot?". It uses the word
        # "assistant" and must NOT trip the rule above.
        "मैं Park+ की calling assistant हूँ सर।",
        # The WhatsApp KYC link, sanctioned by the product owner on 2026-09-20 as
        # the LAST step of the button-not-found ladder. Note the channel is
        # specific: WhatsApp + the KYC link. A bare "link भेज देती हूँ" or an SMS
        # promise stays blocked below, because neither is a thing anyone built.
        #
        # WARNING: nothing in this repo actually sends it. LLM_TOOLS=off and
        # there is no messaging tool, so today this is a promise kept by a human
        # afterwards, not by the bot. Wire a real sender before dialling at scale.
        "सर, मैं आपको WhatsApp पर KYC का link भेज देती हूँ, वहीं से कर लीजिए।",
        "Main aapko WhatsApp pe KYC ka link bhej deti hoon sir.",
        # The policy-delivery answer. It names WhatsApp and a policy in one
        # sentence, which is one word away from three different rules, so it is
        # asserted verbatim.
        "सर, insurer की side से सारी details verify हो जाएँगी, फिर policy आपको "
        "WhatsApp और mail दोनों पे आ जाएगी — app में भी notification आ जाएगा।",
        # Refusing offered documents.
        "आपके documents मुझे नहीं चाहिए सर — privacy की वजह से ये सब app में ही "
        "होता है, मैं यहाँ से नहीं भर सकती।",
        # The rest of the button-not-found ladder.
        "एक काम कीजिए सर — app बंद करके दोबारा खोलिए, फिर insurance page पे देखिए।",
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
        "Park+ Insurance से Shreya बोल रही हूँ।",
        "Payment हो चुका है, बस KYC बाक़ी है।",
        # The sanctioned answers to "अगर न करूँ तो?" and "कब तक?", rendered
        # into the prompt straight from context.json's kyc_mandate. Payment
        # opener dropped 2026-09-21 — IRDAI / cannot-issue is enough; repeating
        # "payment हो चुका" on every बाद में felt like a lecture.
        "सर, IRDAI के rules के हिसाब से KYC complete हुए बिना insurance company "
        "policy issue नहीं कर सकती।",
        "सर, KYC complete हुए बिना IRDAI के rules से policy issue नहीं हो पाती।",
        "नॉमिनी का नाम app में डाल दीजिए।",
        # Inviting them to finish it now is not claiming it is finished.
        "अभी आपके insurance की KYC complete कर लें?",
        # Their future action, not a claim about the present.
        "सर, जैसे ही आप app में KYC complete कर देंगे, policy आ जाएगी।",
        # Says the OPPOSITE of complete, in English.
        "Your payment is done, but the KYC is still pending.",
        "Your KYC is not complete yet sir.",
    ):
        assert g2.check(ok) == ok, f"blocked a legitimate line: {g2.check(ok)!r}"
    rewriting = [c for c, level, _ in KycGuard.COUNTERS if level == "error"]
    assert not any(getattr(g2, c) for c in rewriting), "false positive"

    # The app push is gated on the customer having engaged. Before they say yes
    # or ask how, an app line tacked onto an answer is herding and gets dropped;
    # after, it is the answer they asked for and must survive untouched.
    def _turn_push(caller, reply):
        g = KycGuard()
        g.note_caller(caller)
        return "".join(g.check(x) for x in _SENTENCE_RE.findall(reply) if x.strip())

    ANSWER = "Park+ एक app है सर जहाँ parking और insurance manage होते हैं।"
    PUSH = " अब Insurance icon पर click कर लीजिए।"
    # Pure information question — they never agreed, so only the answer is said.
    assert _turn_push("पाकपस कैसी एप है?", ANSWER + PUSH) == ANSWER
    assert _turn_push("मेरा पैसा फँस गया क्या?", ANSWER + PUSH) == ANSWER
    # ...but when they offer an ID or ask the bot to fill it, "do it in the app"
    # IS the answer — dropping it leaves them nowhere to put the number.
    for app_is_answer in ("मेरा आधार नंबर लिख लो 4321 8765 1234",
                          "आप ही भर दो मेरी details",
                          "क्या-क्या भरना है?"):
        out = _turn_push(app_is_answer,
                         "नंबर मुझे मत बताइए सर। Park+ app खोलकर KYC form में भर दीजिए।")
        assert "app" in out, f"told them nowhere to put it after {app_is_answer!r}"
    # ...and these ARE asking how, so the instruction is what they wanted.
    for asked in ("हाँ बताइए", "अब क्या करना है?", "मुझे समझ नहीं आया क्या करूँ",
                  "process बताओ मुझे", "ठीक है", "Okay so what do I need to do?",
                  "हाँ मैंने app खोल लिया"):
        out = _turn_push(asked, "सर, Park+ app खोलकर Insurance icon पर click कीजिए।")
        assert "Insurance icon" in out, f"instruction dropped after {asked!r}: {out!r}"
    # Engagement latches: they agree once, then ask something else, and the app
    # line still works for the rest of the call.
    g6 = KycGuard()
    g6.note_caller("हाँ ठीक है")
    g6.note_caller("अच्छा ये बताओ पॉलिसी कब आएगी")
    assert "Insurance icon" in g6.check("सर, Insurance icon पर click कीजिए।")

    # DEVANAGARI \b TRAP. Most Hindi words end in a vowel sign (े ी ा ं), which
    # is Unicode category Mn and therefore NOT \w, so a \b written after them
    # never matches and the alternative is silently dead. That is not
    # hypothetical: it killed 8 of the 13 _PROMISE_MARKER entries, and this rule
    # spent that time letting "policy 24 से 48 घंटे में आ जाएगी" reach the
    # caller. Every Devanagari phrase a rule depends on is asserted here, because
    # the pattern still COMPILES and reads correctly when it is broken.
    for phrase in ("48 घंटे में", "24 से 48 घंटे", "दो दिन में", "परसों",
                   "गारंटी", "पक्का"):
        assert _PROMISE_MARKER.search(phrase), f"dead promise marker: {phrase!r}"
    for phrase in ("हाँ", "ठीक है", "जी हाँ", "चलो", "अब क्या करना है",
                   "app खोल लिया"):
        assert _ENGAGED_RE.search(phrase), f"dead engagement marker: {phrase!r}"
    # A real delivery-timing invention must now be caught end to end.
    g_t = KycGuard()
    g_t.note_caller("पॉलिसी कब तक आ जाएगी, कल तक?")
    invented = "फिर policy 24 से 48 घंटे में WhatsApp और mail पर आ जाएगी।"
    assert g_t.check(invented) != invented, "invented a delivery window"

    # NO canned replacement may double the terminator. Sixteen of them appended
    # one unconditionally, and the ones whose own text ends in punctuation spoke
    # "...कब करवा दें?।" — the voice pauses twice on that.
    import itertools
    for name, line in itertools.chain(
        [(n, v) for n, v in globals().items()
         if n.startswith("_SAFE_") and isinstance(v, str)],
        _SAFE_BY_TOPIC.items(),
    ):
        g_t = KycGuard()
        g_t.note_caller("हाँ बताइए")
        out = g_t.check(line if line[-1:] in ".।!?" else line + "।")
        assert not any(d in out for d in ("।।", "?।", "!।", ".।", "।.")), \
            f"{name} doubles its terminator: {out!r}"

    # The sanctioned close is reachable from several rules, so a two-sentence
    # goodbye used to get it twice ("Thank you सर! Have a good day." became
    # "धन्यवाद, thank you for choosing Park+! धन्यवाद, thank you for choosing
    # Park+."). Found replaying 347 spoken lines from call.log through the guard.
    g_c = KycGuard()
    g_c.note_caller("अच्छा ठीक है थैंक यू यार")
    closed = "".join(g_c.check(x) for x in _SENTENCE_RE.findall(
        "Thank you सर! Have a good day.") if x.strip())
    assert closed.count("choosing Park+") == 1, closed

    # The off-topic redirect must SURVIVE the app-push gate. Row 11 used to end
    # "Insurance icon खोलिए?", which the gate drops before they engage — so the
    # redirect vanished and the call just drifted.
    g_o = KycGuard()
    g_o.note_caller("क्रिकेट देख रहे हो आज का मैच?")
    redirect = "मैच का मज़ा लीजिए सर! दो मिनट में KYC निपटा दें?"
    assert g_o.check(redirect) == redirect, g_o.check(redirect)

    # Listing the form fields is an ANSWER, not a document request. Verbatim
    # from the 14:08 call, where "क्या डॉक्यूमेंट चाहिए" got a correct field
    # list and the doc-channel rule replaced it with an upload instruction that
    # answered nothing — it saw "ईमेल" (a field) and "Aadhaar" and fired.
    FIELD_LIST = ("पहले अपने नाम, जन्मतिथि, ईमेल, पता और नामांकित व्यक्ति के बारे "
                  "में भरें — फिर PAN और Aadhaar वाला फॉर्म भरना है।")
    g_f = KycGuard()
    g_f.note_caller("क्या-क्या डॉक्यूमेंट चाहिए होंगे")
    assert g_f.check(FIELD_LIST) == FIELD_LIST, g_f.check(FIELD_LIST)
    # ...while actually asking for an ID by email or WhatsApp still goes.
    for wrong_channel in ("PAN card की copy email कर दीजिए मुझे।",
                          "आप Aadhaar की photo WhatsApp पर भेज दीजिए सर।",
                          "आधार का scan मेल कर दीजिए।"):
        g_w = KycGuard()
        assert g_w.check(wrong_channel) != wrong_channel, wrong_channel

    # The push gate must NEVER empty a turn: a sentence that answers AND pushes
    # keeps its answer. Gemini joined both with an em-dash and the caller heard
    # silence (2026-09-22).
    mixed = ("सर, सुरक्षा कारणों से vehicle number यहाँ से नहीं दिखेगा — आप "
             "Park+ app खोलकर Insurance section में देख सकते हैं।")
    g_m = KycGuard()
    g_m.note_caller("वीकल नंबर बता सकते हो?")
    assert g_m.check(mixed) == mixed, f"ate the answer: {g_m.check(mixed)!r}"
    # A standalone push after an answer still goes.
    g_p = KycGuard()
    g_p.note_caller("किस कंपनी का insurance है?")
    out = "".join(g_p.check(x) for x in _SENTENCE_RE.findall(
        "यह ICICI Lombard का insurance है। App खोलकर KYC complete कर लें?") if x.strip())
    assert "ICICI" in out and "App खोल" not in out, out

    # Asking whether they filled PAN/Aadhaar must survive; asking for the
    # numbers must not.
    for ok_q in ("सर, आपने PAN और Aadhaar दोनों भर दिए थे?",
                 "PAN और Aadhaar details भी भर दी थीं सर?"):
        g_q = KycGuard()
        g_q.note_caller("हाँ कर दिया")
        assert g_q.check(ok_q) == ok_q, f"blocked a fill check: {g_q.check(ok_q)!r}"
    for bad_q in ("सर आपका PAN number बता दीजिए।",
                  "आधार नंबर क्या है आपका?"):
        g_b = KycGuard()
        assert g_b.check(bad_q) != bad_q, f"let an ID ask through: {bad_q!r}"

    # "Complete KYC पे click कर दिया" is ambiguous — two buttons, opposite
    # meanings — so the done answer becomes a question. Saying it plainly told
    # customers sitting in front of an empty form that they were finished.
    DONE_LINE = ("मैं system में check कर लूँगी — आपकी तरफ़ का काम हो गया। "
                 "policy आपको WhatsApp और mail पे आ जाएगी।")
    def _clicked(caller):
        g = KycGuard()
        g.note_caller(caller)
        return "".join(g.check(x) for x in _SENTENCE_RE.findall(DONE_LINE) if x.strip())
    ambiguous = _clicked("हाँ कंप्लीट केवाईसी पे क्लिक कर दिया मैंने")
    assert "भर दी थीं" in ambiguous, ambiguous
    # The replacement says "अगर हाँ तो काम हो गया" — conditional, not a claim.
    # What must NOT survive is the delivery promise.
    assert "WhatsApp" not in ambiguous, ambiguous
    # ...but a click PLUS filling, or a plain submit, really is done.
    for finished in ("complete KYC पे click करके सब भर दिया",
                     "सब भर के submit भी कर दिया"):
        out = _clicked(finished)
        assert "काम हो गया" in out, f"blocked a real completion: {out!r}"

    # A sanctioned line said twice in one call gets its alternate wording. Park+
    # answered two consecutive "बाद में" turns identically on 2026-09-22, three
    # prompt attempts having failed to stop it.
    g_v = KycGuard()
    LINE = "ठीक है सर, कोई दिक्कत नहीं। शाम को call करूँ या कल सुबह?"
    g_v.note_caller("बाद में कर लेंगे")
    assert g_v.check(LINE) == LINE
    g_v.note_caller("यार बाद में करूँगा")
    second = g_v.check(LINE)
    assert second != LINE and "बता दीजिए कब करना है" in second, second
    assert "?" not in second, f"statement kept the question mark: {second!r}"
    assert second.count("सर") == 1, f"doubled honorific: {second!r}"

    # The name is allowed twice a call, then trimmed. Product owner asked three
    # times; the prompt rule never held, so this is deterministic.
    g_n = KycGuard(card={"customer_name": "Anush Gupta"})
    kept = [g_n.check("नमस्ते Anush जी, Park+ से Shreya बोल रही हूँ।"),
            g_n.check("कोई बात नहीं Anush जी, दो मिनट ही लगेंगे।")]
    assert all("Anush" in k for k in kept), kept
    for later in ("Anush जी, आपके insurance की KYC pending है।",
                  "आधार कार्ड भारत सरकार का पहचान पत्र है Anush जी।",
                  "ठीक है Anush जी, मैं कल call कर लूँगी।"):
        out = g_n.check(later)
        assert "Anush" not in out, f"name survived: {out!r}"
        assert " ।" not in out and " ," not in out, f"stray space: {out!r}"
        assert len(out) > 8, f"gutted the sentence: {out!r}"
    # Stating the name is an ANSWER, never trimmed.
    assert "Anush Gupta" in g_n.check("आपका नाम Anush Gupta है।")
    # No card means no name to trim, and nothing changes.
    assert KycGuard().check("Anush जी, KYC pending है।") == "Anush जी, KYC pending है।"

    # A refund / cancellation ask has a real answer: Park+ customer support.
    # Verbatim from the 13:22 call, where the bot said it did not know and the
    # customer was left with nowhere to go.
    DONT_KNOW = "मुझे इसका exact जवाब पता नहीं है सर, team confirm करके बता देगी।"
    for asked in ("अभी छोड़ो यार मेरे को चाहिए नहीं पॉलिसी",
                  "मेरे को पॉलिसी नहीं चाहिए", "refund मिलेगा क्या?",
                  "policy cancel करा दो", "मेरे पैसे वापस चाहिए"):
        g_r = KycGuard()
        g_r.note_caller(asked)
        out = g_r.check(DONT_KNOW)
        assert "customer support" in out, f"no support pointer after {asked!r}: {out!r}"
        assert "।।" not in out and ".।" not in out, f"doubled terminator: {out!r}"
    # ...and a genuinely unknown thing still gets the deflection.
    g_u = KycGuard()
    g_u.note_caller("insurer ने क्यों reject किया?")
    assert g_u.check(DONT_KNOW) == DONT_KNOW

    # Two self-descriptions in one turn get the canned line ONCE.
    g_ai = KycGuard()
    g_ai.note_caller("तुम इंसान हो या रोबोट?")
    doubled = "".join(
        g_ai.check(x) for x in _SENTENCE_RE.findall(
            "मैं एक AI हूँ सर। मैं एक robot हूँ, इंसान नहीं।"
        ) if x.strip()
    )
    assert doubled.count("calling assistant") == 1, doubled

    # The OTP replacement comes in two forms. check() sees ONE SENTENCE at a
    # time, so the "did this turn already refuse" flag has to survive between
    # calls and reset on note_caller — a plain per-call read would make the
    # fact-only branch dead code.
    def _turn(caller, reply):
        g = KycGuard()
        g.note_caller(caller)
        return "".join(g.check(x) for x in _SENTENCE_RE.findall(reply) if x.strip())

    # Refused in sentence one, invented an app-OTP step in sentence two: fix
    # only the invention, do not say the refusal twice.
    both = _turn(
        "OTP आया है मेरे पास, बता दूँ आपको?",
        "OTP किसी को भी नहीं बताएं सर — मुझे भी नहीं। आप अपने app में ही OTP दर्ज करें।",
    )
    assert both.count("मत बताइए") == 0, both
    assert "ज़रूरत ही नहीं पड़ती" in both, both
    # No refusal anywhere in the turn: the replacement has to carry one.
    alone = _turn("OTP बता दूँ?", "OTP बता दीजिए सर, मैं verify कर लूँगी।")
    assert "किसी को मत बताइए" in alone, alone
    # And it never invents an OTP step — there is none in this flow.
    for out in (both, alone):
        assert "app में ही OTP" not in out, out

    # --- rules borrowed from the car spa guard --------------------------------
    # Speaker labels and script drift are MODEL failures, not domain rules — the
    # same class as machine output and thinking-out-loud, which this guard has
    # imported from guardrails.py all along. Insurance was exposed to both.
    g5 = KycGuard()
    # note_caller first: the app line is only allowed once they have engaged,
    # so a fixture with no caller turn at all would be testing the push gate
    # rather than the label stripping this line is about.
    g5.note_caller("हाँ बताइए")
    assert g5.check("Shreya: जी सर, app खोल लीजिए।") == "जी सर, app खोल लीजिए।"
    assert g5.labels == ["Shreya:"]
    g6 = KycGuard()
    assert g6.check("M: आपकी KYC pending है।") == "आपकी KYC pending है।"
    # ...and an ordinary colon is not a label.
    g7 = KycGuard()
    kept = "सर, ये दो चीज़ें चाहिए: PAN और Aadhaar।"
    assert g7.check(kept) == kept and not g7.labels

    # Drift is counted, never rewritten — the text comes back untouched.
    g8 = KycGuard()
    drift = "Aapko sirf PAN number dalna hai, baaki sab ho jayega."
    assert g8.check(drift) == drift, "drift must never be rewritten"
    assert g8.romanised == [drift]
    g9 = KycGuard()
    clean = "सर, PAN number app में डाल दीजिए।"
    assert g9.check(clean) == clean and not g9.romanised, \
        "English nouns that stay English must not read as drift"

    # A whole turn in English carries no romanised Hindi at all, so the function
    # word list never fires on it. Observed on a Park+/Ornith fallback turn.
    g10 = KycGuard()
    english = "Good afternoon. I'm Shreya calling from Park+ Insurance about your vehicle."
    assert g10.check(english) == english, "drift is counted, never rewritten"
    assert g10.romanised == [english]
    # Short Latin chunks are the bot's ordinary vocabulary, not drift. The TTS
    # filter sees chunks, not whole turns.
    for ok_chunk in ("Complete KYC", "Aadhar Front Image", "Next", "PAN Number"):
        g11 = KycGuard()
        assert g11.check(ok_chunk) == ok_chunk and not g11.romanised, ok_chunk

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
    # ...and it must not silence ordinary turns. note_caller first, because the
    # app line is gated on the customer having engaged — see _APP_PUSH_RE.
    g4.note_caller("हाँ ठीक है")
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

    # Prompt scaffolding instead of speech. Both VERBATIM from a Gemini reply
    # on 2026-09-22 that the TTS filter logged as merely "romanised" and would
    # have spoken aloud. Dropped now, and the Hinglish lines beside them prove
    # the check cannot eat ordinary speech.
    scaffold = KycGuard()
    # Engaged, so the app line below is a real instruction rather than a push.
    scaffold.note_caller("हाँ बताइए क्या करना है")
    for junk in ("/Tone: Natural, spoken Hindi, warm, direct.", "    *   No",
                 "Format: two short sentences"):
        assert scaffold.check(junk) == "", junk
    for speech in ("सर, आपके insurance की KYC pending है — दो मिनट लगेंगे।",
                   "Park+ app खोलकर Insurance icon पर click कीजिए।",
                   "धन्यवाद, thank you for choosing Park+।"):
        assert scaffold.check(speech) == speech, speech

    # A \b written through a non-raw Python string becomes a literal 0x08 and
    # the pattern silently stops matching. That is how _NEGATED_DONE lost
    # "not complete" here. Cheap to assert, impossible to eyeball.
    src = io.open(__file__, encoding="utf-8").read()
    for ch in ("\x07", "\x08", "\x0b", "\x0c"):
        assert ch not in src, (
            f"literal {ch!r} in this file — a regex escape went through a "
            "non-raw string and the pattern no longer matches what it reads like"
        )

    print(f"insurance guard ok — {len(KycGuard.COUNTERS)} rules, "
          f"{len(g.insurers)} insurers, upload-only: {sorted(g.upload_only)}")


if __name__ == "__main__":
    _demo()
