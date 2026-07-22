"""Unit tests for OmniVoice TTS handler."""

import sys
from pathlib import Path
from threading import Event
from queue import Queue
from unittest.mock import MagicMock

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.cancel_scope import CancelScope
from handlers.tts.omnivoice_tts_handler import OmniVoiceTTSHandler


def _make_handler(**kwargs):
    should_listen = Event()
    defaults = {
        "should_listen": should_listen,
        "base_url": "http://localhost:8864",
        "sample_rate": 24000,
        "blocksize": 512,
    }
    defaults.update(kwargs)
    handler = OmniVoiceTTSHandler(
        stop_event=Event(),
        queue_in=Queue(),
        queue_out=Queue(),
        setup_args=(defaults.pop("should_listen"),),
        setup_kwargs=defaults,
    )
    return handler, should_listen


class TestOmniVoiceSetup:
    def test_default_setup(self):
        handler, _ = _make_handler()
        assert handler.base_url == "http://localhost:8864"
        assert handler.sample_rate == 24000
        assert handler.blocksize == 512
        assert handler.ref_audio_path == "/upfs/fukewei/FunAudioLLM/ref_audio_clean.wav"

    def test_trailing_slash_stripped(self):
        handler, _ = _make_handler(base_url="http://localhost:8864/")
        assert handler.base_url == "http://localhost:8864"

    def test_custom_params(self):
        handler, _ = _make_handler(
            base_url="http://myhost:9000",
            ref_audio_path="/my/ref.wav",
            ref_text="custom ref",
            num_step=32,
            sample_rate=16000,
        )
        assert handler.base_url == "http://myhost:9000"
        assert handler.ref_audio_path == "/my/ref.wav"
        assert handler.ref_text == "custom ref"
        assert handler.num_step == 32
        assert handler.sample_rate == 16000


class TestOmniVoiceProcess:
    def test_end_of_response_yields_marker(self):
        handler, _ = _make_handler()
        results = list(handler.process(("__END_OF_RESPONSE__",)))
        assert results == [b"__RESPONSE_DONE__"]

    def test_empty_text_yields_nothing(self):
        handler, _ = _make_handler()
        results = list(handler.process(("", "zh")))
        assert results == []

    def test_whitespace_only_yields_nothing(self):
        handler, _ = _make_handler()
        results = list(handler.process(("   ", "zh")))
        assert results == []

    def test_synthesize_produces_correct_chunks(self):
        handler, _ = _make_handler(blocksize=256)

        n_samples = 1000
        pcm = np.arange(n_samples, dtype=np.int16)
        handler._synthesize = MagicMock(return_value=pcm.tobytes())

        results = list(handler.process(("你好", "zh")))

        assert len(results) == 4  # ceil(1000/256)
        for chunk in results:
            assert isinstance(chunk, np.ndarray)
            assert chunk.dtype == np.int16
            assert len(chunk) == 256

        # First chunk should have the first 256 samples
        np.testing.assert_array_equal(results[0], pcm[:256])

    def test_last_chunk_is_padded(self):
        handler, _ = _make_handler(blocksize=512)

        pcm = np.ones(700, dtype=np.int16)
        handler._synthesize = MagicMock(return_value=pcm.tobytes())

        results = list(handler.process(("test", "en")))
        assert len(results) == 2
        assert len(results[1]) == 512
        assert np.all(results[1][188:] == 0)

    def test_cancel_scope_interrupts(self):
        scope = CancelScope()
        handler, _ = _make_handler(cancel_scope=scope, blocksize=100)

        pcm = np.ones(500, dtype=np.int16)
        handler._synthesize = MagicMock(return_value=pcm.tobytes())

        call_count = 0
        original_is_stale = scope.is_stale

        def cancel_after_first(gen):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                scope.cancel()
                return True
            return original_is_stale(gen)

        scope.is_stale = cancel_after_first

        results = list(handler.process(("test", "zh")))
        assert len(results) < 5

    def test_synthesis_failure_does_not_set_should_listen(self):
        """Per-sentence failures should NOT re-enable listening; only __END_OF_RESPONSE__ does."""
        handler, sl = _make_handler()
        handler._synthesize = MagicMock(side_effect=RuntimeError("connection refused"))

        results = list(handler.process(("test", "zh")))
        assert results == []
        assert not sl.is_set()

    def test_empty_synthesis_does_not_set_should_listen(self):
        """Empty TTS output should NOT re-enable listening; only __END_OF_RESPONSE__ does."""
        handler, sl = _make_handler()
        handler._synthesize = MagicMock(return_value=b"")

        results = list(handler.process(("test", "zh")))
        assert results == []
        assert not sl.is_set()

    def test_end_of_response_does_not_set_should_listen(self):
        """TTS no longer sets should_listen; LocalAudioStreamer does after playback."""
        handler, sl = _make_handler()
        assert not sl.is_set()
        results = list(handler.process(("__END_OF_RESPONSE__",)))
        assert results == [b"__RESPONSE_DONE__"]
        assert not sl.is_set()
