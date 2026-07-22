"""Client helpers for vLLM Omni OpenAI-compatible TTS endpoints."""

from __future__ import annotations

import base64
import mimetypes
import subprocess
from pathlib import Path
from typing import Any

import requests


def ref_audio_payload(ref_audio: str | None) -> str | None:
    """Return a value accepted by vLLM Omni ref_audio fields."""
    if not ref_audio:
        return None
    if ref_audio.startswith(("http://", "https://", "file://", "data:")):
        return ref_audio
    ref_path = Path(ref_audio).expanduser()
    if not ref_path.exists():
        raise FileNotFoundError(f"TTS reference audio not found: {ref_path}")
    encoded = base64.b64encode(ref_path.read_bytes()).decode("ascii")
    return f"data:audio/wav;base64,{encoded}"


def decode_audio_to_pcm(audio: bytes, target_rate: int, input_label: str = "audio") -> bytes:
    """Decode any ffmpeg-supported audio payload to mono int16 PCM."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "-ac",
        "1",
        "-ar",
        str(target_rate),
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            input=audio,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"ffmpeg failed to decode {input_label}: {stderr}") from exc
    return proc.stdout


class VLLMOmniTTSClient:
    """Small OpenAI-compatible speech client for vLLM Omni TTS services."""

    def __init__(
        self,
        base_url: str,
        model: str = "openbmb/VoxCPM2",
        voice: str = "customer_female_7_omnivoice",
        api_key: str | None = None,
        timeout: float = 60.0,
        target_sample_rate: int = 16000,
        label: str = "vLLM Omni TTS",
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.voice = voice
        self.timeout = timeout
        self.target_sample_rate = target_sample_rate
        self.label = label
        self.session = session or requests.Session()
        self.session.headers.update({"Connection": "keep-alive"})
        if api_key:
            self.session.headers.update({"Authorization": f"Bearer {api_key}"})

    @property
    def speech_url(self) -> str:
        return f"{self.base_url}/v1/audio/speech"

    @property
    def voices_url(self) -> str:
        return f"{self.base_url}/v1/audio/voices"

    def list_voices(self) -> list[str]:
        resp = self.session.get(self.voices_url, timeout=self.timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"{self.label} voices request failed ({resp.status_code}): {resp.text[:500]}")
        data = resp.json()
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            voices = []
            for item in data["data"]:
                if isinstance(item, str):
                    voices.append(item)
                elif isinstance(item, dict):
                    voice_id = item.get("id") or item.get("name") or item.get("voice")
                    if voice_id:
                        voices.append(str(voice_id))
            return voices
        if isinstance(data, dict) and isinstance(data.get("voices"), list):
            return [str(item) for item in data["voices"]]
        if isinstance(data, list):
            return [str(item) for item in data]
        return []

    def upload_voice(
        self,
        *,
        name: str,
        audio_sample: str,
        consent: str,
        ref_text: str | None = None,
        speaker_description: str | None = None,
    ) -> dict[str, Any]:
        audio_path = Path(audio_sample).expanduser()
        if not audio_path.exists():
            raise FileNotFoundError(f"TTS voice sample not found: {audio_path}")
        content_type = mimetypes.guess_type(str(audio_path))[0] or "audio/wav"
        data = {"name": name, "consent": consent}
        if ref_text:
            data["ref_text"] = ref_text
        if speaker_description:
            data["speaker_description"] = speaker_description
        with audio_path.open("rb") as f:
            files = {"audio_sample": (audio_path.name, f, content_type)}
            resp = self.session.post(self.voices_url, data=data, files=files, timeout=self.timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"{self.label} voice upload failed ({resp.status_code}): {resp.text[:500]}")
        return resp.json()

    def build_payload(
        self,
        text: str,
        *,
        response_format: str = "wav",
        speed: float | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "voice": self.voice,
            "input": text,
            "response_format": response_format,
            "stream": False,
        }
        if speed is not None:
            payload["speed"] = speed
        if extra_body:
            payload.update({k: v for k, v in extra_body.items() if v is not None})
        return payload

    def synthesize_wav(
        self,
        text: str,
        *,
        speed: float | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> bytes:
        payload = self.build_payload(text, response_format="wav", speed=speed, extra_body=extra_body)
        resp = self.session.post(self.speech_url, json=payload, timeout=self.timeout, stream=False)
        if resp.status_code != 200:
            raise RuntimeError(f"{self.label} request failed ({resp.status_code}): {resp.text[:500]}")
        content_type = resp.headers.get("content-type", "")
        data = resp.content
        if "json" in content_type.lower():
            raise RuntimeError(f"{self.label} returned JSON instead of audio: {data.decode(errors='replace')}")
        return data

    def synthesize_pcm(
        self,
        text: str,
        *,
        speed: float | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> bytes:
        wav = self.synthesize_wav(text, speed=speed, extra_body=extra_body)
        return decode_audio_to_pcm(wav, self.target_sample_rate, f"{self.label} wav")

    def stream_pcm_bytes(
        self,
        text: str,
        *,
        speed: float | None = None,
        extra_body: dict[str, Any] | None = None,
        chunk_size: int = 4096,
        idle_timeout: float | None = None,
    ):
        """Yield raw PCM byte chunks from a streaming Speech API response."""
        payload = self.build_payload(text, response_format="pcm", speed=speed, extra_body=extra_body)
        payload["stream"] = True
        payload["stream_format"] = "audio"
        timeout = self.timeout
        if idle_timeout and idle_timeout > 0:
            timeout = (min(float(self.timeout), 10.0), float(idle_timeout))
        resp = self.session.post(self.speech_url, json=payload, timeout=timeout, stream=True)
        try:
            if resp.status_code != 200:
                raise RuntimeError(f"{self.label} streaming request failed ({resp.status_code}): {resp.text[:500]}")
            content_type = resp.headers.get("content-type", "")
            if "json" in content_type.lower():
                data = resp.content
                raise RuntimeError(f"{self.label} returned JSON instead of streaming audio: {data.decode(errors='replace')}")
            got_audio = False
            try:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if chunk:
                        got_audio = True
                        yield chunk
            except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
                if got_audio and idle_timeout and idle_timeout > 0:
                    return
                raise
        finally:
            resp.close()
