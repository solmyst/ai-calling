"""Exotel handshake -> runner body. python test_phone_body.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bot import _phone_body, split_heard  # noqa: E402,F401

assert _phone_body({"custom_parameters": {"proposal_id": "859623"}}) == {"proposal_id": 859623}
assert _phone_body({"custom_parameters": "proposal_id=859623&x=1"}) == {"proposal_id": 859623}
assert _phone_body({"custom_parameters": "?proposal=42"}) == {"proposal_id": 42}
# No id, or junk: no card — never the VM's --proposal test case.
assert _phone_body({"custom_parameters": ""}) == {}
assert _phone_body({"custom_parameters": {"proposal_id": "abc"}}) == {}
assert _phone_body({}) == {}
print("phone body ok")
