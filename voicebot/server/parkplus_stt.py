"""Speech-to-text against Park+'s own flex-chunk server.

Replaces AssemblyAI. Park+ runs it, so there is no per-minute billing and no
third-party quota — the same reason the LLM moved to llm.parkplus.io.

The protocol (MEASURED against wss://speech-to-text.parkplus.io/asr on
2026-09-18, not just read off the doc):

    -> binary PCM, s16le, mono, 16000 Hz
    <- {"type":"config", ...}                       once, on connect
    <- {"type":"partial", committed, live, tail}    continuously
    -> b""                                          "I am done talking"
    <- {"type":"final", committed, live, tail}      the settled transcript
    <- {"type":"ready_to_stop"}

Two things about it shape this whole file:

1. A `final` arrives ONLY after the client sends the empty frame. The protocol is
   per-SESSION, but a voice bot needs one final per TURN. So the socket is
   flushed and reopened on every user turn — see _maybe_reconnect_on_user_stopped_speaking.

2. It transcribes Hindi into ROMANISED LATIN, not Devanagari:
   "हाँ जी, मेरी Creta है" comes back "Haan ji meri creta hai". Anything
   downstream that decides "is this Hindi?" by looking for Devanagari is wrong
   about this service's output. bot.py's NoiseGate is the one that cared.
"""

import asyncio
import json
from typing import AsyncGenerator

import websockets
from loguru import logger

from pipecat.audio.utils import create_stream_resampler
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    InterimTranscriptionFrame,
    StartFrame,
    TranscriptionFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.services.settings import STTSettings
from pipecat.services.stt_service import STTService
from pipecat.services.websocket_service import WebsocketService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601

# The server accepts nothing else; its own config message says so on every
# connect, and sending 48k float silently produces empty transcripts.
PARKPLUS_STT_RATE = 16000


