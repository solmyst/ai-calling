"""How long each STT takes from the caller's last word to a usable final.

Same audio for every provider: real Hindi caller lines spoken by Sarvam's TTS at
8 kHz (phone rate), streamed in real time in 20 ms chunks, then silence. The
clock starts at the end of speech in the audio, not at the end of the file.

    python -m evals.stt_latency            # all setups
    python -m evals.stt_latency aai_now sarvam_fast

Latency only: synthetic speech says nothing about accuracy on real callers.
Each run bills a few seconds of STT per line.
"""

import asyncio
import base64
import hashlib
import io
import json
import os
import statistics
import sys
import time
import urllib.request
import wave
from pathlib import Path
from urllib.parse import urlencode

import websockets
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

RATE = 8000
CHUNK = RATE * 2 // 50  # 20 ms of s16le
LINES = [
    "हाँ बोलिए क्या काम है",
    "मैंने app खोल लिया है अब कहाँ जाना है",
    "ये KYC करना ज़रूरी है क्या",
    "अभी मैं गाड़ी चला रहा हूँ बाद में कॉल करना",
    "पैन कार्ड और आधार दोनों लगेंगे क्या",
]
CACHE = Path(__file__).resolve().parents[3] / "data" / "stt_bench"


def speech(text: str) -> bytes:
    """8 kHz s16le PCM for one caller line, cached (Sarvam TTS, male voice)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{hashlib.md5(text.encode()).hexdigest()[:10]}.pcm"
    if path.exists():
        return path.read_bytes()
    body = {"text": text, "target_language_code": "hi-IN", "speaker": "aditya",
            "speech_sample_rate": RATE, "model": "bulbul:v3"}
    req = urllib.request.Request(
        "https://api.sarvam.ai/text-to-speech", json.dumps(body).encode(),
        {"api-subscription-key": os.environ["SARVAM_API_KEY"], "Content-Type": "application/json"})
    wav = base64.b64decode(json.load(urllib.request.urlopen(req, timeout=30))["audios"][0])
    with wave.open(io.BytesIO(wav)) as w:
        pcm = w.readframes(w.getnframes())
    path.write_bytes(pcm)
    return pcm


def speech_end(pcm: bytes) -> float:
    """Seconds into the audio where the last loud 20 ms frame ends."""
    import array
    samples = array.array("h", pcm)
    frame = RATE // 50
    last = 0
    for i in range(0, len(samples), frame):
        if max((abs(s) for s in samples[i:i + frame]), default=0) > 800:
            last = i + frame
    return last / RATE


async def stream(ws, pcm: bytes, send) -> None:
    """Send speech + 3 s silence in real time."""
    t0 = time.monotonic()
    audio = pcm + b"\0" * (RATE * 2 * 3)
    for n, i in enumerate(range(0, len(audio), CHUNK)):
        await send(ws, audio[i:i + CHUNK])
        await asyncio.sleep(max(0, t0 + (n + 1) * 0.02 - time.monotonic()))


async def assemblyai(pcm: bytes, **opts) -> tuple[float, str]:
    params = {"sample_rate": RATE, "encoding": "pcm_s16le", "speech_model": "universal-3-5-pro",
              "language_codes": json.dumps(["hi", "en"]), "voice_focus": "near-field",
              "voice_focus_threshold": 0.7, "vad_threshold": 0.6, **opts}
    url = "wss://streaming.assemblyai.com/v3/ws?" + urlencode(params)
    async with websockets.connect(url, additional_headers={
            "Authorization": os.environ["ASSEMBLYAI_API_KEY"]}) as ws:
        async def send(ws, b):
            await ws.send(b)
        end_at = time.monotonic() + speech_end(pcm)
        sender = asyncio.create_task(stream(ws, pcm, send))
        async for msg in ws:
            m = json.loads(msg)
            if m.get("type") == "Turn" and m.get("end_of_turn"):
                sender.cancel()
                return time.monotonic() - end_at, m.get("transcript", "")
    return float("nan"), ""


async def sarvam(pcm: bytes, **opts) -> tuple[float, str]:
    params = {"language_code": "hi-IN", "stream_type": "fast", "endpointing": "vad",
              "encoding": "linear16", "sample_rate": RATE, "model": "saaras:v3-realtime",
              "mode": "transcribe", "threshold": 0.6, **opts}
    url = "wss://api.sarvam.ai/speech-to-text-realtime/ws?" + urlencode(params)
    async with websockets.connect(url, additional_headers={
            "API-SUBSCRIPTION-KEY": os.environ["SARVAM_API_KEY"]}) as ws:
        async def send(ws, b):
            await ws.send(json.dumps({"event": "audio_input", "audio": base64.b64encode(b).decode()}))
        end_at = time.monotonic() + speech_end(pcm)
        sender = asyncio.create_task(stream(ws, pcm, send))
        async for msg in ws:
            m = json.loads(msg)
            if m.get("event") == "transcript.final":
                sender.cancel()
                return time.monotonic() - end_at, m.get("transcript") or m.get("text") or str(m)[:80]
            if m.get("event") == "error":
                sender.cancel()
                return float("nan"), str(m)[:120]
    return float("nan"), ""


SETUPS = {
    # What the VM runs today (.env: min_latency, max 900, min 100).
    "aai_now": lambda p: assemblyai(p, mode="min_latency", min_turn_silence=100, max_turn_silence=900),
    "aai_640": lambda p: assemblyai(p, mode="min_latency", min_turn_silence=100, max_turn_silence=640),
    "aai_400": lambda p: assemblyai(p, mode="min_latency", min_turn_silence=100, max_turn_silence=400),
    "aai_balanced_640": lambda p: assemblyai(p, mode="balanced", min_turn_silence=100, max_turn_silence=640),
    "sarvam_fast": lambda p: sarvam(p),
    "sarvam_fast_500": lambda p: sarvam(p, silence_duration_ms=500),
    "sarvam_fast_300": lambda p: sarvam(p, silence_duration_ms=300),
}


async def main(names):
    audio = [(t, speech(t)) for t in LINES]
    for name in names:
        secs = []
        for text, pcm in audio:
            try:
                lag, heard = await SETUPS[name](pcm)
            except Exception as e:  # one bad line should not hide the others
                lag, heard = float("nan"), f"ERR {type(e).__name__}: {e}"[:100]
            secs.append(lag)
            print(f"  {name:18} {lag:5.2f}s  {heard[:60]}")
        ok = [s for s in secs if s == s]
        if ok:
            print(f"{name}: median {statistics.median(ok):.2f}s  max {max(ok):.2f}s  ({len(ok)}/{len(secs)})\n")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or list(SETUPS)))
