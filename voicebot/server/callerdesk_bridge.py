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

    python callerdesk_bridge.py            # BRIDGE_PORT=9092 BOT_WS_URL=ws://127.0.0.1:7860/ws
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


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, bot_url: str):
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

        async def caller_to_bot():
            while True:
                kind, payload = await read_frame(reader)
                if kind == AUDIO:
                    await ws.send(json.dumps({"event": "media", "stream_sid": sid,
                                              "media": {"payload": base64.b64encode(payload).decode()}}))
                elif kind == DTMF:
                    await ws.send(json.dumps({"event": "dtmf", "stream_sid": sid,
                                              "dtmf": {"digit": payload.decode(errors="ignore")}}))
                elif kind in (HANGUP, ERROR):
                    return

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


async def main():
    port = int(os.getenv("BRIDGE_PORT") or 9092)
    bot_url = os.getenv("BOT_WS_URL") or "ws://127.0.0.1:7860/ws"
    server = await asyncio.start_server(
        lambda r, w: handle(r, w, bot_url), os.getenv("BRIDGE_HOST") or "127.0.0.1", port)
    logger.info(f"AudioSocket bridge on :{port} -> {bot_url}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
