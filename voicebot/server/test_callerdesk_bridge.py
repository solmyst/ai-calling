"""AudioSocket framing + proposal-in-UUID. python test_callerdesk_bridge.py"""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import os  # noqa: E402

from callerdesk_bridge import AUDIO, UUID, dial, frame, phone_from_uuid, proposal_from_uuid, read_frame  # noqa: E402

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


async def outbound():
    """dial() against a fake Asterisk manager: the Originate it sends."""
    got = []

    async def fake_ami(r, w):
        got.append((await r.read(4096)).decode())
        w.write(b"Response: Success\r\nMessage: Originate successfully queued\r\n\r\n")
        await w.drain()
        w.close()

    server = await asyncio.start_server(fake_ami, "127.0.0.1", 0)
    os.environ.update(AMI_PORT=str(server.sockets[0].getsockname()[1]),
                      AMI_USER="aibot", AMI_SECRET="x", CALLERDESK_DIAL_PREFIX="0")
    async with server:
        reply = await dial("+91 98765 43210", 859623)
    assert "successfully queued" in reply
    sent = got[0]
    assert "Channel: PJSIP/09876543210@callerdesk" in sent, sent
    assert "Variable: PROPOSAL_ID=859623,CUSTOMER_PHONE=919876543210" in sent, sent
    assert "Context: ai-bot" in sent and "Username: aibot" in sent

asyncio.run(outbound())
print("callerdesk bridge ok")
