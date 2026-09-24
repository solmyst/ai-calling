"""AudioSocket framing + proposal-in-UUID. python test_callerdesk_bridge.py"""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from callerdesk_bridge import AUDIO, UUID, frame, phone_from_uuid, proposal_from_uuid, read_frame  # noqa: E402

assert proposal_from_uuid(str(uuid.UUID("00000000-0000-4000-8000-000000859623"))) == 859623
assert proposal_from_uuid("00000000-0000-4000-8000-000000000000") is None
assert proposal_from_uuid(str(uuid.uuid4())) is None  # a plain call: no card, never a guess
both = str(uuid.UUID("91998292-0838-4000-8000-000000859623"))
assert proposal_from_uuid(both) == 859623 and phone_from_uuid(both) == "919982920838"
assert phone_from_uuid("00000000-0000-4000-8000-000000859623") is None


async def roundtrip():
    r = asyncio.StreamReader()
    r.feed_data(frame(UUID, b"\x01" * 16) + frame(AUDIO, b"\x00\x01" * 160))
    r.feed_eof()
    assert await read_frame(r) == (UUID, b"\x01" * 16)
    assert await read_frame(r) == (AUDIO, b"\x00\x01" * 160)

asyncio.run(roundtrip())
print("callerdesk bridge ok")
