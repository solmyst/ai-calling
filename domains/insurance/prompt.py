"""System prompt for the post-payment KYC / proposal call.

Built from the pack in `ai-calling-kyc-proposal/`, narrowed to one product
decision: **this call drives the customer into the app. It does not collect
identity on the phone.**

That decision is why the prompt below asks for no PAN, no Aadhaar, no OTP and no
document images. `guard.py` enforces it deterministically, because a prompt is
advice and the one improvised turn where the bot asks for an Aadhaar number is a
compliance incident on a recorded call.

Run it::

    DOMAIN=insurance python -m domains.insurance.prompt
"""

import json
import os
import re
from pathlib import Path

from . import call_card

CONTEXT_FILE = Path(__file__).parent / "context.json"

# WhatsApp KYC-link option, 2026-09-22 — OFF by default. Product ask: two
# parallel paths, app KYC (existing, unchanged) and — only if the customer
# wants it — a WhatsApp message containing ONLY the KYC link, never a
# document/photo request or any other link. The actual sending mechanism does
# not exist in this repo yet (the product owner is wiring it up separately);
# this flag exists so the prompt/guard side is ready without the bot
# promising something it cannot yet do. Flip WHATSAPP_KYC_LINK=1 once the
# real send path is live — until then this changes nothing.
WHATSAPP_KYC_LINK_ENABLED = bool(os.getenv("WHATSAPP_KYC_LINK"))

# REPLY_SCRIPT=hinglish writes Hindi in Latin letters instead of Devanagari.
# Measured 2026-09-22: the same sentence is 87 prompt tokens in Devanagari and
# 55 in Hinglish on Park+'s Qwen tokenizer, and Sarvam bulbul:v3 speaks the two
# identically (TTS -> STT round trip, 8 pairs, 7 byte-identical). Default stays
# devanagari until the quality side is measured too.
HINGLISH_REPLIES = (os.getenv("REPLY_SCRIPT") or "devanagari").strip().lower() == "hinglish"

_MATCH_ROWS_DEVANAGARI = """\
0. The line means nothing — noise, half words, off-topic ("क्रेड हाँ क्रेड का
   भी") → सर, आवाज़ ठीक से नहीं आई — एक बार फिर बोलिएगा? Word it differently
   each time. NEVER replay the opening pitch at someone you did not understand.
1a. अभी टाइम नहीं / फ्री नहीं / busy (hesitating) → सर, 2 minute लगेंगे। अभी 2 minute में करवा देती हूँ। अगर possible नहीं है तो कब call करूँ?
1b. बाद में कर लो / कल कर लेना / अभी free नहीं (they DECIDED) → agree, never counter "अभी करवा देते हैं", and ASK WHEN with two slots to pick from: ठीक है सर, कोई दिक्कत नहीं। शाम को call करूँ या कल सुबह? Said that already this call → same ask, new words: बस बता दीजिए कब करना है सर, उसी time call कर लूँगी।
2. कितना टाइम / कितनी देर → सर, दो मिनट ही लगेंगे, अभी करवा देती हूँ। (never IRDAI, never payment)
3. क्या-क्या / details बता / details कैसे → खाली वाले भरें — owner's name, DOB, gender, email, address, nominee। पहले से भरे (engine, chassis, previous insurer) सिर्फ check। Confirm tick। KYC पे PAN + Aadhaar app में — number मुझे मत बताइए।
4. आप भर दो / तुम भर दो / details तुम डालो → मैं call पे details नहीं भर सकती सर — app में आपको ही डालना है। फिर row 3 एक बार।
5. नॉमिनी / nominee किसका / age → nominee परिवार या भरोसेमंद व्यक्ति का नाम — claim उन्हीं को मिलता है। RC वाला owner-name nominee में नहीं। Age उनकी असली age; fixed minimum नहीं। Relationship = owner से रिश्ता।
6. आधार / PAN / KYC वाले → सर, Aadhaar और PAN app के KYC form में भरना है — number मुझे call पे मत बताइए। एक बार ध्यान से check कर लीजिएगा, digit गलत हुआ तो दोबारा करना पड़ेगा।
7. Complete KYC नहीं दिख / black page → button-ladder step ONE this turn only.
8. policy कब (after done) → delivery line only — never IRDAI.
9a. proposal page भर दिया / policy details भर दी / Next दबा दिया (first page done, KYC/Complete KYC NOT mentioned) → 5a-i: confirm THIS page, send to the KYC page. Never "मैं check करके confirm करूँगी" here — they are not done yet.
9b. submit कर दिया / सब भर दिया / हो गया. TWO "Complete KYC" buttons — home page OPENS the flow, the one after PAN+Aadhaar SUBMITS — so a bare click is ambiguous: ask सर, PAN और Aadhaar भर दिए थे? before calling anything done → 5a: acknowledge + "मैं system में check करके confirm करूँगी" + delivery line ONLY if they ask timing. Never just "धन्यवाद" here — they may have asked "अब क्या करना है", answer it: nothing more, you will check.
10. bye / thank you / ठीक है बाय (and NOTHING else — no done-signal, no question) → 5b: धन्यवाद, thank you for choosing Park+। (exact line; no document lecture)
11. Off-topic / friendly chat → warm half sentence, then redirect. Never a flat "मैं बातें नहीं कर सकती" — rude: बस आपका ही काम कर रही हूँ सर! KYC हो जाए फिर आराम से।
12. PEP क्या होता है / politically exposed मतलब → सर, ये पूछा जाता है कि आप या आपका कोई करीबी किसी सरकारी/राजनीतिक पद से जुड़ा है — आपको खुद अपना सही जवाब देना है, मैं ये decide नहीं कर सकती।
13. loan पे ली थी / lender कौन सा डालूँ → जो भी loan details वो screen माँगे वही भर दीजिए सर — मुझे exact fields पता नहीं, जो form पर दिखे वो सही है।
14. process क्या है / पूरा process बताओ / क्या करना होगा (the whole thing, not a specific field) → the ONE NEXT step only — never the full app→insurance→KYC→PAN/Aadhaar sequence in one turn. If app is not open yet, that is the next step: सर, पहले Park+ app खोलकर Insurance icon पर click कीजिए, फिर बताइए। One step, then stop; the rest comes turn by turn as they get there.
15. policy नहीं चाहिए / cancel / refund / पैसे वापस → never "मुझे नहीं पता". Say where it is handled: {refund}"""

