import logging
import time

from pipeline.base_handler import BaseHandler

logger = logging.getLogger(__name__)


class TranscriptionNotifier(BaseHandler):
    """
    Sits between STT and LLM.  Intercepts partial and final transcriptions,
    emitting events on ``text_output_queue`` for connected clients (Realtime
    API or plain WebSocket) while only forwarding final transcripts to the LLM.
    """

    def setup(self, text_output_queue=None, cancel_scope=None, runtime_config=None):
        self.text_output_queue = text_output_queue
        self.cancel_scope = cancel_scope
        self.runtime_config = runtime_config

    def process(self, transcription):
        if isinstance(transcription, tuple) and len(transcription) == 2 and transcription[0] == "__PARTIAL__":
            _, text = transcription
            if self.text_output_queue and text:
                self.text_output_queue.put(
                    {"type": "partial_transcription", "delta": str(text)}
                )
                logger.debug("Partial transcription: %s", str(text)[:80])
            return

        text = transcription[0] if isinstance(transcription, tuple) else transcription
        if self.text_output_queue and text:
            msg = {"type": "transcription_completed", "transcript": str(text)}
            if self.cancel_scope and self.cancel_scope.pipeline_start:
                asr_ms = round((time.perf_counter() - self.cancel_scope.pipeline_start) * 1000)
                msg["server_asr_ms"] = asr_ms
                self.cancel_scope.turn_asr_ms = asr_ms
            self.text_output_queue.put(msg)
            logger.debug("Transcription completed: %s", str(text)[:80])
        yield transcription
