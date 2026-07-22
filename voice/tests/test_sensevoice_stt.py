"""Unit tests for SenseVoice STT handler."""

import base64
import io
import json
import sys
import wave
from pathlib import Path
from threading import Event
from queue import Queue
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.stt.sensevoice_handler import SenseVoiceSTTHandler


def _make_handler(**kwargs):
    handler = SenseVoiceSTTHandler(
        stop_event=Event(),
        queue_in=Queue(),
        queue_out=Queue(),
        setup_kwargs=kwargs,
    )
    return handler


def _make_audio(duration=1.0, sr=16000):
    """Generate a short sine wave as int16 PCM."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    return (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)


class TestSenseVoiceSetup:
    def test_default_setup(self):
        handler = _make_handler()
        assert handler.language == "zh"
        assert handler.timeout == 30.0
        assert handler.url == ""
        assert handler.headers["MPS-app-name"] == "speech-to-speech"
        assert handler.headers["MPS-http-version"] == "1.0"

    def test_custom_url(self):
        handler = _make_handler(url="http://localhost:9999/asr")
        assert handler.url == "http://localhost:9999/asr"

    def test_custom_language(self):
        handler = _make_handler(language="en")
        assert handler.language == "en"


class TestPcmToWav:
    def test_produces_valid_wav(self):
        handler = _make_handler()
        audio = _make_audio(0.5)
        wav_bytes = handler._pcm_to_wav(audio)

        assert wav_bytes[:4] == b"RIFF"
        assert wav_bytes[8:12] == b"WAVE"

        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000
            assert wf.getnframes() == len(audio)


class TestCallAsr:
    def test_request_body_format(self):
        handler = _make_handler()
        captured = {}

        def mock_post(url, json=None, headers=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"resultMap": {"asr": "你好"}}
            return resp

        handler.session.post = mock_post
        audio = _make_audio(0.5)
        wav_bytes = handler._pcm_to_wav(audio)
        result = handler._call_asr(wav_bytes)

        assert result == "你好"
        body = captured["json"]
        assert "features" in body
        assert body["features"] == {}
        assert "tensorFeatures" in body
        assert "query" in body["tensorFeatures"]
        assert body["tensorFeatures"]["query"]["shapes"] == [1]
        assert len(body["tensorFeatures"]["query"]["stringValues"]) == 1

        # Verify base64 roundtrip
        decoded = base64.b64decode(body["tensorFeatures"]["query"]["stringValues"][0])
        assert decoded == wav_bytes

    def test_headers_include_mps_fields(self):
        handler = _make_handler()
        captured = {}

        def mock_post(url, json=None, headers=None, timeout=None):
            captured["headers"] = headers
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"resultMap": {"asr": ""}}
            return resp

        handler.session.post = mock_post
        handler._call_asr(b"fake_wav")

        h = captured["headers"]
        assert h["Content-Type"] == "application/json;charset=utf-8"
        assert h["MPS-app-name"] == "speech-to-speech"
        assert h["MPS-http-version"] == "1.0"
        assert "MPS-trace-id" in h
        # trace-id should be a UUID-like string
        assert len(h["MPS-trace-id"]) == 36

    def test_timeout_returns_empty(self):
        handler = _make_handler()
        import requests

        handler.session.post = MagicMock(side_effect=requests.Timeout("timeout"))
        result = handler._call_asr(b"fake")
        assert result == ""

    def test_error_returns_empty(self):
        handler = _make_handler()

        handler.session.post = MagicMock(side_effect=ConnectionError("refused"))
        result = handler._call_asr(b"fake")
        assert result == ""

    def test_empty_asr_result(self):
        handler = _make_handler()

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"resultMap": {"asr": ""}}
        handler.session.post = MagicMock(return_value=resp)

        result = handler._call_asr(b"fake")
        assert result == ""


class TestProcess:
    def test_yields_text_and_language(self):
        handler = _make_handler()

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"resultMap": {"asr": "测试文本"}}
        handler.session.post = MagicMock(return_value=resp)

        audio = _make_audio(0.5)
        results = list(handler.process(audio))

        assert len(results) == 1
        assert results[0] == ("测试文本", "zh")

    def test_empty_asr_yields_nothing(self):
        handler = _make_handler()

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"resultMap": {"asr": "  "}}
        handler.session.post = MagicMock(return_value=resp)

        audio = _make_audio(0.5)
        results = list(handler.process(audio))
        assert results == []

    def test_non_array_input_yields_nothing(self):
        handler = _make_handler()
        results = list(handler.process("not an array"))
        assert results == []

    def test_custom_language_in_output(self):
        handler = _make_handler(language="en")

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"resultMap": {"asr": "hello"}}
        handler.session.post = MagicMock(return_value=resp)

        audio = _make_audio(0.5)
        results = list(handler.process(audio))
        assert results[0] == ("hello", "en")
