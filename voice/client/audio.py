"""Audio loading helpers for client-side replay.

The replay client feeds pre-recorded PCM into the realtime server's
WebSocket endpoint.  These helpers wrap ``ffmpeg`` so any common audio
format can be converted to mono int16 PCM at the target sample rate.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def load_audio_pcm(audio_path: str | Path, target_rate: int = 16000) -> bytes:
    """Load any ffmpeg-supported audio file as mono int16 PCM.

    Parameters
    ----------
    audio_path:
        Path to the audio file (wav, mp3, flac, etc.).
    target_rate:
        Target sample rate in Hz.  Defaults to 16000, which matches the
        realtime server's input expectation.

    Returns
    -------
    bytes
        Raw PCM data (int16, mono, little-endian).

    Raises
    ------
    FileNotFoundError
        If ``audio_path`` does not exist.
    subprocess.CalledProcessError
        If ``ffmpeg`` fails to decode the file.
    """
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(path),
        "-f", "s16le",
        "-ac", "1",
        "-ar", str(target_rate),
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True, check=True)
    return result.stdout