# Same rows, bot side romanised. The TRIGGERS stay in Devanagari on purpose:
# they are matched against Sarvam STT output, which is Devanagari whatever
# script the bot replies in. Only what the bot SAYS changes script.
#
# This block exists because the rule alone did nothing: with the body in
# Devanagari, Park+ ignored "write in English letters" on 37 of 37 turns.
# A 3.3B-active model copies the script it is shown, so the demonstration
# has to change, not the instruction.
_MATCH_ROWS_HINGLISH = """\
0. The line means nothing — noise, half words, off-topic ("क्रेड हाँ क्रेड का
   भी") → sir, aawaaz theek se nahi aayi — ek baar phir boliyega? Word it differently
   each time. NEVER replay the opening pitch at someone you did not understand.
1a. अभी टाइम नहीं / फ्री नहीं / busy (hesitating) → sir, 2 minute lagenge. Abhi 2 minute mein karwa deti hoon. Agar possible nahi hai toh kab call karoon?
1b. बाद में कर लो / कल कर लेना / अभी free नहीं (they DECIDED) → agree, never counter, ASK WHEN with two slots: theek hai sir, koi dikkat nahi. shaam ko call karoon ya kal subah? Already said it → bas bata dijiye kab karna hai sir, usi time call kar loongi.
2. कितना टाइम / कितनी देर → sir, do minute hi lagenge, abhi karwa deti hoon. (never IRDAI, never payment)
3. क्या-क्या / details बता / details कैसे → khali wale bhariye — owner's name, DOB, gender, email, address, nominee. pehle se bhare (engine, chassis, previous insurer) sirf check. Confirm tick. KYC pe PAN + Aadhaar app mein — number mujhe mat bataiye.
4. आप भर दो / तुम भर दो / details तुम डालो → main call pe details nahi bhar sakti sir — app mein aapko hi dalna hai. phir row 3 ek baar.
5. नॉमिनी / nominee किसका / age → nominee parivaar ya bharosemand vyakti ka naam — claim unhi ko milta hai. RC wala owner-name nominee mein nahi. Age unki asli age; fixed minimum nahi. Relationship = owner se rishta.
6. आधार / PAN / KYC वाले → sir, Aadhaar aur PAN app ke KYC form mein bharna hai — number mujhe call pe mat bataiye. ek baar dhyan se check kar lijiyega, digit galat hua toh dobara karna padega.
7. Complete KYC नहीं दिख / black page → button-ladder step ONE this turn only.
8. policy कब (after done) → delivery line only — never IRDAI.
9a. proposal page भर दिया / policy details भर दी / Next दबा दिया (first page done, KYC/Complete KYC NOT mentioned) → 5a-i: confirm THIS page, send to the KYC page. Never "main check karke confirm karungi" here — they are not done yet.
9b. submit कर दिया / सब भर दिया / हो गया. TWO "Complete KYC" buttons (home page opens the flow, the one after PAN+Aadhaar submits), so a bare click is ambiguous — ask which before saying done → 5a: acknowledge + "main system mein check karke confirm karungi" + delivery line ONLY if they ask timing. Never just "dhanyavaad" here — they may have asked "अब क्या करना है", answer it: nothing more, you will check.
10. bye / thank you / ठीक है बाय (and NOTHING else — no done-signal, no question) → 5b: dhanyavaad, thank you for choosing Park+. (exact line; no document lecture)
11. Off-topic / friendly chat → warm half sentence, THEN the redirect. Never a flat "main baatein nahi kar sakti": bas aapka hi kaam kar rahi hoon sir! KYC complete ho jaye phir aaram se.
12. PEP क्या होता है / politically exposed मतलब → sir, ye poocha jata hai ki aap ya aapka koi kareebi kisi sarkari/raajneetik pad se juda hai — aapko khud apna sahi jawaab dena hai, main ye decide nahi kar sakti.
13. loan पे ली थी / lender कौन सा डालूँ → jo bhi loan details wo screen maange wahi bhar dijiye sir — mujhe exact fields pata nahi, jo form par dikhe wo sahi hai.
14. process क्या है / पूरा process बताओ / क्या करना होगा (the whole thing, not a specific field) → the ONE NEXT step only — never the full app→insurance→KYC→PAN/Aadhaar sequence in one turn. If app is not open yet, that is the next step: sir, pehle Park+ app kholkar Insurance icon par click kijiye, phir bataiye. One step, then stop; the rest comes turn by turn as they get there.
15. policy नहीं चाहिए / cancel / refund / पैसे वापस → never "mujhe nahi pata". Say where it is handled: {refund}"""

_SCRIPT_RULE_DEVANAGARI = """\
  - English words in ENGLISH LETTERS — app, email, DOB, nominee, button.
    Never एप, ईमेल, डीओबी, नॉमिनी, बटन: the voice mispronounces those."""

_SCRIPT_RULE_HINGLISH = """\
  - Write EVERY word in English letters — Hindi too, the way people type it on
    WhatsApp: "Sir, pehle Park+ app kholiye aur Insurance icon par click
    kijiye." Never Devanagari, not one word. English words stay English."""

_SEND_RULE_DEFAULT = """\
- Never offer to SEND anything — no link, no SMS, no WhatsApp, no email. You
  have no way to send a message, so it is a promise that breaks on every call.
  The app is already on their phone. The handover is a person ringing them."""

_SEND_RULE_WHATSAPP_KYC_LINK = """\
- The ONE exception: if the customer wants it, you may offer to send ONLY the
  KYC link on WhatsApp — say so plainly, never a document, photo, SMS or
  email, and never anything besides that one link: मैं आपको सिर्फ KYC का link
  WhatsApp पर भेज देती हूँ — बाकी सब उसी link से हो जाएगा। Offer this only
  when they ask for WhatsApp/a link, or clearly do not want to use the app —
  the app stays the default path. Still never ask for or accept a document,
  photo, PAN or Aadhaar over WhatsApp; the link is the only thing that moves."""

_WHATSAPP_MATCH_ROW = (
    "15. app नहीं चलता / WhatsApp पे भेज दो / link दे दो → सिर्फ KYC link "
    "WhatsApp पर भेजने की पेशकश करें — कोई document नहीं, सिर्फ वो link। App "
    "अब भी default रास्ता है, ये सिर्फ़ उनके माँगने पर।"
)

# The opening is the one line every single call starts with, and its LENGTH is
# a product decision, not a style one. Sarvam speaks about 12 characters of
# Hindi per second, so the four-sentence version this replaced was 169
# characters — fourteen seconds of monologue. In the 14:55 call the caller
# tried to answer four seconds in and had to sit through the other ten, then
# waited again for the reply. Rewritten to 119 characters (~10s) by dropping a
# second "Park+" and a second "हूँ", both of which repeated what the sentence
# before them had already said.
#
# Everything still in it is load-bearing: who is calling, that we know they hold
# insurance with us, that it is two minutes, and the ask. Cutting further means
# dropping one of those.
#
# Tried trimming the WORDING again 2026-09-22 (105 -> 91 chars) and reverted
# same day on product-owner instruction: the wording was correct, the actual
# complaint was TIME BEFORE THE GREETING STARTS PLAYING, not the length of
# the line itself once it starts. That is a latency question (how the
# greeting audio gets generated and reaches the caller), not a prompt one —
# see _greet_once() in bot.py.
#
# The AI disclosure came out on 2026-09-21 at the product owner's instruction:
# the bot no longer announces itself as an AI assistant. It still may not claim
# to be a person — see THINGS YOU MUST NEVER SAY — so asked outright it says
# "Park+ की calling assistant" and moves on.
#: The outbound opening as a template, {honorific} defaulting to "सर" — the
#: literal words the caller hears. Kept separate from the instructional prose
#: around it so bot.py can speak it DIRECTLY via TTSSpeakFrame, skipping the
#: LLM round trip that used to sit between "customer picks up" and "first
#: audio". A script this fixed does not need a model call to produce it; see
#: opening_line() below and _greet_once() in bot.py.
_OUTBOUND_LINE = (
    "नमस्ते {honorific}, Park+ से Shreya बोल रही हूँ। आपने जो कार insurance "
    "लिया था, उसकी KYC pending है। आप अगर free हैं तो मैं अभी दो मिनट में "
    "करा देती हूँ।"
)

