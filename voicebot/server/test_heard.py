"""What the caller heard before barging in. python test_heard.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bot import SPEECH_CHARS_PER_SEC, split_heard  # noqa: E402

reply = ("Sir, pehle Park+ app kholkar Insurance icon par click kijiye. "
         "Phir 'Complete KYC' ka button dikhega, us par click kar dijiye.")

# Cut in almost at once: nothing heard, the whole reply is unheard.
assert split_heard(reply, 0.0) == ("", reply)
# Played longer than the reply: all of it heard.
assert split_heard(reply, 60) == (reply, "")
# Mid-reply: cut on a word boundary, and the two halves rebuild the reply.
heard, unheard = split_heard(reply, 3.0)
assert heard and unheard and not heard.endswith(" ")
assert len(heard) <= 3.0 * SPEECH_CHARS_PER_SEC
assert f"{heard} {unheard}" == reply
assert "Complete KYC" in unheard
print("ok")
