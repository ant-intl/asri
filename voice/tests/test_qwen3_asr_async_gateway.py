import asyncio
from types import SimpleNamespace

import numpy as np

from services.asr_streaming_service.async_gateway import AsyncQwen3ASRGateway


class _Tokenizer:
    def encode(self, text):
        return [ord(ch) for ch in text]

    def decode(self, ids):
        return "".join(chr(i) for i in ids)


class _Processor:
    tokenizer = _Tokenizer()

    def apply_chat_template(self, messages, add_generation_prompt=True, tokenize=False):
        return "<prompt>"


class _FakeEngine:
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.calls = []
        self.lock = asyncio.Lock()

    async def generate(self, inputs, sampling_params, request_id):
        async with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append(request_id)
        try:
            await asyncio.sleep(0.03)
            yield SimpleNamespace(outputs=[SimpleNamespace(text=f"text-{request_id[-4:]}")])
        finally:
            async with self.lock:
                self.active -= 1


def _parse(raw, user_language=None):
    return (user_language or "zh", raw)


def _gateway(engine=None):
    return AsyncQwen3ASRGateway(
        engine=engine or _FakeEngine(),
        processor=_Processor(),
        sampling_params=object(),
        parse_asr_output=_parse,
        unfixed_chunk_num=999,
        unfixed_token_num=5,
        chunk_size_sec=0.001,
    )


async def test_async_gateway_allows_parallel_decodes_across_sessions():
    engine = _FakeEngine()
    gateway = _gateway(engine)
    s1 = await gateway.start_session()
    s2 = await gateway.start_session()
    chunk = np.zeros(gateway.chunk_size_samples, dtype=np.float32)

    r1, r2 = await asyncio.gather(
        gateway.submit_chunk(s1, chunk),
        gateway.submit_chunk(s2, chunk),
    )

    assert r1["text"].startswith("text-")
    assert r2["text"].startswith("text-")
    assert engine.max_active == 2


async def test_async_gateway_serializes_decodes_within_one_session():
    engine = _FakeEngine()
    gateway = _gateway(engine)
    session_id = await gateway.start_session()
    chunk = np.zeros(gateway.chunk_size_samples, dtype=np.float32)

    await asyncio.gather(
        gateway.submit_chunk(session_id, chunk),
        gateway.submit_chunk(session_id, chunk),
    )

    assert engine.max_active == 1
    assert len(engine.calls) == 2


async def test_async_gateway_finish_flushes_tail_and_removes_session():
    engine = _FakeEngine()
    gateway = _gateway(engine)
    session_id = await gateway.start_session(language="Chinese")
    tail = np.zeros(gateway.chunk_size_samples // 2, dtype=np.float32)

    assert (await gateway.submit_chunk(session_id, tail)) == {"language": "", "text": ""}
    final = await gateway.finish_session(session_id)

    assert final["language"] == "Chinese"
    assert final["text"].startswith("text-")
    assert session_id not in gateway.sessions