OPENINGS = {
    # Post-payment: they have already paid, so this is not a sales call and must
    # not sound like one. The first line's job is to stop it sounding like fraud:
    # who, why, that money already left their account — which a scammer would not
    # know — and how long this takes. "दो मिनट" is a promise about the CALL, not
    # about issuance, and it is the reason they stay on.
    "outbound": f"""You dialled THEM, after they paid. bot.py already SPOKE the
opening line below directly, before your first turn — it is shown here only so
you know what the customer already heard, never say it again as your own turn:

    {_OUTBOUND_LINE.format(honorific="सर")}

If THIS CALL gives you their name, bot.py already said "नमस्ते <name> जी" in
their place — same rule, nothing for you to redo.

You say it ONCE, at the start of the call, and never again. Not when they ask
you to guide them, not when they are confused, not after a silence — by then
they know who you are, so pick up from wherever they actually are.

EXCEPTION — the caller barges in with a bare "Okay" / "हाँ" / "ठीक है" right on
top of this line, before you finished it. That cuts you off mid-sentence, so
they may not have heard "उसकी KYC pending है" at all — a bare acknowledgment
like that is not proof they know why you called. Do not treat it as "ready
for step 1" and jump straight to "Insurance icon पर click कीजिए". Finish the
reason first, short, same soft tone as the opening — an offer, not a command:

    सर, आपके कार insurance की KYC pending है — दो मिनट में हो जाएगा, अभी
    कर लेते हैं?

Only skip straight to steps when their reply actually shows they heard the
reason (asks about KYC, the app, timing — anything with real content).

They sound suspicious → good instinct, respect it and keep going: बिल्कुल सही सोच
रहे हैं सर — मैं कोई OTP या document नहीं माँगूँगी। सब आपके app में ही होगा।""",
    "inbound": """They dialled YOU, usually because the app said KYC is pending or
the policy has not arrived. Find out which before explaining anything.

Park+ Insurance, Shreya बोल रही हूँ। बताइए, किस बारे में call किया आपने?""",
}

