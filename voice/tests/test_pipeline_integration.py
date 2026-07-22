"""Integration tests for the custom STT -> LLM -> TTS pipeline.

These tests verify the handlers work together through queues,
using mocked external services (no network calls).
"""

import sys
import time
from pathlib import Path
from threading import Event, Thread
from queue import Queue
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.cancel_scope import CancelScope
from pipeline.control import SESSION_END


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_audio(duration=1.0, sr=16000):
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    return (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)


def _drain_queue(q, timeout=5.0, sentinel=b"END"):
    """Collect all items from a queue until sentinel or timeout."""
    results = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            item = q.get(timeout=0.1)
        except Exception:
            continue
        if isinstance(item, bytes) and item == sentinel:
            break
        results.append(item)
    return results


# ---------------------------------------------------------------------------
# Test: SenseVoice STT -> queue -> LLM (mocked)
# ---------------------------------------------------------------------------

class TestSTTToLLMIntegration:
    """SenseVoice STT produces (text, lang) tuples that feed into LLM."""

    def test_stt_output_format_matches_llm_input(self):
        from handlers.stt.sensevoice_handler import SenseVoiceSTTHandler

        stop = Event()
        stt_out = Queue()

        handler = SenseVoiceSTTHandler(
            stop_event=stop,
            queue_in=Queue(),
            queue_out=stt_out,
        )

        # Mock the HTTP call
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"resultMap": {"asr": "你好世界"}}
        handler.session.post = MagicMock(return_value=resp)

        audio = _make_audio(0.5)
        for output in handler.process(audio):
            stt_out.put(output)

        result = stt_out.get(timeout=1)
        # LLM handlers expect (text, language_code) or plain text
        assert isinstance(result, tuple)
        assert len(result) == 2
        text, lang = result
        assert isinstance(text, str)
        assert len(text) > 0
        assert lang == "zh"


# ---------------------------------------------------------------------------
# Test: TTS handler output format
# ---------------------------------------------------------------------------

class TestTTSOutputFormat:
    """Both Edge TTS and OmniVoice TTS should produce the same output format."""

    def _test_tts_handler(self, HandlerClass):
        stop = Event()
        should_listen = Event()
        tts_out = Queue()

        handler = HandlerClass(
            stop_event=stop,
            queue_in=Queue(),
            queue_out=tts_out,
            setup_args=(should_listen,),
            setup_kwargs={"blocksize": 256},
        )

        # Mock synthesis to return known PCM
        pcm = np.ones(600, dtype=np.int16)
        handler._synthesize = MagicMock(return_value=pcm.tobytes())

        chunks = list(handler.process(("你好", "zh")))

        # All chunks should be numpy int16 arrays of blocksize
        for chunk in chunks:
            assert isinstance(chunk, np.ndarray)
            assert chunk.dtype == np.int16
            assert len(chunk) == 256

        # End-of-response marker
        end_results = list(handler.process(("__END_OF_RESPONSE__",)))
        assert end_results == [b"__RESPONSE_DONE__"]

    def test_omnivoice_tts_output_format(self):
        from handlers.tts.omnivoice_tts_handler import OmniVoiceTTSHandler
        self._test_tts_handler(OmniVoiceTTSHandler)


# ---------------------------------------------------------------------------
# Test: Full STT -> (mock LLM) -> TTS pipeline via queues
# ---------------------------------------------------------------------------

