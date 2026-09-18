"""Keep identity numbers out of the logs.

On a KYC call the customer reads their PAN and Aadhaar out loud, so the
transcript contains them whatever the model does. call.log is an unrestricted
file on whatever machine the bot runs on, which the insurance pack forbids
directly:

    "Never store raw Aadhaar/PAN/full address payloads in wiki notes, training
     dumps, or unrestricted logs."
    — domains/insurance/.../kyc-proposal-field-graph.json, safety_rules

This is the layer that enforces it. It is deterministic and it runs on the
transcript on its way to the log, not on the model's output — a prompt cannot
stop a customer from saying their Aadhaar number.

What is kept: enough to prove capture and to debug. PAN keeps its last
character-group shape, Aadhaar and phone keep their last four. That matches the
pack's "collected=true / last4 only" allowance for the runtime side-channel.

This runs for every domain, not just insurance. A Car Spa caller gives a
callback number, and a phone number in a log file is still personal data.
"""

import re

# PAN: five letters, four digits, one letter (ABCDE1234F). Speech-to-text often
# breaks it up — "ABCDE 1234 F" — so separators are tolerated between the parts.
_PAN_RE = re.compile(r"\b([A-Z]{5})[\s-]?(\d{4})[\s-]?([A-Z])\b", re.IGNORECASE)

# Aadhaar: twelve digits, usually spoken in three groups of four.
_AADHAAR_RE = re.compile(r"\b(\d{4})[\s-]?(\d{4})[\s-]?(\d{4})\b")

# Indian mobile: ten digits starting 6-9, optionally +91 / 0 prefixed. Checked
# AFTER Aadhaar so the first ten digits of an Aadhaar number are not mistaken
# for a phone number.
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?|0)?([6-9]\d{4})[\s-]?(\d{5})(?!\d)")

# GSTIN carries a PAN inside it, so it is masked as a unit rather than letting
# the PAN rule chew the middle out of it.
_GSTIN_RE = re.compile(r"\b(\d{2})([A-Z]{5}\d{4}[A-Z])([A-Z\d]{3})\b", re.IGNORECASE)


def redact(text: str) -> str:
    """Mask identity numbers in a transcript, keeping the last few characters.

    Order matters: GSTIN before PAN (it contains one), Aadhaar before phone (its
    first ten digits look like one).
    """
    if not text:
        return text
    text = _GSTIN_RE.sub(lambda m: f"GSTIN[{m.group(1)}…{m.group(3)}]", text)
    text = _AADHAAR_RE.sub(lambda m: f"AADHAAR[…{m.group(3)}]", text)
    text = _PAN_RE.sub(lambda m: f"PAN[{m.group(1)[0]}…{m.group(3)}]", text)
    text = _PHONE_RE.sub(lambda m: f"PHONE[…{m.group(2)[-4:]}]", text)
    return text


def _demo():
    # Spoken the way a customer actually reads them out, with and without gaps.
    cases = [
        ("मेरा PAN ABCDE1234F है", "ABCDE1234F"),
        ("PAN is abcde 1234 f", "abcde 1234 f"),
        ("Aadhaar 1234 5678 9012 hai", "1234 5678 9012"),
        ("aadhaar number 123456789012", "123456789012"),
        ("mera number 9876543210 hai", "9876543210"),
        ("call me on +91 98765 43210", "98765 43210"),
        ("GSTIN 07ABCDE1234F1Z5 hai", "07ABCDE1234F1Z5"),
    ]
    for text, secret in cases:
        out = redact(text)
        assert secret not in out, f"leaked {secret!r}: {out!r}"
        assert out != text, f"nothing masked in {text!r}"
    # Last four are kept, so a human can still match a log line to a case.
    assert "…9012" in redact("Aadhaar 1234 5678 9012"), redact("Aadhaar 1234 5678 9012")
    assert "…3210" in redact("number 9876543210"), redact("number 9876543210")

    # Things that must NOT be mangled: prices, durations, pincodes, slot times,
    # and the car spa numbers that share the log file.
    for safe in (
        "Creta के लिए 499 रुपये",
        "करीब 110 मिनट लगते हैं",
        "Sector 56 में",
        "कल सुबह आठ बजे",
        "pincode 122001 hai",
        "4+1 pack",
    ):
        assert redact(safe) == safe, f"mangled a safe line: {redact(safe)!r}"

    # An Aadhaar must not be half-eaten by the phone rule.
    out = redact("1234 5678 9012")
    assert "PHONE" not in out, out
    print("redaction ok — PAN, Aadhaar, phone, GSTIN masked; prices and pincodes intact")


if __name__ == "__main__":
    _demo()