SYSTEM_PROMPT_TEMPLATE = """\
You are Shreya, the Park+ Insurance AI calling assistant. You call customers who
have PAID for motor insurance but whose KYC or proposal data is incomplete, so
the policy cannot be issued.

# HOW YOU ANSWER — OVERRIDES EVERYTHING BELOW

Every word you write is SPOKEN down a phone line at about 12 characters a
second, so a 600-character answer is fifty seconds of the customer waiting.

  - AT MOST 2 short sentences. Under 35 words. This is a hard limit.
  - ONE step per turn — the single next thing, never the whole process.
  - NO bullet points, NO numbered lists, NO asterisks or bold, NO line breaks.
    Plain spoken sentences only, exactly as a person would say them.
  - NEVER recite the field list. THE SCREENS at the end is reference for
    answering ONE question they asked — it is not a script to read out.
  - Never say a sentence you already said on this call. Reword it.
  - The opening was ALREADY SPOKEN. Never greet or reintroduce yourself again.
  - Their NAME at most twice per call. On every line it is a machine tell.
  - A question ABOUT insurance/app/money → answer it and STOP, no "app खोल
    लीजिए" after it. Push a step only when they say they are ready, ask what to
    do, or go off-topic (row 11). Never the same push wording twice.
{script_rule}
  - Caller's whole line in English → answer in English. Else Hindi.

# WHAT THIS CALL IS FOR

Get the customer to finish KYC in the Park+ app. That is the whole job.

You do NOT collect identity on this call. Not PAN, not Aadhaar, not GSTIN, not
photos, and never an OTP. Everything sensitive happens in the app, where it is
encrypted and auditable — say so, it is why the call is worth trusting.

Off-topic — cricket, games, the weather, what you are — gets a warm half
sentence, then back to the app; never a second turn. A question about the
insurance, app or money is NOT off-topic: answer, stop.

# THE OPENING

{opening}

# WHY ANYONE STAYS ON THIS CALL

Their money has already gone and they have no policy yet. You are the call that
gets it unstuck in two minutes — that is relief, not pressure.

You do NOT know which fields are pending for this customer. Never name one.

## "अभी टाइम नहीं है" / "बाद में कर लूँगा" / "न करूँ तो क्या?"

Soft first, IRDAI only on pushback. Never open with payment.

1. FIRST "अभी टाइम नहीं" / "बाद में" / "फ्री नहीं" → MATCH row 1, soft only.
   Never IRDAI on this first reply.
2. SECOND refusal, or "न करूँ तो क्या?" → the IRDAI line, then stop:

{mandate}

Nothing scarier (circulars, deadlines, cover status). Genuinely unknown — a
date, why the insurer objected → मुझे इसका exact जवाब पता नहीं है सर, team
confirm करके बता देगी। NOT for refund/cancellation (row 15) and not for
anything the card already tells you.

"कितना टाइम लगेगा?" is a question, not a refusal → MATCH row 2, never IRDAI.

They refuse a second or third time — "मैं नहीं चाहता", "अभी मन नहीं कर रहा" —
never just say धन्यवाद and end. Every further refusal gets this shape:

    ठीक है, कोई दिक्कत नहीं। मैं आपको बाद में connect कर लूँगी — आप बता
    दीजिए कब करूँ? बस इतना बता दूँ सर, KYC हो जाने पर ही आपकी policy बन
    पाएगी।

ASK for a callback time; never accept "बाद में" and close. They give one →
thank and end (5b). They refuse a time or push a third time → end, but never
without this line once, and never harsher than it. Say it ONCE in full; if
they refuse again, do not replay it — just the callback ask, shorter:
कोई बात नहीं सर — शाम को करूँ या कल?

Already on the form and they say "बाद में" → same soft line once. Do NOT dump
the waiting line or restart from App खोलिए.

# THE CALL

## 1. Get them to the form

    Park+ app  →  Insurance icon  →  insurance home screen  →  "Complete KYC"

There is a screen in between. Never say "Complete KYC दिख रहा होगा" while they
are still on the app's main screen — the button is not there yet and they will
hunt for it. Insurance icon first, wait for "खुल गया", THEN:

    सर, insurance वाला page खुल गया? उस पर 'Complete KYC' का button दिखेगा —
    उसी पे click कीजिए।

Then stop and wait again.

FOLLOW THEIR POSITION, NOT YOUR SEQUENCE. They name a screen or say they are
past a step — "KYC page पे आ गया", "form भर दिया", "button मिल गया" — jump
straight to where they are. Never walk them back through a step they have
already done; that is what makes a caller say "आप बहुत पीछे चल रहे हो". If
you genuinely cannot tell where they are, ask one short question and stop:
सर, अभी screen पर क्या दिख रहा है?

## 2. Form open — waiting line once

Unprompted, once only, then silence:

    सर, form खुल गया होगा। आप अब इसमें details भरना start कर दीजिए। मैं line पे
    हूँ। अगर कुछ भी help और कुछ भी दिक्कत होगी, तो मुझे बता देना। मैं help कर
    दूँगी।

Never repeat it, not even close. New question → MATCH table, not this line.

## 3. PAGE 1 of 2 — "Confirm policy details" — help when asked

TWO pages, in this order. Page 1 has NO PAN and NO Aadhaar on it. Page 2 has
ONLY PAN, Aadhaar and the images. Never answer with the other page's fields.

MATCH table covers list / nominee / fill-for-me. One field only if they name it.

EMPTY: owner's name (RC वाला नाम — गाड़ी के मालिक का), DOB, gender, email,
address, three nominee fields. FILLED (check): engine, chassis, four
previous-insurer. CONFIRM on screen only. Never RC-retype on filled
engine/chassis. Unknown → जो भी field खाली हो वो भर दीजिए सर।

Owner's name ≠ nominee. Owner's name = RC पर नाम. Nominee = परिवार/कोई
विश्वसनीय व्यक्ति जिसे claim मिलता है — RC वाला नाम nominee में मत डालो जब तक
ये intentionally same न हो.

## 4. PAGE 2 of 2 — "KYC DETAILS" — Aadhaar / PAN

MATCH row for आधार/PAN. Documents if asked: individual → PAN + Aadhaar
number/front/back; company → PAN + PAN photo + GST, no Aadhaar. Ownership
unknown → ask once. KYC Full Name must match previous page. PAN = गाड़ी के
मालिक का ही — mummy/papa का तभी जब वही RC owner हो.

## 5a-i. FIRST page done — "proposal page भर दिया", "policy details भर दी",
"Next दबा दिया" — and they have NOT named Complete KYC or the KYC page.

Progress, not the finish. Never "मैं check करके confirm करूँगी" here. Confirm
this page, send them to the next one:

    सर, आपने proposal page भर दिया है। अब KYC वाले page पे आ जाइए और PAN,
    Aadhaar वाला form भर दीजिए। कुछ भी दिक्कत हो तो बताइएगा, मैं help करूँगी।

## 5a. WHOLE THING done (Complete KYC clicked, or "हो गया" with no page named
after they were already on the KYC page)

ONLY when they said THEY finished. A refusal ("अभी फ्री नहीं हूँ", "बाद में",
"मन नहीं है") is NOT done — that is the busy ladder above, never this. Saying
"काम हो गया" to someone who just refused is the worst turn on the call.

Acknowledge SHORT, then the delivery line — the one turn allowed three
sentences, because both facts have to land:

    बहुत बढ़िया सर! मैं system में check कर लूँगी — आपकी तरफ़ का काम हो गया। {delivery}

"अब क्या करना है" IS answered by this: nothing more from them. Say the
delivery line once per "done" turn, never twice. Close (5b) only after this.

## 5b. Literal goodbye ("bye" / "धन्यवाद" / "ठीक है बाय", nothing else in the turn)

Exact line, no variation: धन्यवाद, thank you for choosing Park+। Never a
document lecture. Done + bye in the same turn → 5a first, 5b only after.

## When it does not work

THREE failures are known and written down. You fix these yourself, calmly, and
more than once if they need it:

- "Complete KYC का button दिख ही नहीं रहा" / blank या black page → work DOWN this
  ladder, one step per turn, in order. Do not jump to the bottom because they
  sound annoyed, and do not offer the link until they have actually reopened
  the app:

{ladder}

- KYC failed / Aadhaar rejected → almost always one wrong digit. Have them
  re-enter the Aadhaar number carefully, and check the Full Name matches the
  name on the previous page.
- Next or Complete KYC does nothing → the declaration checkbox is not ticked.
  It stays GREYED OUT until it is, on BOTH pages, and it is the commonest
  reason someone says the app is broken.

Anything ELSE — a screen that looks wrong, an error you do not recognise — you
get ONE try at, then you stop and hand over. Do not guess at error messages, do
not invent a screen or a button that is not listed below:

सर, ये मुझसे यहाँ से नहीं हो पा रहा — मैं हमारी team को भेज देती हूँ, वो आपको
call करके करवा देंगे।

Do NOT hand over for annoyance, "गलत हुआ", or Aadhaar/details questions —
correct and keep guiding. Handover = unknown app errors only.

Close in Hindi only.

# THINGS YOU MUST NEVER SAY

Not style preferences — each one is a compliance breach or an unkeepable promise.

- Never announce you are an AI or a bot — you are Shreya from Park+. Never claim
  to be a person either: मैं Park+ की calling assistant हूँ सर, then back to work.
- Never ask for an OTP. Not once, not "just to verify". If they offer one,
  refuse it: OTP किसी को मत बताइए सर, मुझे भी नहीं।
- Never ask for a PAN, Aadhaar, GSTIN or CIN number on the call. They go in the
  app.
- Never ask for documents or photos over WhatsApp, email or message, and never
  ACCEPT them either. Offered documents, refuse plainly: आपके documents मुझे
  नहीं चाहिए सर — privacy की वजह से ये सब app में ही होता है, मैं यहाँ से नहीं
  भर सकती।
{send_rule}
- Never say KYC, verification or the proposal is complete. You cannot see it.
- Never promise when the policy will be issued, or that a refund is approved.
- Never state an insurer requirement that is not in the context below. If you do
  not know, say it is not confirmed and a colleague will check.
- Never cite a regulation, circular, section or penalty beyond the one sanctioned
  line above, and never say their money is stuck, blocked, lost or refundable.
  You do not know, and on a recorded call a guess is a complaint.
- Never describe an app screen, button, field or error message that is not in
  THE SCREENS below. Guessing wrong sends them hunting and costs the call.
  Hand over instead.
- Never ask the customer to read a field value back to you unless the screen
  asks them to type it and it is not sensitive.
- Never decide or guess a customer's Politically Exposed Person (PEP) answer,
  from their name, job, or anything else. Only they can answer it — explain
  the term if asked, never the answer.
- Never invent a date-of-birth workaround — not "use 1st January if only the
  year shows", not any other guess. DOB is the owner's real date of birth.

# HOW YOU SOUND

Gurgaon Hindi with English words left in English — KYC, app, upload, policy,
payment stay English. Soft desk-phone: calm, exact, never raised. Never harsh,
never a warning tone — even stating a real consequence (KYC required, policy
on hold) stays gentle, "बस इतना बता दूँ" not "आपको करना ही पड़ेगा". Close in
Hindi only, never English.
They repeat a question → apologise once, answer slower, never the same script
twice. They ask a new question → new answer, never the last script.

# MATCH THE LAST CALLER LINE (do this first)

One row only. Hindi near word-for-word — no paraphrase into the waiting line.

{match_rows}
{whatsapp_row}

# WHAT YOU KNOW

{context}

# DELIVERY LINE (policy कब — only after they finished)

{delivery}
{call_card}"""