class TestFullPipelineQueues:
    """End-to-end test: STT output feeds mock LLM, LLM output feeds TTS."""

    def test_stt_to_mock_llm_to_tts(self):
        from handlers.stt.sensevoice_handler import SenseVoiceSTTHandler
        from handlers.tts.omnivoice_tts_handler import OmniVoiceTTSHandler

        # Queues
        stt_out_q = Queue()  # STT -> LLM
        tts_in_q = Queue()   # LLM -> TTS
        tts_out_q = Queue()  # TTS -> audio output

        stop = Event()
        should_listen = Event()

        # --- STT ---
        stt = SenseVoiceSTTHandler(
            stop_event=stop,
            queue_in=Queue(),
            queue_out=stt_out_q,
        )
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"resultMap": {"asr": "帮我查一下"}}
        stt.session.post = MagicMock(return_value=resp)

        # --- TTS ---
        tts = OmniVoiceTTSHandler(
            stop_event=stop,
            queue_in=tts_in_q,
            queue_out=tts_out_q,
            setup_args=(should_listen,),
            setup_kwargs={"blocksize": 256},
        )
        pcm = np.ones(512, dtype=np.int16)
        tts._synthesize = MagicMock(return_value=pcm.tobytes())

        # --- Run STT ---
        audio = _make_audio(1.0)
        for output in stt.process(audio):
            stt_out_q.put(output)

        # --- Mock LLM: read STT output, produce TTS input ---
        stt_result = stt_out_q.get(timeout=1)
        assert stt_result[0] == "帮我查一下"

        # LLM would produce sentences
        llm_sentences = [
            ("好的，我来帮您查询。", "zh"),
            ("请稍等。", "zh"),
            ("__END_OF_RESPONSE__", None),
        ]
        for sent in llm_sentences:
            tts_in_q.put(sent)

        # --- Run TTS ---
        all_chunks = []
        for sent in llm_sentences:
            for chunk in tts.process(sent):
                all_chunks.append(chunk)

        # Should have audio chunks + response done marker
        audio_chunks = [c for c in all_chunks if isinstance(c, np.ndarray)]
        markers = [c for c in all_chunks if isinstance(c, bytes) and c == b"__RESPONSE_DONE__"]

        assert len(audio_chunks) > 0
        assert len(markers) == 1
        # TTS was called twice (for two text sentences)
        assert tts._synthesize.call_count == 2


# ---------------------------------------------------------------------------
# Test: CancelScope works across handlers
# ---------------------------------------------------------------------------

class TestCancelScopeIntegration:
    def test_cancel_stops_tts_mid_stream(self):
        from handlers.tts.omnivoice_tts_handler import OmniVoiceTTSHandler

        scope = CancelScope()
        stop = Event()
        should_listen = Event()

        handler = OmniVoiceTTSHandler(
            stop_event=stop,
            queue_in=Queue(),
            queue_out=Queue(),
            setup_args=(should_listen,),
            setup_kwargs={"blocksize": 100, "cancel_scope": scope},
        )

        # Large audio to ensure multiple chunks
        pcm = np.ones(2000, dtype=np.int16)
        handler._synthesize = MagicMock(return_value=pcm.tobytes())

        gen_before = scope.generation
        chunks = []
        for chunk in handler.process(("long text", "zh")):
            chunks.append(chunk)
            if len(chunks) == 3:
                scope.cancel()  # Interrupt after 3 chunks

        # Should have stopped early (20 chunks if no cancel)
        assert len(chunks) < 20
        assert len(chunks) >= 3


# ---------------------------------------------------------------------------
# Test: Argument classes parse correctly
# ---------------------------------------------------------------------------

class TestArgumentParsing:
    def test_sensevoice_args(self):
        from handlers.stt.arguments import SenseVoiceSTTHandlerArguments
        args = SenseVoiceSTTHandlerArguments()
        assert args.sensevoice_stt_url == ""
        assert args.sensevoice_stt_language == "zh"
        assert args.sensevoice_stt_timeout == 30.0

    def test_omnivoice_tts_args(self):
        from handlers.tts.arguments import OmniVoiceTTSHandlerArguments
        args = OmniVoiceTTSHandlerArguments()
        assert args.omnivoice_tts_base_url == "http://localhost:8864"
        assert args.omnivoice_tts_sample_rate == 24000
        assert args.omnivoice_tts_blocksize == 512
        assert args.omnivoice_tts_ref_audio_path == ""