class ParkPlusSTTService(STTService, WebsocketService):
    """Streams call audio to Park+'s flex-chunk ASR and emits transcription frames."""

    def __init__(
        self,
        *,
        url: str = "wss://speech-to-text.parkplus.io/asr",
        final_timeout: float = 2.0,
        chunk_ms: int = 100,
        language: Language = Language.HI,
        ttfs_p99_latency: float = 1.0,
        **kwargs,
    ):
        # Every STTSettings field must be set explicitly, including the ones this
        # service does not support. Leaving them NOT_GIVEN logs
        # "STTSettings: the following fields are NOT_GIVEN: model, language" at
        # ERROR on every start, and leaves self._settings.language as a sentinel
        # that then rides into every TranscriptionFrame this service pushes.
        # The server picks its own model, so model is None, not unset.
        #
        # Deliberately NOT sample_rate=PARKPLUS_STT_RATE. Passing it pins
        # self.sample_rate to 16000 no matter what the transport actually
        # produces, and run_stt below resamples FROM self.sample_rate — so the
        # resample silently became 16000->16000, a no-op, and 24 kHz audio went
        # to the server labelled as 16 kHz. It transcribes that as near-silence.
        # Leaving it unset makes self.sample_rate the real pipeline rate, which
        # is the number the resample actually needs.
        STTService.__init__(
            self,
            ttfs_p99_latency=ttfs_p99_latency,
            settings=STTSettings(model=None, language=language, extra={}),
            **kwargs,
        )
        WebsocketService.__init__(self, reconnect_on_error=True)
        self._url = url
        self._final_timeout = final_timeout
        # The pipeline hands run_stt roughly fifty audio frames a second. Awaiting
        # a websocket send to a REMOTE server on each one made this processor the
        # slowest thing in the pipeline, and everything queued behind it — the
        # opening greeting included — waited on those sends. The symptom was
        # brutal to read: with no microphone the bot greeted in 3s, and on a live
        # call with audio flowing it never spoke at all.
        #
        # So batch. One send per chunk_ms of audio instead of one per frame, which
        # is what pipecat's own AssemblyAI service does (_chunk_size_bytes) for
        # the same reason. 100ms is what the Park+ demo page uses too.
        self._chunk_ms = chunk_ms
        self._buffer = bytearray()
        self._resampler = create_stream_resampler()
        self._receive_task = None
        # Set when a "final" (or ready_to_stop) lands, so the turn flush can wait
        # for the settled transcript instead of guessing how long it takes.
        self._final_event = asyncio.Event()
        self._flushing = False

    # --- lifecycle -----------------------------------------------------------

    async def start(self, frame: StartFrame):
        await super().start(frame)
        await self._connect()

    async def stop(self, frame: EndFrame):
        await super().stop(frame)
        await self._disconnect()

    async def cancel(self, frame: CancelFrame):
        await super().cancel(frame)
        await self._disconnect()

    async def _connect(self):
        await WebsocketService._connect(self)
        await self._connect_websocket()
        if self._websocket and not self._receive_task:
            self._receive_task = self.create_task(
                self._receive_task_handler(self._report_error)
            )

    async def _disconnect(self):
        await WebsocketService._disconnect(self)
        if self._receive_task:
            await self.cancel_task(self._receive_task)
            self._receive_task = None
        await self._disconnect_websocket()

    async def _connect_websocket(self):
        try:
            if self._websocket and self._websocket.state is websockets.State.OPEN:
                return
            logger.debug(f"{self}: connecting to {self._url}")
            self._websocket = await self._websocket_connect(self._url, max_size=None)
        except Exception as e:
            logger.error(f"{self}: could not connect to Park+ STT: {e}")
            self._websocket = None
            await self._call_event_handler("on_connection_error", f"{e}")

    async def _disconnect_websocket(self):
        try:
            if not self._websocket:
                return
            logger.debug(f"{self}: disconnecting from Park+ STT")
            await self._websocket.close()
        except Exception as e:
            logger.error(f"{self}: error closing websocket: {e}")
        finally:
            self._websocket = None

    async def _report_error(self, error: ErrorFrame, force_treat_as_permanent: bool = False):
        await self.push_error(error)

    # --- audio in ------------------------------------------------------------

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        """Forward call audio to the socket. Transcripts arrive on the receive task.

        The pipeline's rate is whatever the transport negotiated, and this server
        accepts exactly 16 kHz, so resample every chunk rather than assuming.
        """
        if self._flushing:
            # Mid-turn-flush: this audio belongs to the next turn and the socket
            # is about to be replaced. Dropping it is better than racing a close.
            yield None
            return
        if not self._websocket or self._websocket.state is not websockets.State.OPEN:
            yield None
            return
        pcm = await self._resampler.resample(audio, self.sample_rate, PARKPLUS_STT_RATE)
        if pcm:
            self._buffer.extend(pcm)
        # 2 bytes per sample, mono.
        chunk_bytes = int(PARKPLUS_STT_RATE * 2 * self._chunk_ms / 1000)
        while len(self._buffer) >= chunk_bytes:
            chunk = bytes(self._buffer[:chunk_bytes])
            del self._buffer[:chunk_bytes]
            await self._websocket.send(chunk)
        yield None

    # --- transcripts out -----------------------------------------------------

    async def _receive_messages(self):
        async for message in self._websocket:
            if isinstance(message, bytes):
                continue
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                logger.warning(f"{self}: non-JSON message from STT: {message!r:.80}")
                continue

            kind = data.get("type")
            if kind == "config":
                logger.debug(f"{self}: STT ready — {data}")
                continue
            if kind == "ready_to_stop":
                self._final_event.set()
                continue
            if kind not in ("partial", "final"):
                continue

            text = (data.get("text") or "").strip()
            language = self._settings.language
            if kind == "final" or data.get("final"):
                self._final_event.set()
                if text:
                    await self.push_frame(
                        TranscriptionFrame(
                            text, "", time_now_iso8601(), language, result=data
                        )
                    )
                    await self.stop_processing_metrics()
            elif text:
                await self.push_frame(
                    InterimTranscriptionFrame(
                        text, "", time_now_iso8601(), language, result=data
                    )
                )

    # --- turn boundaries -----------------------------------------------------

    async def _handle_vad_user_stopped_speaking(self, frame: VADUserStoppedSpeakingFrame):
        """Flush the ASR turn the moment VAD says the caller stopped talking.

        THIS HOOK, not UserStoppedSpeakingFrame, and the difference is a deadlock.

        UserStoppedSpeakingFrame is emitted by the turn-stop strategy, which waits
        for a final transcript before it will declare the turn over. This server
        emits a final only after the empty frame, which the flush sends. So
        flushing on UserStoppedSpeakingFrame means: the strategy waits for a
        transcript, the transcript waits for the flush, the flush waits for the
        strategy. Measured on 2026-09-18: the caller spoke at 18:43:50 and the
        transcript appeared at 18:44:52 — 62 seconds later, only once the socket
        was closed at shutdown. The bot never answered a single turn.

        VAD stop depends on nothing but audio, so it breaks the cycle: flush here,
        the final lands, the strategy sees it and ends the turn normally.
        """
        await super()._handle_vad_user_stopped_speaking(frame)
        await self._flush_turn()

    async def _flush_turn(self):
        """End the ASR session so it emits a final, then open a fresh one.

        This server only produces a `final` after the empty frame, so without
        this the bot would only ever see partials and would answer whatever the
        volatile `tail` happened to say. Reconnecting here — rather than at the
        start of the next turn — hides the connection setup behind the bot's own
        reply, so the caller never waits for it.
        """
        if not self._websocket or self._websocket.state is not websockets.State.OPEN:
            return
        self._flushing = True
        self._final_event.clear()
        # Anything still buffered belongs to the turn being closed, so send it
        # before the empty frame rather than leaking it into the next session.
        if self._buffer and self._websocket:
            try:
                await self._websocket.send(bytes(self._buffer))
            except Exception:
                pass
        self._buffer.clear()
        # Tell WebsocketService this close is deliberate. Without it the receive
        # task treats the per-turn close as a dropped connection: it logs
        # "connection lasted only 4.7s (1/3 consecutive quick failures)" and
        # races its own reconnect against ours. On a real call every turn is a
        # few seconds long, so three turns would trip the quick-failure circuit
        # breaker and take the ASR down mid-conversation.
        self._disconnecting = True
        try:
            await self._websocket.send(b"")
            try:
                await asyncio.wait_for(self._final_event.wait(), self._final_timeout)
            except asyncio.TimeoutError:
                # Never hold the turn open on a slow ASR: the caller has stopped
                # talking and is waiting. The partials already pushed are what
                # the aggregator will use.
                logger.warning(
                    f"{self}: no final within {self._final_timeout}s — continuing"
                )
        except Exception as e:
            logger.error(f"{self}: error flushing the ASR turn: {e}")
        finally:
            # Receive task FIRST, then the socket. Closing underneath a live
            # receive loop makes it observe the close as a failure and log
            # "error during disconnect: no close frame received or sent" on
            # every single turn, which is exactly the noise call.log exists to
            # avoid. We already have the final by this point, so the loop has
            # nothing left to read.
            if self._receive_task:
                await self.cancel_task(self._receive_task)
                self._receive_task = None
            await self._disconnect_websocket()
            self._disconnecting = False
            self._quick_failure_tracker.reset()
            await self._connect_websocket()
            if self._websocket and not self._receive_task:
                self._receive_task = self.create_task(
                    self._receive_task_handler(self._report_error)
                )
            self._flushing = False