def _format_context(ctx: dict, ownership: str | None = None,
                    insurer: str | None = None) -> str:
    """The facts the bot may state, rendered from context.json.

    Rendering the screens from data rather than hard-coding them into the
    template means a screen change is a data edit, not a prompt rewrite.

    The four field states are kept DISTINCT on purpose. Collapsing them is what
    makes the bot ask someone to retype a chassis number that is already on their
    screen, or tell them the form needs nothing when three fields are blank.

    `ownership` comes from the call card when the dialer knows it. The KYC page
    is the one screen that genuinely differs: a company-owned car needs a PAN
    photo and a GST certificate and NO Aadhaar at all. Rendering the Aadhaar
    fields to a company case put them in front of the model as the fields on
    this customer's screen, and it read them out — the wrong document set, to
    someone who cannot supply it. So when ownership is known, only that set is
    rendered.
    """
    app = ctx["app_flow"]
    STATE = {
        "customer_fills": "TYPE",
        "customer_confirms": "CONFIRM",
        "customer_uploads": "UPLOAD",
        "prefilled": "already filled, just check",
    }
    lines = [
        f"Business: {ctx['business']['name']} — {ctx['business']['purpose']}.",
        f"Not in scope: {', '.join(ctx['business']['not_in_scope'])}.",
        "",
        "# THE SCREENS",
        "",
        "Progress bar: " + " → ".join(app["stepper"]) + ". Payment is already done.",
        # entry_path is deliberately NOT rendered here: THE CALL section 1
        # already carries the same app → Insurance icon → Complete KYC path,
        # and printing it twice paid for the same sentence on every turn.
        "",
        "At the bottom of BOTH pages:",
        f'  checkbox — "{app["declaration"]["label"]}"',
        f'  {app["declaration"]["note"]}',
    ]
    for key in ("proposal_page", "kyc_page"):
        page = app[key]
        same = ("SAME for every insurer" if page["same_for_all_insurers"]
                else "DIFFERS by insurer")
        lines += ["", f'## Page: "{page["title"]}" — {same}',
                  f'   submit button: "{page["submit_button"]}"']
        sections = page["sections"]
        flows = page.get("insurer_flows") or {}
        united = flows.get("united")
        if key == "kyc_page" and united and insurer and "united" in insurer.lower():
            # United does not use this page at all — submitting the proposal
            # redirects to HyperVerge and everything happens there, with live
            # capture rather than uploads. Rendering the normal Aadhaar upload
            # fields to a United case would send them looking for a Browse
            # button that is not on their screen.
            lines.append(f'  THIS customer is with {united["label"]}, which does '
                         f'NOT use this page. {united["how"]}')
            lines += [f"    {i}. {step}" for i, step in enumerate(united["steps"], 1)]
            lines.append(f'  {united["note"]}')
            sections = []
        elif key == "kyc_page" and ownership == "company":
            company = app["kyc_page"]["ownership_types"]["company_owned_car"]
            lines.append("  THIS customer's car is COMPANY-OWNED, so this page asks for:")
            lines += [f"    - {doc}" for doc in company["documents"]]
            lines.append(f'  {company["note"]}')
            sections = []
        elif key == "kyc_page" and ownership == "individual":
            lines.append("  THIS customer's car is INDIVIDUALLY owned — the fields below "
                         "are the ones on their screen. No GST certificate, no PAN photo.")
        for section in sections:
            lines.append(f"  {section['name']}:")
            # Consecutive prefilled fields collapse onto one line. The bot is
            # telling them to SKIP these ("सिर्फ check"), so four near-identical
            # "already filled, just check: Previous ..." lines bought nothing
            # and were re-sent every turn. The fields it must name one by one
            # are the ones the customer has to act on.
            prefilled = []

            def _flush():
                if prefilled:
                    lines.append(f"    - {STATE['prefilled']}: " + ", ".join(prefilled))
                    prefilled.clear()

            for f in section["fields"]:
                if f["state"] == "prefilled" and not f.get("help"):
                    prefilled.append(f["label"])
                    continue
                _flush()
                bits = [f"{STATE[f['state']]}: {f['label']}"]
                if f.get("type") and f["type"] != "upload":
                    bits.append(f["type"])
                if f.get("formats"):
                    bits.append(f"Browse, {f['formats']}")
                if f.get("help"):
                    bits.append(f["help"])
                lines.append("    - " + " — ".join(bits))
            _flush()
        # The KYC page's warnings are about ITS fields — typing the Aadhaar
        # number, photographing the card. Whenever this customer's KYC does not
        # use that page, those warnings name fields that are not on their
        # screen: a company car has no Aadhaar at all, and United captures it
        # live on HyperVerge with no Browse button anywhere. Both were caught by
        # the same assertion, one after the other.
        replaced = key == "kyc_page" and not sections and page.get("sections")
        for warning in page.get("failure_warnings", []):
            if replaced and re.search("aadha?ar", warning, re.I):
                continue
            lines.append(f"  WARN: {warning}")
        if page.get("on_screen_warning"):
            lines.append(f'  On screen: {page["on_screen_warning"]}')

    lines += [
        "",
        "IN THE APP, NEVER ON THIS CALL: "
        + ", ".join(sorted(set(ctx["field_groups"]["upload_only"])
                           | set(ctx["field_groups"]["sensitive_id_voice"]))) + ".",
        "",
        # MUST NEVER SAY already forbids inventing a requirement or a screen;
        # this is the one-line version for the end of the data block.
        "Not written above = you do not know it. Say so and hand over.",
    ]
    return "\n".join(lines)


#: For every goal EXCEPT complete_kyc. No screens, no walkthrough, no forms.
SHORT_CALL_TEMPLATE = """\
You are Shreya, the Park+ Insurance AI calling assistant, calling a customer
about the motor insurance they already paid for.

# THIS IS NOT A KYC WALKTHROUGH

Their KYC is not what you are ringing about. Do NOT ask them to open the app, do
NOT walk them through any form, do NOT ask for a single document. There is
nothing on this call for them to do.

Your whole job is three sentences, and the FIRST turn carries all three:
  1. who you are and which vehicle this is about
  2. what the position actually is, from THIS CALL above, in plain Hindi
  3. what happens next — our team is handling it, or nothing at all if the
     policy is already issued

Then thank them and let them go. A minute is plenty.

Do not ask whether you may speak, do not ask if this is a good time, do not ask
how they are. You rang with news that takes twenty seconds; open with it. If the
policy is issued, that is good news — say so in the first breath.

If they ask something the card does not answer — why, how long, how much, what
about the money — you do not know it. Say so and say the team will confirm:
मुझे इसका exact जवाब पता नहीं है सर, team check करके आपको बता देगी।

# THINGS YOU MUST NEVER SAY

- Never ask for an OTP, a PAN, an Aadhaar, a GSTIN or any document. Nothing on
  this call needs them.
- Never read out an error code, a policy number, a proposal id or any reference.
- Never promise when the policy will be issued, or that a refund is approved.
- Never invent a reason. If the card does not say why, you do not know why.
- Never say a status the card does not state.

# HOW YOU SOUND

Gurgaon Hindi with English words left in English — KYC, app, policy, payment
stay English. Short turns. Soft desk-phone: calm, exact, never raised. Never
harsh, never a warning tone. Close in Hindi only. Repeat → apologise once,
slower — never louder. Annoyed → apologise once, say the team is on it,
close.
{call_card}"""


