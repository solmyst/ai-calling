"""A fake phone call against a running bot.

Two ways in, both end to end (proposal id in the handshake -> card, STT, LLM,
TTS, audio back):

    # as Exotel's Voicebot applet, straight to the bot
    python -m evals.phone_sim ws://127.0.0.1:7860/ws --proposal 859623
    # as CallerDesk's Asterisk, through callerdesk_bridge.py
    python -m evals.phone_sim tcp://127.0.0.1:9092 --proposal 859623

Caller audio: the cached lines from evals/stt_latency.py. Prints, per caller
line, how long after the caller stopped the first bot audio came back — the
number a caller actually waits (minus the phone network).
"""

import argparse
import asyncio
import base64
import json
import time
import uuid

import websockets

from callerdesk_bridge import AUDIO, UUID, frame, read_frame
from evals.stt_latency import LINES, RATE, speech, speech_end

CHUNK = RATE * 2 // 50  # 20 ms


class Exotel:
    async def open(self, url, proposal):
        self.ws = await websockets.connect(url, max_size=None)
        self.sid = f"sim{int(time.time())}"
        await self.ws.send(json.dumps({"event": "connected"}))
        await self.ws.send(json.dumps({"event": "start", "stream_sid": self.sid, "start": {
            "stream_sid": self.sid, "call_sid": self.sid, "account_sid": "sim", "from": "sim", "to": "sim",
            "custom_parameters": {"proposal_id": str(proposal)} if proposal else {},
            "media_format": {"encoding": "base64", "sample_rate": str(RATE), "bit_rate": "128kbps"}}}))

    async def send(self, pcm):
        await self.ws.send(json.dumps({"event": "media", "stream_sid": self.sid, "media": {
            "payload": base64.b64encode(pcm).decode()}}))

    async def audio(self):
        async for msg in self.ws:
            m = json.loads(msg)
            if m.get("event") == "media":
                yield base64.b64decode(m["media"]["payload"])

    async def close(self):
        await self.ws.send(json.dumps({"event": "stop", "stream_sid": self.sid}))
        await self.ws.close()


class AudioSocket:
    """What Asterisk's AudioSocket() does: UUID frame, then 20 ms audio frames."""

    async def open(self, url, proposal):
        host, port = url.removeprefix("tcp://").split(":")
        self.reader, self.writer = await asyncio.open_connection(host, int(port))
        call_id = uuid.UUID(f"00000000-0000-4000-8000-{proposal or 0:012d}")
        self.writer.write(frame(UUID, call_id.bytes))

    async def send(self, pcm):
        self.writer.write(frame(AUDIO, pcm))
        await self.writer.drain()

    async def audio(self):
        while True:
            kind, payload = await read_frame(self.reader)
            if kind == AUDIO:
                yield payload
            elif kind == 0x00:
                return

    async def close(self):
        self.writer.write(frame(0x00))
        self.writer.close()


async def call(url: str, proposal: int | None):
    line = AudioSocket() if url.startswith("tcp://") else Exotel()
    await line.open(url, proposal)
    heard = {"last": 0.0, "bytes": 0}

    async def listen():
        async for chunk in line.audio():
            heard["last"] = time.monotonic()
            heard["bytes"] += len(chunk)

    async def send_audio(pcm: bytes):
        t0 = time.monotonic()
        for n, i in enumerate(range(0, len(pcm), CHUNK)):
            await line.send(pcm[i:i + CHUNK])
            await asyncio.sleep(max(0, t0 + (n + 1) * 0.02 - time.monotonic()))

    async def wait_quiet(quiet: float, limit: float):
        """Until the bot has been silent `quiet` seconds (it finished its line)."""
        end = time.monotonic() + limit
        while time.monotonic() < end:
            if heard["bytes"] and time.monotonic() - heard["last"] > quiet:
                return
            await asyncio.sleep(0.05)

    listener = asyncio.create_task(listen())
    silence = b"\0" * CHUNK
    # A real phone line sends audio constantly, so keep it alive while the bot talks.
    pump = asyncio.create_task(send_audio(silence * 1500))
    await wait_quiet(1.5, 30)
    pump.cancel()
    print(f"greeting: {heard['bytes'] / (RATE * 2):.1f}s of audio")
    for text in LINES[:3]:
        pcm = speech(text)
        before = heard["bytes"]
        await send_audio(pcm)
        stopped = time.monotonic() - (len(pcm) / (RATE * 2) - speech_end(pcm))
        pump = asyncio.create_task(send_audio(silence * 1500))
        limit = time.monotonic() + 15
        while heard["bytes"] == before and time.monotonic() < limit:
            await asyncio.sleep(0.01)
        first = time.monotonic() - stopped if heard["bytes"] > before else float("nan")
        await wait_quiet(1.5, 30)
        pump.cancel()
        print(f"{first:5.2f}s to first bot audio | caller: {text}")
    await line.close()
    listener.cancel()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--proposal", type=int)
    args = ap.parse_args()
    asyncio.run(call(args.url, args.proposal))
