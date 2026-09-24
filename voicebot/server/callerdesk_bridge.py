"""CallerDesk (SIP / Asterisk) calls into the bot, with no change to the bot.

CallerDesk's integration is SIP: the AI registers on their Asterisk like a
MicroSIP softphone, over a site-to-site tunnel. Pipecat has no SIP transport, so
a local Asterisk does the SIP (deploy/callerdesk/) and hands each call's audio to
this bridge over AudioSocket — Asterisk's plain TCP audio protocol. The bridge
speaks the Exotel media protocol to the bot's existing /ws endpoint, so the
phone path the bot already runs (proposal id from the handshake, STT, LLM, TTS,
barge-in) is exactly the one CallerDesk calls take.

    Asterisk --AudioSocket(tcp :9092)--> callerdesk_bridge --Exotel ws--> bot.py /ws

The proposal id and the customer's phone ride in the AudioSocket UUID — the
dialplan builds it as <phone 12 digits as 8-4>-4000-8000-<proposal id, 12 digits>
(zeros when unknown) — so no side channel is needed. The phone is where the
bot sends the KYC link on WhatsApp.

    python callerdesk_bridge.py                          # the bridge (inbound + outbound audio)
    python callerdesk_bridge.py dial 9876543210 741688   # outbound: ring a customer

`dial` asks our Asterisk (AMI, 127.0.0.1:5038, deploy/callerdesk/manager.conf)
to call the customer through CallerDesk and hand the answered call to the bot.
"""

import asyncio
import base64
import json
import os
import uuid

import websockets
from loguru import logger

# AudioSocket frame kinds (https://docs.asterisk.org/Configuration/Channel-Drivers/AudioSocket/)
HANGUP, UUID, DTMF, AUDIO, ERROR = 0x00, 0x01, 0x03, 0x10, 0xFF
RATE = 8000
FRAME = RATE * 2 // 50  # 20 ms of 8 kHz s16le: what Asterisk sends and expects


def proposal_from_uuid(call_id: str) -> int | None:
    """The proposal id the dialplan packed into the call UUID, if any."""
    parts = call_id.split("-")
    if len(parts) != 5 or parts[2:4] != ["4000", "8000"] or not parts[4].isdigit():
        return None
    return int(parts[4]) or None


def phone_from_uuid(call_id: str) -> str | None:
    """The customer's 12-digit phone (91XXXXXXXXXX) packed into the call UUID, if any."""
    parts = call_id.split("-")
    digits = "".join(parts[:2]) if len(parts) == 5 and parts[2:4] == ["4000", "8000"] else ""
    return digits if digits.isdigit() and digits.startswith("91") else None


async def read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    head = await reader.readexactly(3)
    return head[0], await reader.readexactly(int.from_bytes(head[1:], "big"))


def frame(kind: int, payload: bytes = b"") -> bytes:
    return bytes([kind]) + len(payload).to_bytes(2, "big") + payload


# Live calls per bot process. One bot process is one Python core and carries
# ~4-5 calls (measured on the 4-core VM 2026-09-24: 4 calls = 40-93% of a core),
# so scale is many bot processes behind this one bridge: BOT_WS_URLS lists them
# and each new call goes to the least busy. MAX_CALLS_PER_BOT caps each one.
ACTIVE: dict[str, int] = {}


def pick_bot(urls: list[str], cap: int) -> str | None:
    """The least busy bot process with room for one more call, or None."""
    free = [u for u in urls if ACTIVE.get(u, 0) < cap]
    return min(free, key=lambda u: ACTIVE.get(u, 0)) if free else None


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, bot_urls: list[str]):
    bot_url = pick_bot(bot_urls, int(os.getenv("MAX_CALLS_PER_BOT") or 5))
    if bot_url is None:
        # Every bot is full: hang up at once so Asterisk / the dialer can retry
        # later, rather than put a customer on a bot that will stutter.
        logger.warning(f"ALL BOTS FULL ({sum(ACTIVE.values())} calls) — rejecting call")
        writer.write(frame(HANGUP))
        writer.close()
        return
    ACTIVE[bot_url] = ACTIVE.get(bot_url, 0) + 1
    try:
        await _bridge(reader, writer, bot_url)
    finally:
        ACTIVE[bot_url] -= 1