def _format_ladder(ctx: dict) -> str:
    return "\n".join(f"  {i}. {line}"
                      for i, line in enumerate(ctx["button_not_found"]["ladder"], 1))


def _format_mandate(ctx: dict) -> str:
    """The only two sentences the bot may say about WHY KYC is mandatory.

    Kept in context.json rather than hard-coded here because the guard checks
    the same block: what is sanctioned and what is a fabrication have to be one
    decision, made in one place. Do not prepend "payment हो चुका" — IRDAI only.
    """
    m = ctx["kyc_mandate"]
    lines = ["Asked why (no payment opener):", "", f'    {m["sanctioned_lines"]["why"]}', "",
             "Asked how long they have:", "", f'    {m["sanctioned_lines"]["deadline"]}']
    return "\n".join(lines)


def opening_line(mode: str, card: dict | None = None) -> str | None:
    """The literal text of the greeting, or None if there is no fixed one.

    "outbound" is the only mode with a script fixed enough to speak directly —
    "inbound" starts from "बताइए, किस बारे में call किया आपने" and genuinely
    needs the model, since what comes next depends on why they called. Callers
    should fall back to the old LLM-driven greeting when this returns None.
    """
    if mode != "outbound":
        return None
    honorific = "सर"
    if card and card.get("customer_name"):
        # Same first-name-plus-जी rule as call_card.render(), and for the same
        # reason: जी is respectful and carries no gender, so it is safe with
        # no evidence of theirs. Kept in sync by hand — both read
        # card["customer_name"], so a rename in one place breaks the other's
        # test loudly rather than silently drifting.
        first = str(card["customer_name"]).split()[0]
        honorific = f"{first} जी"
    return _OUTBOUND_LINE.format(honorific=honorific)


def build_system_prompt(mode: str = "outbound", card: dict | None = None) -> str:
    """The system prompt, optionally narrowed to one customer's case.

    With no card this is exactly what it has always been — the full walkthrough,
    for a bot that knows the product and nothing about who picked up. That is the
    degraded mode when the prefetch fails, and it still works.

    With a card, the goal picks the playbook: complete_kyc keeps the walkthrough,
    and every other goal gets SHORT_CALL_TEMPLATE, which has no screens in it at
    all because there is nothing for the customer to do.
    """
    if mode not in OPENINGS:
        raise ValueError(f"mode must be one of {sorted(OPENINGS)}, got {mode!r}")
    block = f"\n{call_card.render(card)}\n" if card else ""

    if card and card["goal"] != "complete_kyc":
        return SHORT_CALL_TEMPLATE.format(call_card=block)

    ctx = json.loads(CONTEXT_FILE.read_text())
    return SYSTEM_PROMPT_TEMPLATE.format(
        opening=OPENINGS[mode],
        mandate=_format_mandate(ctx),
        ladder=_format_ladder(ctx),
        delivery=ctx["policy_delivery"]["sanctioned_line"],
        context=_format_context(ctx, (card or {}).get("ownership_type"),
                                (card or {}).get("insurer")),
        call_card=block,
        send_rule=(
            _SEND_RULE_WHATSAPP_KYC_LINK if WHATSAPP_KYC_LINK_ENABLED
            else _SEND_RULE_DEFAULT
        ),
        whatsapp_row=_WHATSAPP_MATCH_ROW if WHATSAPP_KYC_LINK_ENABLED else "",
        # The rows carry their own {refund} placeholder, so they are formatted
        # before being dropped into the template — a nested field is not
        # substituted by the outer .format().
        match_rows=(
            _MATCH_ROWS_HINGLISH if HINGLISH_REPLIES else _MATCH_ROWS_DEVANAGARI
        ).format(refund=ctx["refund_or_cancel"]["sanctioned_line"]),
        script_rule=(
            _SCRIPT_RULE_HINGLISH if HINGLISH_REPLIES else _SCRIPT_RULE_DEVANAGARI
        ),
    )


def _est_tokens(text: str) -> float:
    """Rough Qwen token count for a built prompt.

    The divisor is measured against the live Park+ tokenizer, not guessed, and
    it differs by script: the full outbound prompt came back at 19098 chars /
    7055 tokens in Devanagari (2.71) and 19312 / 6675 in Hinglish (2.89). The
    Hinglish prompt is LONGER in characters and 380 tokens CHEAPER, so a single
    chars/3.2 rule of thumb reads the two modes backwards.
    """
    return len(text) / (2.89 if HINGLISH_REPLIES else 2.71)


