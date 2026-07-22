import numpy as np
import requests

from handlers.tts.qwen3_tts_streaming_handler import Qwen3TTSStreamingHandler
from handlers.tts.vllm_omni_tts_client import VLLMOmniTTSClient
from pipeline.cancel_scope import CancelScope


class _FakeClient:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    def stream_pcm_bytes(self, text, **kwargs):
        self.calls.append((text, kwargs))
        for chunk in self.chunks:
            yield chunk


def _make_handler(source_rate=16000, sample_rate=16000, blocksize=4):
    handler = object.__new__(Qwen3TTSStreamingHandler)
    handler.client = _FakeClient([])
    handler.cancel_scope = None
    handler.speed = 1.0
    handler.streaming_send_speed = False
    handler.streaming_network_chunk_bytes = 1024
    handler.streaming_idle_timeout = 3.0
    handler.streaming_source_sample_rate = source_rate
    handler.sample_rate = sample_rate
    handler.blocksize = blocksize
    handler.task_type = "Base"
    handler.language = "Auto"
    handler.instructions = None
    handler.use_ref_audio_each_request = False
    handler.ref_audio = None
    handler.ref_text = None
    return handler


def test_qwen3_tts_streaming_yields_blocks_from_streamed_pcm():
    pcm = np.arange(10, dtype=np.int16).tobytes()
    handler = _make_handler(blocksize=4)
    handler.client = _FakeClient([pcm[:6], pcm[6:]])

    chunks = list(handler.process(("hello", "en", 1)))

    assert [chunk.tolist() for chunk in chunks] == [
        [0, 1, 2, 3],
        [4, 5, 6, 7],
        [8, 9, 0, 0],
    ]
    text, kwargs = handler.client.calls[0]
    assert text == "hello"
    assert kwargs["speed"] is None
    assert kwargs["extra_body"] == {"task_type": "Base", "language": "Auto"}


def test_qwen3_tts_streaming_cancel_drops_late_audio_chunks():
    first = np.arange(4, dtype=np.int16).tobytes()
    late_old = np.arange(100, 104, dtype=np.int16).tobytes()
    scope = CancelScope()
    handler = _make_handler(blocksize=4)
    handler.cancel_scope = scope
    handler.client = _FakeClient([first, late_old])

    stream = handler.process(("old answer", "zh", 0))

    assert next(stream).tolist() == [0, 1, 2, 3]
    scope.cancel()

    assert list(stream) == []


def test_vllm_omni_client_streaming_payload_sets_audio_pcm_flags():
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/octet-stream"}
        closed = False

        def iter_content(self, chunk_size=4096):
            yield b"\x01\x00\x02\x00"

        def close(self):
            self.closed = True

    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.payload = None
            self.response = FakeResponse()

        def post(self, _url, json, timeout, stream):
            self.payload = json
            self.timeout = timeout
            self.stream = stream
            return self.response

    session = FakeSession()
    client = VLLMOmniTTSClient(
        base_url="http://tts.test",
        model="model",
        voice="voice",
        session=session,
    )

    assert list(client.stream_pcm_bytes("hi", extra_body={"task_type": "Base"})) == [b"\x01\x00\x02\x00"]
    assert session.stream is True
    assert session.payload["stream"] is True
    assert session.payload["stream_format"] == "audio"
    assert session.payload["response_format"] == "pcm"
    assert session.payload["task_type"] == "Base"
    assert session.response.closed is True


def test_vllm_omni_client_streaming_response_closes_when_generator_closes():
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/octet-stream"}

        def __init__(self):
            self.closed = False

        def iter_content(self, chunk_size=4096):
            yield b"\x01\x00"
            yield b"\x02\x00"

        def close(self):
            self.closed = True

    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.response = FakeResponse()

        def post(self, _url, json, timeout, stream):
            return self.response

    session = FakeSession()
    client = VLLMOmniTTSClient(base_url="http://tts.test", session=session)
    gen = client.stream_pcm_bytes("hi")

    assert next(gen) == b"\x01\x00"
    gen.close()
    assert session.response.closed is True


def test_vllm_omni_client_streaming_idle_after_audio_is_clean_end():
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/octet-stream"}

        def __init__(self):
            self.closed = False

        def iter_content(self, chunk_size=4096):
            yield b"\x01\x00"
            raise requests.exceptions.ReadTimeout("idle")

        def close(self):
            self.closed = True

    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.response = FakeResponse()
            self.timeout = None

        def post(self, _url, json, timeout, stream):
            self.timeout = timeout
            return self.response

    session = FakeSession()
    client = VLLMOmniTTSClient(base_url="http://tts.test", timeout=120.0, session=session)

    assert list(client.stream_pcm_bytes("hi", idle_timeout=3.0)) == [b"\x01\x00"]
    assert session.timeout == (10.0, 3.0)
    assert session.response.closed is True
