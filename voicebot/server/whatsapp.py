"""Send the customer their KYC link on WhatsApp, as the call starts.

The link is the call's main path now: "Sir, aapke WhatsApp par KYC ka link aaya
hoga — us par click kijiye, page khul jayega." It opens the same pages as the
app. The bot may only SAY that if the link really went out, so this returns
True only when Meta accepted the message; anything else (not configured, no
phone, API error) returns False and the call runs the app steps as before.

The link is this customer's own KYC page,
parkplus.io/app/car-insurance/verification?proposal_id=<their proposal>, made
into a Park+ deeplink (prk.bz, opens the app when installed, the web page when
not) for the user id on their proposal. No deeplink credentials, or the API
failing, sends the plain page URL instead — it works either way.

The template is kyc_completion_insurance (UTILITY, en_US, approved 2026-09-24):
    body   "Hi {{1}}, here is your link to complete the KYC ...: {{2}} ..."
    button "Complete KYC" -> https://l.prk.bz/{{1}}
so it needs the name, the link, and the deeplink's code for the button — which
means the deeplink must work; a plain URL cannot fill the button, so without one
nothing is sent and the call runs the app steps.

Config (.env): WHATSAPP_TOKEN, WHATSAPP_PHONE_ID (the sender), WHATSAPP_TEMPLATE,
WHATSAPP_TEMPLATE_LANG, DEEPLINK_CLIENT_ID, DEEPLINK_CLIENT_SECRET, DEEPLINK_CAMPAIGN.
"""

import json
import os
import re
import urllib.error
import urllib.request

from loguru import logger

GRAPH = "https://graph.facebook.com/v25.0"
SHORT_LINK = "https://l.prk.bz/"
KYC_PAGE = "https://parkplus.io/app/car-insurance/verification?proposal_id={proposal_id}"


def kyc_link(proposal_id, user_id=None) -> str:
    """This customer's KYC page as a Park+ deeplink, or the plain page URL."""
    page = KYC_PAGE.format(proposal_id=int(proposal_id))
    cid, secret = os.getenv("DEEPLINK_CLIENT_ID"), os.getenv("DEEPLINK_CLIENT_SECRET")
    if not (cid and secret and user_id):
        return page
    body = {"user_id": str(user_id), "distribution_channel": "app", "destination_url": page,
            "feature_name": "insurance_home",
            "campaign_name": os.getenv("DEEPLINK_CAMPAIGN") or "INSURANCE_D0_D10",
            "screen_id": 10, "custom_data": {}, "fallback_url": page,
            "desktop_url": "https://parkplus.io/car-insurance"}
    req = urllib.request.Request(
        "https://prk.bz/api/deeplink", json.dumps(body).encode(), method="POST",
        headers={"client-id": cid, "client-secret": secret, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=float(os.getenv("DEEPLINK_TIMEOUT_SECS") or 3)) as r:
            url = (json.loads(r.read()).get("data") or {}).get("url")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        logger.warning(f"KYC LINK | deeplink failed for proposal {proposal_id} ({e}); plain URL")
        return page
    return url if isinstance(url, str) and url.startswith("https://") else page


def normalise_phone(raw) -> str | None:
    """Digits with the 91 country code, or None if it is not an Indian mobile."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 10:
        digits = "91" + digits
    return digits if len(digits) == 12 and digits.startswith("91") else None


def send_kyc_link(phone, proposal_id, user_id=None, name=None) -> bool:
    """True only if WhatsApp accepted the KYC-link message for this customer."""
    token, sender = os.getenv("WHATSAPP_TOKEN"), os.getenv("WHATSAPP_PHONE_ID")
    template = os.getenv("WHATSAPP_TEMPLATE") or "kyc_completion_insurance"
    to = normalise_phone(phone)
    if not (token and sender and to and proposal_id):
        missing = [n for n, v in (("WHATSAPP_TOKEN", token), ("WHATSAPP_PHONE_ID", sender),
                                  ("phone", to), ("proposal_id", proposal_id)) if not v]
        logger.info(f"KYC LINK | not sent — missing {', '.join(missing)}; app steps this call")
        return False
    # Testing safety: with WHATSAPP_ONLY_TO set, nothing goes anywhere else. On
    # 2026-09-24 a simulated call on a real customer's proposal (741688) looked
    # up their phone and tried to send; only the sandbox allowed-list stopped
    # it. Unset it only when real customers should get the link.
    only = {normalise_phone(n) for n in (os.getenv("WHATSAPP_ONLY_TO") or "").split(",") if n.strip()}
    if only and to not in only:
        logger.warning(f"KYC LINK | not sent — ...{to[-4:]} is not in WHATSAPP_ONLY_TO (test mode)")
        return False
    link = kyc_link(proposal_id, user_id)
    if not link.startswith(SHORT_LINK):
        logger.warning(f"KYC LINK | no deeplink for proposal {proposal_id} — the template's "
                       "button needs one; app steps this call")
        return False
    # The proposal's owner name; none on the case -> "Hi sir/madam," (product owner).
    first = str(name or "").split()[0].title() if str(name or "").strip() else "sir/madam"
    body = {"messaging_product": "whatsapp", "to": to, "type": "template", "template": {
        "name": template, "language": {"code": os.getenv("WHATSAPP_TEMPLATE_LANG") or "en_US"},
        "components": [
            {"type": "body", "parameters": [{"type": "text", "text": first},
                                            {"type": "text", "text": link}]},
            {"type": "button", "sub_type": "url", "index": "0",
             "parameters": [{"type": "text", "text": link[len(SHORT_LINK):]}]},
        ]}}
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
    assert send_kyc_link("9982920838", 741688) is False, "unconfigured must never claim sent"
    os.environ.update(WHATSAPP_TOKEN="t", WHATSAPP_PHONE_ID="p", WHATSAPP_ONLY_TO="9982920838")
    assert send_kyc_link("6397644000", 741688) is False, "test mode sent outside WHATSAPP_ONLY_TO"
    os.environ.pop("WHATSAPP_TOKEN"); os.environ.pop("WHATSAPP_ONLY_TO")
    for k in ("DEEPLINK_CLIENT_ID", "DEEPLINK_CLIENT_SECRET"):
        os.environ.pop(k, None)
    assert kyc_link(741688, 25393657) == \
        "https://parkplus.io/app/car-insurance/verification?proposal_id=741688", kyc_link(741688)
    print("whatsapp ok")
