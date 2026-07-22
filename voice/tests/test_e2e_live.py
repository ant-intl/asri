"""End-to-end live tests against real services.

Requires:
  - STT service reachable (configure via TEST_STT_URL env var)
  - LLM API reachable (configure via TEST_LLM_BASE_URL / TEST_LLM_API_KEY)
  - TTS service reachable (localhost:8864)

Run:
    uv run python -m pytest tests/test_e2e_live.py -v -s

Skip if no network:
    uv run python -m pytest tests/test_e2e_live.py -v -s -k "not live"
"""

import io
import os
import sys
import time
import wave
from pathlib import Path
from threading import Event, Thread
from queue import Queue, Empty

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ---------------------------------------------------------------------------
# Skip marker: check connectivity once
# ---------------------------------------------------------------------------

# Environment-based config for live tests
TEST_STT_URL = os.environ.get("TEST_STT_URL", "http://localhost:8000/v1/audio/transcriptions")
TEST_LLM_BASE_URL = os.environ.get("TEST_LLM_BASE_URL", "https://api.openai.com/v1")
TEST_LLM_API_KEY = os.environ.get("TEST_LLM_API_KEY", "test-key")


def _can_reach_asr():
    try:
        import requests
        resp = requests.post(
            TEST_STT_URL,
            json={"features": {}, "tensorFeatures": {"query": {"shapes": [1], "stringValues": [""]}}},
            headers={"Content-Type": "application/json;charset=utf-8"},
            timeout=5,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _can_reach_tts():
    try:
        import requests
        resp = requests.post("http://localhost:8864/tts/fast", data={"text": "test"}, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def _can_reach_llm():
    try:
        import requests
        resp = requests.get(
            f"{TEST_LLM_BASE_URL}/models",
            headers={"Authorization": f"Bearer {TEST_LLM_API_KEY}"},
            timeout=5,
        )
        return resp.status_code == 200
    except Exception:
        return False


_asr_ok = None
_tts_ok = None
_llm_ok = None


def check_asr():
    global _asr_ok
    if _asr_ok is None:
        _asr_ok = _can_reach_asr()
    return _asr_ok


def check_tts():
    global _tts_ok
    if _tts_ok is None:
        _tts_ok = _can_reach_tts()
    return _tts_ok


def check_llm():
    global _llm_ok
    if _llm_ok is None:
        _llm_ok = _can_reach_llm()
    return _llm_ok


skip_no_asr = pytest.mark.skipif("not check_asr()", reason="SenseVoice API unreachable")
skip_no_tts = pytest.mark.skipif("not check_tts()", reason="OmniVoice TTS unreachable (localhost:8864)")
skip_no_llm = pytest.mark.skipif("not check_llm()", reason="LLM API unreachable")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_speech_audio(text_hint="speech", duration=2.0, sr=16000):
    """Generate a 'speech-like' audio segment (sine sweep, not real speech).

    Real ASR will return something for any non-silent audio.
    """
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    freq = 200 + 300 * t / duration  # sweep 200-500 Hz
    audio = (np.sin(2 * np.pi * freq * t) * 20000).astype(np.int16)
    return audio


# ===========================================================================
# 1. SenseVoice ASR — live
# ===========================================================================

class TestSenseVoiceLive:
    @skip_no_asr
    def test_asr_returns_text(self):
        from handlers.stt.sensevoice_handler import SenseVoiceSTTHandler

        handler = SenseVoiceSTTHandler(
            stop_event=Event(), queue_in=Queue(), queue_out=Queue(),
        )

        audio = make_speech_audio(duration=2.0)
        results = list(handler.process(audio))

        assert len(results) >= 1
        text, lang = results[0]
        assert isinstance(text, str)
        assert len(text) > 0
        assert lang == "zh"

    @skip_no_asr
    def test_asr_latency_under_3s(self):
        from handlers.stt.sensevoice_handler import SenseVoiceSTTHandler

        handler = SenseVoiceSTTHandler(
            stop_event=Event(), queue_in=Queue(), queue_out=Queue(),
        )

        audio = make_speech_audio(duration=1.0)
        t0 = time.time()
        list(handler.process(audio))
        elapsed = time.time() - t0

        assert elapsed < 3.0, f"ASR took {elapsed:.1f}s, expected < 3s"

    @skip_no_asr
    def test_asr_silent_audio_returns_something(self):
        """Even silence or noise should not crash the handler."""
        from handlers.stt.sensevoice_handler import SenseVoiceSTTHandler

        handler = SenseVoiceSTTHandler(
            stop_event=Event(), queue_in=Queue(), queue_out=Queue(),
        )

        silence = np.zeros(16000, dtype=np.int16)
        results = list(handler.process(silence))
        # May or may not return text, but should not raise
        assert isinstance(results, list)


# ===========================================================================
# 2. OmniVoice TTS — live
# ===========================================================================

class TestOmniVoiceLive:
    @skip_no_tts
    def test_tts_produces_audio(self):
        from handlers.tts.omnivoice_tts_handler import OmniVoiceTTSHandler

        handler = OmniVoiceTTSHandler(
            stop_event=Event(), queue_in=Queue(), queue_out=Queue(),
            setup_args=(Event(),),
            setup_kwargs={"base_url": "http://localhost:8864", "blocksize": 512, "sample_rate": 24000},
        )

        chunks = list(handler.process(("你好世界", "zh")))
        audio_chunks = [c for c in chunks if isinstance(c, np.ndarray)]

        assert len(audio_chunks) > 0
        total_samples = sum(len(c) for c in audio_chunks)
        duration = total_samples / 24000
        assert duration > 0.5, f"Too short: {duration:.2f}s"
        assert duration < 10.0, f"Too long: {duration:.2f}s"

    @skip_no_tts
    def test_tts_latency_under_5s(self):
        from handlers.tts.omnivoice_tts_handler import OmniVoiceTTSHandler

        handler = OmniVoiceTTSHandler(
            stop_event=Event(), queue_in=Queue(), queue_out=Queue(),
            setup_args=(Event(),),
            setup_kwargs={"base_url": "http://localhost:8864", "blocksize": 512, "sample_rate": 24000},
        )

        t0 = time.time()
        chunks = list(handler.process(("测试延迟", "zh")))
        elapsed = time.time() - t0

        assert len([c for c in chunks if isinstance(c, np.ndarray)]) > 0
        assert elapsed < 5.0, f"TTS took {elapsed:.1f}s, expected < 5s"

    @skip_no_tts
    def test_tts_end_of_response_marker(self):
        from handlers.tts.omnivoice_tts_handler import OmniVoiceTTSHandler

        handler = OmniVoiceTTSHandler(
            stop_event=Event(), queue_in=Queue(), queue_out=Queue(),
            setup_args=(Event(),),
            setup_kwargs={"base_url": "http://localhost:8864", "blocksize": 512, "sample_rate": 24000},
        )

        results = list(handler.process(("__END_OF_RESPONSE__",)))
        assert results == [b"__RESPONSE_DONE__"]

    @skip_no_tts
    def test_tts_chunk_format(self):
        from handlers.tts.omnivoice_tts_handler import OmniVoiceTTSHandler

        handler = OmniVoiceTTSHandler(
            stop_event=Event(), queue_in=Queue(), queue_out=Queue(),
            setup_args=(Event(),),
            setup_kwargs={"base_url": "http://localhost:8864", "blocksize": 512, "sample_rate": 24000},
        )

        chunks = list(handler.process(("测试", "zh")))
        audio_chunks = [c for c in chunks if isinstance(c, np.ndarray)]

        for chunk in audio_chunks:
            assert chunk.dtype == np.int16
            assert len(chunk) == 512


# ===========================================================================
# 3. LLM — live
# ===========================================================================

class TestLLMLive:
    @skip_no_llm
    def test_llm_streaming_response(self):
        from pipeline.cancel_scope import CancelScope
        from handlers.llm.chat import Chat
        from handlers.llm.openai_api_language_model import OpenApiModelHandler

        handler = object.__new__(OpenApiModelHandler)
        handler.model_name = "Qwen3-30B-A3B-Instruct-2507"
        handler.stream = True
        handler.gen_kwargs = {}
        handler.request_timeout_s = 20.0
        handler.request_timeout = 20.0
        handler.disable_thinking = True
        handler._extra_body = {"chat_template_kwargs": {"enable_thinking": False}}
        handler.user_role = "user"
        handler.chat = Chat(5)
        handler.runtime_config = None
        handler.cancel_scope = CancelScope()
        handler.tools = None
        handler.tools_choice = None

        import openai
        handler.client = openai.OpenAI(
            base_url=TEST_LLM_BASE_URL,
            api_key=TEST_LLM_API_KEY,
            timeout=20.0,
        )

        t0 = time.time()
        outputs = list(handler.process("你好"))
        elapsed = time.time() - t0

        # Should get at least one text sentence + end marker
        texts = [o for o in outputs if isinstance(o, tuple) and o[0] != "__END_OF_RESPONSE__"]
        end_markers = [o for o in outputs if isinstance(o, tuple) and o[0] == "__END_OF_RESPONSE__"]

        assert len(texts) > 0, "LLM produced no text"
        assert len(end_markers) == 1, "Missing __END_OF_RESPONSE__"
        assert elapsed < 15.0, f"LLM took {elapsed:.1f}s"

        # Text content check
        full_text = " ".join(t[0] for t in texts)
        assert len(full_text) > 0

    @skip_no_llm
    def test_llm_latency_first_token(self):
        from pipeline.cancel_scope import CancelScope
        from handlers.llm.chat import Chat
        from handlers.llm.openai_api_language_model import OpenApiModelHandler

        handler = object.__new__(OpenApiModelHandler)
        handler.model_name = "Qwen3-30B-A3B-Instruct-2507"
        handler.stream = True
        handler.gen_kwargs = {}
        handler.request_timeout_s = 20.0
        handler.request_timeout = 20.0
        handler.disable_thinking = True
        handler._extra_body = {"chat_template_kwargs": {"enable_thinking": False}}
        handler.user_role = "user"
        handler.chat = Chat(5)
        handler.runtime_config = None
        handler.cancel_scope = CancelScope()
        handler.tools = None
        handler.tools_choice = None

        import openai
        handler.client = openai.OpenAI(
            base_url=TEST_LLM_BASE_URL,
            api_key=TEST_LLM_API_KEY,
            timeout=20.0,
        )

        t0 = time.time()
        for output in handler.process("说一个字"):
            first_token_time = time.time() - t0
            break

        assert first_token_time < 5.0, f"First token took {first_token_time:.1f}s"


# ===========================================================================
# 4. Full pipeline: ASR -> LLM -> TTS (live)
# ===========================================================================

class TestFullPipelineLive:
    @skip_no_asr
    @skip_no_llm
    @skip_no_tts
    def test_full_pipeline_produces_audio(self):
        """STT -> LLM -> TTS end-to-end with real services."""
        from handlers.stt.sensevoice_handler import SenseVoiceSTTHandler
        from handlers.llm.openai_api_language_model import OpenApiModelHandler
        from handlers.llm.chat import Chat
        from handlers.tts.omnivoice_tts_handler import OmniVoiceTTSHandler
        from pipeline.cancel_scope import CancelScope
        import openai

        stop = Event()
        should_listen = Event()

        # --- STT ---
        stt = SenseVoiceSTTHandler(
            stop_event=stop, queue_in=Queue(), queue_out=Queue(),
        )

        # --- LLM ---
        llm = object.__new__(OpenApiModelHandler)
        llm.model_name = "Qwen3-30B-A3B-Instruct-2507"
        llm.stream = True
        llm.gen_kwargs = {}
        llm.request_timeout_s = 20.0
        llm.request_timeout = 20.0
        llm.disable_thinking = True
        llm._extra_body = {"chat_template_kwargs": {"enable_thinking": False}}
        llm.user_role = "user"
        llm.chat = Chat(5)
        llm.runtime_config = None
        llm.cancel_scope = CancelScope()
        llm.tools = None
        llm.tools_choice = None
        llm.client = openai.OpenAI(
            base_url=TEST_LLM_BASE_URL,
            api_key=TEST_LLM_API_KEY,
            timeout=20.0,
        )

        # --- TTS ---
        tts = OmniVoiceTTSHandler(
            stop_event=stop, queue_in=Queue(), queue_out=Queue(),
            setup_args=(should_listen,),
            setup_kwargs={"base_url": "http://localhost:8864", "blocksize": 512, "sample_rate": 24000},
        )

        # === Step 1: ASR ===
        audio_in = make_speech_audio(duration=2.0)
        t0 = time.time()
        stt_results = list(stt.process(audio_in))
        stt_time = time.time() - t0

        assert len(stt_results) > 0, "ASR returned nothing"
        stt_text, stt_lang = stt_results[0]
        print(f"\n  [ASR] '{stt_text}' ({stt_time:.1f}s)")

        # === Step 2: LLM ===
        t1 = time.time()
        llm_outputs = list(llm.process(stt_text))
        llm_time = time.time() - t1

        sentences = [o for o in llm_outputs if isinstance(o, tuple) and o[0] != "__END_OF_RESPONSE__"]
        assert len(sentences) > 0, "LLM returned no sentences"
        print(f"  [LLM] {len(sentences)} sentences ({llm_time:.1f}s): {[s[0][:20] for s in sentences]}")

        # === Step 3: TTS (first sentence only for speed) ===
        first_sentence = sentences[0]
        t2 = time.time()
        tts_chunks = list(tts.process(first_sentence))
        tts_time = time.time() - t2

        audio_chunks = [c for c in tts_chunks if isinstance(c, np.ndarray)]
        assert len(audio_chunks) > 0, "TTS produced no audio"
        total_samples = sum(len(c) for c in audio_chunks)
        duration = total_samples / 24000
        print(f"  [TTS] {len(audio_chunks)} chunks, {duration:.2f}s audio ({tts_time:.1f}s)")

        # === Timing summary ===
        total = stt_time + llm_time + tts_time
        print(f"  [Total] ASR={stt_time:.1f}s + LLM={llm_time:.1f}s + TTS={tts_time:.1f}s = {total:.1f}s")

        assert total < 20.0, f"Pipeline too slow: {total:.1f}s"

    @skip_no_asr
    @skip_no_llm
    @skip_no_tts
    def test_pipeline_with_prefetch(self):
        """Test that PrefetchHandler works with real TTS."""
        from handlers.tts.omnivoice_tts_handler import OmniVoiceTTSHandler
        from pipeline.prefetch_handler import PrefetchHandler

        stop = Event()
        should_listen = Event()
        tts_in = Queue()
        tts_out = Queue()

        inner = OmniVoiceTTSHandler(
            stop_event=stop, queue_in=tts_in, queue_out=tts_out,
            setup_args=(should_listen,),
            setup_kwargs={"base_url": "http://localhost:8864", "blocksize": 512, "sample_rate": 24000},
        )
        ph = PrefetchHandler(inner, prefetch=2)

        # Run in background
        t = Thread(target=ph.run, daemon=True)
        t.start()

        # Feed 2 sentences
        tts_in.put(("第一句话。", "zh"))
        tts_in.put(("第二句话。", "zh"))
        tts_in.put(b"END")

        # Collect output
        results = []
        t0 = time.time()
        while time.time() - t0 < 30:
            try:
                item = tts_out.get(timeout=0.5)
            except Empty:
                continue
            if isinstance(item, bytes) and item == b"END":
                break
            results.append(item)

        t.join(timeout=3)

        audio_chunks = [c for c in results if isinstance(c, np.ndarray)]
        total_samples = sum(len(c) for c in audio_chunks)
        duration = total_samples / 24000

        print(f"\n  [Prefetch] {len(audio_chunks)} chunks, {duration:.2f}s audio")
        assert len(audio_chunks) > 0
        assert duration > 0.5