async def _bridge(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, bot_url: str):
    kind, payload = await read_frame(reader)
    if kind != UUID:
        logger.error(f"AudioSocket: first frame was {kind:#x}, not a UUID — dropping")
        writer.close()
        return
    call_id = str(uuid.UUID(bytes=payload))
    proposal, phone = proposal_from_uuid(call_id), phone_from_uuid(call_id)
    logger.info(f"CALL proposal={proposal or 'none'} phone={'...' + phone[-4:] if phone else 'none'}")
    sid = call_id.replace("-", "")
    out: asyncio.Queue[bytes] = asyncio.Queue()

    async with websockets.connect(bot_url, max_size=None) as ws:
        await ws.send(json.dumps({"event": "connected"}))
        await ws.send(json.dumps({"event": "start", "stream_sid": sid, "start": {
            "stream_sid": sid, "call_sid": sid, "account_sid": "callerdesk", "from": "", "to": "",
            "custom_parameters": {k: v for k, v in (("proposal_id", str(proposal or "")),
                                                    ("phone", phone or "")) if v},
            "media_format": {"encoding": "base64", "sample_rate": str(RATE), "bit_rate": "128kbps"}}}))

        async def send_audio(pcm: bytes):
            await ws.send(json.dumps({"event": "media", "stream_sid": sid,
                                      "media": {"payload": base64.b64encode(pcm).decode()}}))

        async def caller_to_bot():
            # Asterisk sends AudioSocket frames only while there IS sound — a
            # silent or silence-suppressed leg sends nothing (tested on the VM,
            # 2026-09-24: 193 frames over a 36s call). The STT ends a turn by
            # hearing silence, so every gap is filled with silence here;
            # otherwise the caller's last line is never transcribed.
            frames: asyncio.Queue = asyncio.Queue()

            async def read_all():
                try:
                    while True:
                        frames.put_nowait(await read_frame(reader))
                except (asyncio.IncompleteReadError, ConnectionError):
                    frames.put_nowait((HANGUP, b""))

            reading = asyncio.create_task(read_all())
            silence = b"\0" * FRAME
            try:
                while True:
                    try:
                        kind, payload = await asyncio.wait_for(frames.get(), 0.03)
                    except asyncio.TimeoutError:
                        await send_audio(silence)
                        continue
                    if kind == AUDIO:
                        await send_audio(payload)
                    elif kind == DTMF:
                        await ws.send(json.dumps({"event": "dtmf", "stream_sid": sid,
                                                  "dtmf": {"digit": payload.decode(errors="ignore")}}))
                    elif kind in (HANGUP, ERROR):
                        return
            finally:
                reading.cancel()

        async def bot_to_queue():
            pending = b""
            async for msg in ws:
                m = json.loads(msg)
                if m.get("event") == "media":
                    pending += base64.b64decode(m["media"]["payload"])
                    while len(pending) >= FRAME:
                        out.put_nowait(pending[:FRAME])
                        pending = pending[FRAME:]
                elif m.get("event") == "clear":
                    # Barge-in: the caller must stop hearing the old reply NOW.
                    pending = b""
                    while not out.empty():
                        out.get_nowait()

        async def queue_to_caller():
            # The bot sends audio ~2x faster than real time; Asterisk plays what
            # it is given, so pace it here — which also keeps "clear" meaningful.
            loop = asyncio.get_running_loop()
            next_at = loop.time()
            while True:
                chunk = await out.get()
                next_at = max(next_at, loop.time())
                writer.write(frame(AUDIO, chunk))
                await writer.drain()
                next_at += 0.02
                await asyncio.sleep(max(0, next_at - loop.time()))

        tasks = [asyncio.create_task(t) for t in (caller_to_bot(), bot_to_queue(), queue_to_caller())]
        done, pending_tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending_tasks:
            t.cancel()
        try:
            await ws.send(json.dumps({"event": "stop", "stream_sid": sid}))
        except websockets.ConnectionClosed:
            pass
    try:
        writer.write(frame(HANGUP))  # bot ended the call: hang up the SIP leg
        await writer.drain()
    except ConnectionError:
        pass
    writer.close()
    logger.info(f"CALL {call_id} ended")


async def dial(phone: str, proposal: int) -> str:
    """Ring a customer via our Asterisk -> CallerDesk; the answered call reaches the bot.

    Returns Asterisk's reply to the Originate. Needs AMI_USER / AMI_SECRET
    (deploy/callerdesk/manager.conf). CALLERDESK_DIAL_PREFIX is whatever
    CallerDesk wants in front of the number (e.g. "0") — ask them.
    """
    digits = "".join(c for c in phone if c.isdigit())[-10:]
    full = "91" + digits
    number = (os.getenv("CALLERDESK_DIAL_PREFIX") or "") + digits
    reader, writer = await asyncio.open_connection(
        os.getenv("AMI_HOST") or "127.0.0.1", int(os.getenv("AMI_PORT") or 5038))
    writer.write((f"Action: Login\r\nUsername: {os.environ['AMI_USER']}\r\n"
                  f"Secret: {os.environ['AMI_SECRET']}\r\n\r\n"
                  f"Action: Originate\r\nChannel: PJSIP/{number}@callerdesk\r\n"
                  "Context: ai-bot\r\nExten: s\r\nPriority: 1\r\nAsync: true\r\n"
                  f"Variable: PROPOSAL_ID={int(proposal)},CUSTOMER_PHONE={full}\r\n\r\n"
                  "Action: Logoff\r\n\r\n").encode())
    await writer.drain()
    reply = (await asyncio.wait_for(reader.read(4096), 5)).decode(errors="ignore")
    writer.close()
    logger.info(f"DIAL ...{digits[-4:]} proposal={proposal}: "
                f"{'accepted' if 'Originate successfully queued' in reply else reply[-200:]!r}")
    return reply


async def main():
    port = int(os.getenv("BRIDGE_PORT") or 9092)
    bot_urls = [u.strip() for u in (os.getenv("BOT_WS_URLS") or os.getenv("BOT_WS_URL")
                                    or "ws://127.0.0.1:7860/ws").split(",") if u.strip()]
    server = await asyncio.start_server(
        lambda r, w: handle(r, w, bot_urls), os.getenv("BRIDGE_HOST") or "127.0.0.1", port)
    logger.info(f"AudioSocket bridge on :{port} -> {len(bot_urls)} bot process(es)")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["dial"]:
        asyncio.run(dial(sys.argv[2], int(sys.argv[3])))
    else:
        asyncio.run(main())
