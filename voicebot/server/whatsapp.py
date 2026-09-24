"""Send the customer their KYC link on WhatsApp, as the call starts.

The link is the call's main path now: "Sir, aapke WhatsApp par KYC ka link aaya
hoga — us par click kijiye, page khul jayega." It opens the same pages as the
app. The bot may only SAY that if the link really went out, so this returns
True only when Meta accepted the message; anything else (not configured, no
phone, API error) returns False and the call runs the app steps as before.

Config (.env): WHATSAPP_TOKEN, WHATSAPP_PHONE_ID (the sender), WHATSAPP_TEMPLATE
(an approved template whose body {{1}} is the link), WHATSAPP_TEMPLATE_LANG,
KYC_LINK_URL (with {proposal_id}).
"""

import json
import os
import re
import urllib.error
import urllib.request

from loguru import logger

GRAPH = "https://graph.facebook.com/v25.0"


def normalise_phone(raw) -> str | None:
    """Digits with the 91 country code, or None if it is not an Indian mobile."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 10:
        digits = "91" + digits
    return digits if len(digits) == 12 and digits.startswith("91") else None


def send_kyc_link(phone, proposal_id) -> bool:
    """True only if WhatsApp accepted the KYC-link message for this customer."""
    token, sender = os.getenv("WHATSAPP_TOKEN"), os.getenv("WHATSAPP_PHONE_ID")
    template, link_url = os.getenv("WHATSAPP_TEMPLATE"), os.getenv("KYC_LINK_URL")
    to = normalise_phone(phone)
    if not (token and sender and template and link_url and to and proposal_id):
        missing = [n for n, v in (("WHATSAPP_TOKEN", token), ("WHATSAPP_PHONE_ID", sender),
                                  ("WHATSAPP_TEMPLATE", template), ("KYC_LINK_URL", link_url),
                                  ("phone", to), ("proposal_id", proposal_id)) if not v]
        logger.info(f"KYC LINK | not sent — missing {', '.join(missing)}; app steps this call")
        return False
    link = link_url.format(proposal_id=proposal_id)
    body = {"messaging_product": "whatsapp", "to": to, "type": "template", "template": {
        "name": template, "language": {"code": os.getenv("WHATSAPP_TEMPLATE_LANG") or "en"},
        "components": [{"type": "body", "parameters": [{"type": "text", "text": link}]}]}}
    req = urllib.request.Request(
        f"{GRAPH}/{sender}/messages", json.dumps(body).encode(), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=float(os.getenv("WHATSAPP_TIMEOUT_SECS") or 4)) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        logger.error(f"KYC LINK | WhatsApp refused proposal {proposal_id}: "
                     f"{e.code} {e.read()[:200].decode(errors='ignore')}")
        return False
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        logger.error(f"KYC LINK | WhatsApp unreachable for proposal {proposal_id}: {e}")
        return False
    ok = bool((data.get("messages") or [{}])[0].get("id"))
    logger.info(f"KYC LINK | {'sent' if ok else 'NOT accepted'} for proposal {proposal_id} "
                f"to ...{to[-4:]}")
    return ok


if __name__ == "__main__":
    assert normalise_phone("9982920838") == "919982920838"
    assert normalise_phone("+91 99829 20838") == "919982920838"
    assert normalise_phone("12345") is None and normalise_phone(None) is None
    os.environ.pop("WHATSAPP_TOKEN", None)
    assert send_kyc_link("9982920838", 859623) is False, "unconfigured must never claim sent"
    print("whatsapp ok")