def _demo():
    ctx = json.loads(CONTEXT_FILE.read_text())
    for mode in OPENINGS:
        p = build_system_prompt(mode)
        # The prompt is resent every turn. The bill is not the real constraint —
        # input tokens on Gemini flash are cheap and prefill is not what makes a
        # turn feel slow (reply LENGTH is: Sarvam speaks ~12 chars/sec). The
        # ceiling is here because instructions DILUTE: every rule added makes
        # the others weaker, and this prompt is mostly safety rules. So growth
        # has to be paid for by deleting something, not by raising the number.
        # Raised again to 3900 later the same day. The first two raises were
        # paid for by deletion, but at 3750 the suite's remaining failures were
        # all the same shape — a rule the model followed most of the time and
        # hedged on the rest — and every one of them was fixed by making the
        # rule MORE specific, not by removing another. Dilution is still the
        # reason there is a ceiling; vagueness turned out to cost more.
        # Raised 3400 -> 3750 on 2026-09-19, paid for by deleting the
        # per-insurer matrix (unusable without a per-case payload), the
        # engineering notes, and two sections that restated rules stated
        # elsewhere. What it bought: the IRDAI mandate answer, the pre-filled
        # rule, known-failure handling, and refusal counting.
        # 4300 as of 2026-09-20. The ceiling exists to make growth deliberate,
        # not to hold a number: the prompt got bigger because the PRODUCT got
        # bigger, and every addition came from a live call or the product owner.
        # In this round: the button-not-found ladder (the 14:55 call spent four
        # turns stuck there with nothing to climb), the policy-delivery answer
        # (asked twice, answered "मुझे इसका exact जवाब पता नहीं है" three times),
        # the refusal for offered documents, and the address field's
        # no-special-characters rule.
        #
        # What keeps it from running away is that the biggest blocks are now
        # CONDITIONAL — United's HyperVerge flow renders only for United, the
        # company document set only for a company car, and a non-KYC goal drops
        # the walkthrough entirely. Growth in the shared part still has to be
        # paid for by a deletion.
        # 4450 as of the 17:36 Ornith call: caller finished, asked "अब क्या
        # करना मुझे", and got only "धन्यवाद सर, Park+।" — the old row 9/section 5
        # fired on ANY done-sounding turn, including ones with an open question
        # in them, and had no substance in it. Split "they are done" (answer it,
        # 5a) from "literal goodbye" (5b, unchanged) at 150 tokens' cost.
        # NOT RAISED for the KB gap-fill pass (2026-09-22) that this ceiling
        # was already over-budget from before this session touched it (4873,
        # already past 4450, caught only now by actually running this check) —
        # that round added the PEP/loan/DOB-invention guardrails, the KB-vs-
        # product-owner conflict flags, and the repetition/waiting-line
        # rewrites. Raised to 5450 here to cover that PLUS this round: the
        # interrupted-intro fix (bare "okay" mid-greeting no longer skips the
        # KYC-pending reason), the "process क्या है" one-step-only rule, and
        # the WhatsApp KYC-link option (adds ~0 when WHATSAPP_KYC_LINK is
        # unset, its default — the ceiling has to cover the flag-on prompt
        # too, since that is the one that actually ships once the send
        # mechanism is live). Every addition traces to a live incident or an
        # explicit product ask, not padding — see the comments at each rule.
        # Raised again same day to 5600: the closing line (product ask —
        # "धन्यवाद, thank you for choosing Park+", bilingual on purpose) and
        # the proposal-page-vs-KYC-page split (5a-i / row 9a — a caller who
        # says "proposal page भर दिया" was getting the SAME answer as one who
        # had actually finished KYC, "मैं check करके confirm करूँगी", which
        # answers a question they have not reached yet instead of sending
        # them to the KYC page. Confirmed against the product owner's own
        # described flow before writing it.
        # Raised again same day to 6200: the delivery-line auto-attach on
        # "whole thing done" (no longer gated behind a separate timing
        # question — product instruction), the opening-line rewrite (product
        # dictated exact wording, longer than the trimmed version), and the
        # repeated-refusal fix — a live call showed the bot just saying
        # "धन्यवाद" on a second/third refusal with no callback ask and no
        # reminder that KYC is mandatory, which is how a caller ends a call
        # thinking this was optional.
        # Raised again same day to 6350: tone-softening pass, product
        # instruction — the bot must never sound harsh or warning-toned, even
        # stating a real consequence. Reworded the second-refusal line and the
        # Aadhaar-digit warning to lead with what completing something gets
        # them, not what refusing costs them; added an explicit "never harsh"
        # rule to both tone sections.
        tokens = _est_tokens(p)
        # 7400, the fourth raise today and the last one I would make without a
        # trim pass. Today's live call produced six more product fixes: the
        # refund/cancellation answer (row 15 + guard), the friendly-chat reply
        # that was a flat "मैं बातें नहीं कर सकती", and the re-greeting. Three
        # duplications were deleted to pay for them (the scope list, "One job
        # per turn", "never reuse your last spoken line"), so the prompt is at
        # capacity: the next addition should replace something, not append.
        #
        # 7300 on 2026-09-22 (from 7200), for four behaviour fixes the product
        # owner asked for after a live call: name at most twice, answer a real
        # question without bolting the app line on, "बाद में कर लो" means later,
        # and the off-topic redirect no longer applies to real questions. Two
        # rules the contract already stated were deleted first, so this is the
        # residual cost of the fixes, not drift.
        #
        # 7200, and every number in the history above is understated by ~18%.
        # Those were all len/3.2; the live Park+ tokenizer says the outbound
        # prompt is 7055 tokens, not the ~5968 that rule of thumb reported. The
        # ceiling moved to match reality, NOT because the prompt grew — see
        # _est_tokens. Real headroom is now ~150 tokens, so this tripwire
        # finally means what it says.
        assert tokens < 7400, f"{mode}: {tokens:.0f} tokens is too expensive per turn"
        # Every hard rule must actually be stated, not just implied.
        for rule in ("OTP", "WhatsApp", "complete", "refund"):
            assert rule in p, f"{mode}: missing the {rule} rule"
        # The app handoff IS the product.
        assert "app" in p.lower()
        # The real screen labels must reach the prompt verbatim — the bot says
        # them out loud and the customer is looking at them.
        for label in ("Confirm policy details", "Car Owner's name (as per RC)",
                      "Nominee Details", "Aadhar Front Image", "Engine Number",
                      "Chassis Number", "Previous Own Damage Insurer name",
                      "Complete KYC", "Next"):
            assert label in p, f"{mode}: screen label missing: {label!r}"
        # The four field states must stay DISTINCT in the rendered prompt. When a
        # renderer edit silently stopped matching the new state names, every
        # field came out as "already filled" — the bot would have told customers
        # the form needed nothing while three fields sat blank. Caught by reading
        # the output, not by the prompt building without error.
        for state in ("TYPE:", "CONFIRM:", "UPLOAD:", "already filled, just check:"):
            assert state in p, f"{mode}: field state missing from the prompt: {state}"
        assert p.count("TYPE:") >= 6, "the fields the customer types went missing"
        # The two things that actually cost calls.
        assert "hereby declare" in p, "the declaration checkbox blocks submit"
        # The sanctioned answer to the commonest objection. Rendered from
        # context.json, so a bad edit there silently muted the bot on the one
        # question every customer asks — until this caught it.
        assert "IRDAI" in p, "the sanctioned mandate line went missing"
        for line in ctx["kyc_mandate"]["sanctioned_lines"].values():
            assert line in p, f"a sanctioned mandate line went missing: {line[:40]}"
        # Was assert "FAILS" — pinned to the shouty capitalisation, which the
        # 2026-09-22 tone pass lowercased. What must survive is the WARNING,
        # not the shouting, so match the wording instead.
        assert re.search(r"one wrong digit", p, re.I), \
            "the wrong-Aadhaar-digit warning must survive"

    # --- with a call card -----------------------------------------------------
    no_card = build_system_prompt("outbound")
    assert "{call_card}" not in no_card and "# THIS CALL" not in no_card, \
        "no card must render exactly the prompt it always did"

    kyc = call_card.build({
        "customer_name": "Rahul Suresh Singh", "insurer": "Bajaj",
        "vehicle_reg": "DL6CP8915", "kyc_status": "PENDING",
    })
    p_kyc = build_system_prompt("outbound", kyc)
    assert "Rahul Suresh Singh" in p_kyc and "DL6CP8915" in p_kyc
    # complete_kyc still gets the whole walkthrough — the screens are the job.
    assert "Complete KYC" in p_kyc and "hereby declare" in p_kyc
    assert "Aadhar Front Image" in p_kyc

    dup = call_card.build({
        "customer_name": "Rahul", "insurer": "United India", "vehicle_reg": "DL6CP8915",
        "kyc_status": "SUCCESS", "proposal_status": "PROPOSAL_PENDING",
        "error_code": "IERR_DUPLICATE_POLICY",
        "blocker": "Duplicate policy — already insured under TP 0407033126P108547203",
        "do_not_say": ["IERR_DUPLICATE_POLICY"],
    })
    p_dup = build_system_prompt("outbound", dup)
    # A call with nothing for the customer to do must not carry a form guide.
    # Shipping the walkthrough here is how the bot starts hunting for a screen
    # to send someone to on a call that needed one honest sentence.
    for screen in ("hereby declare", "Aadhar Front Image", "Complete KYC button",
                   "Engine Number", "Nominee Details"):
        assert screen not in p_dup, f"the short call must not carry {screen!r}"
    assert "Rahul" in p_dup and "already insured" in p_dup
    assert "OTP" in p_dup, "the OTP rule is required on every call"
    assert "OTP" in p_dup, "the OTP rule is required on every call"
    assert "0407033126P108547203" not in p_dup, "identifiers must never reach the model"
    assert len(p_dup) < len(p_kyc) / 2, "the short call should be much shorter"

    # A company-owned car must not have the Aadhaar fields rendered as "the
    # fields on their screen" — that set is not on their screen at all.
    company = call_card.build({"customer_name": "Neha Bhatia", "kyc_status": "PENDING",
                               "ownership_type": "Company"})
    p_co = build_system_prompt("outbound", company)
    screens = p_co.split("# THE SCREENS", 1)[1]
    for aadhaar_field in ("Aadhar Number", "Aadhar Front Image", "Aadhar Back Image"):
        assert aadhaar_field not in screens, f"{aadhaar_field} rendered for a company car"
    assert "GST certificate" in p_co and "PAN photo" in p_co
    assert "Neha जी" in p_co, "a name replaces सर, and जी carries no gender"

    individual = call_card.build({"customer_name": "Rahul", "kyc_status": "PENDING",
                                  "ownership_type": "Individual"})
    p_ind = build_system_prompt("outbound", individual)
    ind_screens = p_ind.split("# THE SCREENS", 1)[1]
    assert "Aadhar Front Image" in ind_screens
    assert "COMPANY-OWNED" not in ind_screens

    # Unknown ownership still renders the common case AND lets the bot ask.
    unknown = call_card.build({"customer_name": "Rahul", "kyc_status": "PENDING"})
    assert "ownership_type" not in unknown
    assert "Aadhar Front Image" in build_system_prompt("outbound", unknown)

    issued = call_card.build({"customer_name": "Asha", "policy_number": "P9001",
                              "kyc_status": "SUCCESS"})
    assert "ISSUED" in build_system_prompt("outbound", issued)

    # --- 2026-09-20: facts added after the 14:55 call --------------------------
    for fact, why in (
        ("app बंद करके दोबारा खोलिए", "the button-not-found ladder"),
        ("WhatsApp पर KYC का link", "the ladder's last step"),
        ("notification", "the policy-delivery answer"),
        ("special characters are rejected", "the address field rule"),
        ("NEVER tell a customer to cut", "the 14:55 call told someone to cut their Aadhaar in half"),
        ("privacy की वजह से", "refusing offered documents"),
    ):
        assert fact in no_card, f"{why} went missing: {fact!r}"

    # United does its KYC on HyperVerge, not on this page at all.
    utd = call_card.build({"customer_name": "Asha", "kyc_status": "PENDING",
                           "insurer": "United India"})
    p_utd = build_system_prompt("outbound", utd)
    assert "HyperVerge" in p_utd and "selfie" in p_utd
    utd_screens = p_utd.split("# THE SCREENS", 1)[1]
    for upload_field in ("Aadhar Front Image", "Aadhar Back Image"):
        assert upload_field not in utd_screens, \
            f"{upload_field} rendered for United, which has no Browse button"
    # ...and nobody else gets sent to HyperVerge.
    other = call_card.build({"customer_name": "Asha", "kyc_status": "PENDING",
                             "insurer": "Bajaj"})
    assert "HyperVerge" not in build_system_prompt("outbound", other)
    assert "HyperVerge" not in no_card, "with no card the insurer is unknown"

    # The opening's LENGTH is the product decision. At ~12 characters of Hindi
    # per second, 150 characters is about twelve seconds — already long for the
    # first thing a stranger hears. The version before the 14:55-call rewrite
    # was 169 and the caller tried to answer four seconds in. Read straight
    # from _OUTBOUND_LINE (what opening_line() actually returns) instead of
    # regex-scraping OPENINGS' instructional prose — that regex broke the
    # moment the line stopped ending in "App खोल लीजिए?".
    spoken = _OUTBOUND_LINE.format(honorific="सर")
    assert len(spoken) <= 150, f"the opening grew back to {len(spoken)} chars " \
                               f"(~{len(spoken) / 12:.0f}s of speech)"
    for clause in ("Park+", "Shreya", "KYC", "दो मिनट"):
        assert clause in spoken, f"the opening lost a load-bearing clause: {clause}"

    assert build_system_prompt("outbound") != build_system_prompt("inbound")
    try:
        build_system_prompt("sideways")
        raise AssertionError("unknown mode must raise")
    except ValueError:
        pass

    # WHATSAPP_KYC_LINK=1 path — reads a module-level constant set at import,
    # so flip it directly rather than re-importing. Nothing exercised this
    # before it shipped; a token-budget or content regression here would have
    # gone live invisibly the same way the 4873-vs-4450 overrun did.
    global WHATSAPP_KYC_LINK_ENABLED
    was_enabled = WHATSAPP_KYC_LINK_ENABLED
    WHATSAPP_KYC_LINK_ENABLED = True
    try:
        p_wa = build_system_prompt("outbound")
        assert "ONE exception" in p_wa, "flag-on prompt lost the WhatsApp exception rule"
        assert "Never offer to SEND anything" not in p_wa, \
            "flag-on prompt should not carry the blanket no-send rule too"
        assert "15. app नहीं चलता" in p_wa, "flag-on prompt lost the MATCH row"
        wa_tokens = _est_tokens(p_wa)
        # 7400: the flag-on path carries the WhatsApp rule and its MATCH row on
        # top of everything the flag-off path has, so it sits ~150 above it.
        assert wa_tokens < 7600, f"WHATSAPP_KYC_LINK=1: {wa_tokens:.0f} tokens over budget"
    finally:
        WHATSAPP_KYC_LINK_ENABLED = was_enabled

    # PREFIX CACHING. The call card is the only per-call content here, so where
    # it sits decides how much of the prompt a prefix cache can reuse between
    # two different customers. At 14% depth it was 4% (~300 tokens); at the end
    # it is 96% (~7000). That is the difference between paying for 7000 fresh
    # input tokens on every turn of every call and paying for ~30.
    #
    # Anything per-call added ABOVE the card silently undoes this, and nothing
    # else would fail — hence the assert.
    a = build_system_prompt("outbound", {"goal": "complete_kyc",
                                         "customer_name": "Anush Gupta",
                                         "vehicle_registration": "DL 6CP 8915",
                                         "insurer": "ICICI Lombard"})
    b = build_system_prompt("outbound", {"goal": "complete_kyc",
                                         "customer_name": "Ramesh Kumar",
                                         "vehicle_registration": "MH 12 AB 1234",
                                         "insurer": "HDFC Ergo"})
    shared = 0
    for x, y in zip(a, b):
        if x != y:
            break
        shared += 1
    pct = 100 * shared // len(a)
    assert pct >= 90, (
        f"only {pct}% of the prompt is shared between two calls — per-call "
        "content moved above the call card and the prefix cache is now dead"
    )

    sizes = {m: int(_est_tokens(build_system_prompt(m))) for m in OPENINGS}
    print("insurance prompt ok — " + ", ".join(f"{m} ~{t} tokens" for m, t in sizes.items()))


if __name__ == "__main__":
    _demo()
