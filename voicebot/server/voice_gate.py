"""Keep only the voice at the microphone; silence everyone further away.

AssemblyAI's Voice Focus removes noise, but on the 2026-09-23 calls it still
transcribed colleagues talking near the laptop as the caller. The caller is
the loudest voice by a wide margin — 20 cm from the mic against a metre or two
for anyone else is ~15-20 dB — so audio well below the loudest recent voice is
zeroed before it reaches VAD and STT.

ponytail: a loudness gate, not speaker isolation. Someone as close to the mic
as the caller is as loud as the caller and passes. A speaker-isolation model
(ai-coustics AICFilter or Krisp KrispVivaFilter, both already in Pipecat,
both need a licence key) is the upgrade if that case matters.
"""

import numpy as np
from pipecat.audio.filters.base_audio_filter import BaseAudioFilter


class PrimaryVoiceGate(BaseAudioFilter):
    def __init__(
        self,
        margin_db: float = 15.0,
        floor_db: float = -55.0,
        hold_secs: float = 0.4,
        decay_db_per_sec: float = 3.0,
    ):
        # margin: how far below the loudest recent voice still counts as the caller.
        # floor: below this is line hiss, never speech.
        # hold: keep the gate open this long after the caller's last loud frame,
        #   so soft word endings between syllables are not chopped.
        # decay: how fast the "loudest voice" estimate relaxes, so a cough or a
        #   door slam does not mute the caller for long.
        self._margin = margin_db
        self._floor = floor_db
        self._hold_secs = hold_secs
        self._decay = decay_db_per_sec
        self._rate = 16000
        self._level = floor_db
        self._hold = 0.0

    async def start(self, sample_rate: int):
        self._rate = sample_rate

    async def stop(self):
        pass

    async def process_frame(self, frame):
        pass

    async def filter(self, audio: bytes) -> bytes:
        if not audio:
            return audio
        x = np.frombuffer(audio, dtype=np.int16).astype(np.float32)
        secs = len(x) / self._rate
        db = 20 * np.log10(np.sqrt(np.mean(x * x)) / 32768 + 1e-9)
        self._level = max(self._level - self._decay * secs, self._floor)
        self._level = max(self._level, db)
        if db >= self._floor and db >= self._level - self._margin:
            self._hold = self._hold_secs
        else:
            self._hold -= secs
        return audio if self._hold > 0 else bytes(len(audio))


if __name__ == "__main__":
    import asyncio

    def frame(db: float) -> bytes:
        amp = 32768 * 10 ** (db / 20) * np.sqrt(2)
        t = np.arange(320) / 16000  # 20 ms
        return (amp * np.sin(2 * np.pi * 200 * t)).astype(np.int16).tobytes()

    async def main():
        g = PrimaryVoiceGate()
        await g.start(16000)
        near, far, soft = frame(-20), frame(-40), frame(-30)
        assert await g.filter(near) == near                      # caller passes
        for _ in range(19):                                      # hold spans 0.4 s
            await g.filter(far)
        assert await g.filter(far) == bytes(len(far))            # colleague muted
        assert await g.filter(near) == near
        assert await g.filter(soft) == soft                      # caller, softer: kept
        print("voice gate ok")

    asyncio.run(main())
