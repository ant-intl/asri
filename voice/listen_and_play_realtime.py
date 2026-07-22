import argparse
import asyncio
import base64
import json
import math
import os
import re
import time
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Event, Lock
from typing import Optional

from openai import AsyncOpenAI

_BRACKETS = re.compile(
    r'\([^)]*\)'           # ()
    r'|\[[^\]]*\]'          # []
    r'|\{[^{}]*\}'          # {}
    r'|（[^）]*）'           # fullwidth （）
    r'|【[^】]*】'           # 【】
    r'|《[^》]*》'           # 《》
    r'|「[^」]*」'           # 「」
    r'|『[^』]*』'           # 『』
)


def strip_brackets(text: str) -> str:
    return _BRACKETS.sub('', text)

@dataclass
class ListenAndPlayRealtimeArguments:
    host: str = field(
        default="127.0.0.1",
        metadata={"help": "Realtime server host. Default is 127.0.0.1."},
    )
    port: int = field(
        default=8765,
        metadata={"help": "Realtime server port. Default is 8765."},
    )
    model: str = field(
        default="local",
        metadata={"help": "Model name sent to the OpenAI-compatible realtime client."},
    )
    api_key: str = field(
        default="test-key",
        metadata={"help": "API key for the OpenAI SDK client. Local server ignores it."},
    )
    base_url: Optional[str] = field(
        default=None,
        metadata={"help": "Optional HTTP base URL, e.g. http://127.0.0.1:8765/v1"},
    )
    websocket_base_url: Optional[str] = field(
        default=None,
        metadata={"help": "Optional WS base URL, e.g. ws://127.0.0.1:8765/v1"},
    )
    send_rate: int = field(
        default=16000,
        metadata={"help": "Microphone sample rate in Hz. Default is 16000."},
    )
    recv_rate: int = field(
        default=16000,
        metadata={"help": "Speaker sample rate in Hz. Default is 16000."},
    )
    chunk_size: int = field(
        default=1024,
        metadata={"help": "Audio callback block size in samples. Default is 1024."},
    )
    input_device: Optional[int] = field(
        default=None,
        metadata={"help": "Optional sounddevice input device index."},
    )
    output_device: Optional[int] = field(
        default=None,
        metadata={"help": "Optional sounddevice output device index."},
    )
    instructions: Optional[str] = field(
        default=None,
        metadata={"help": "Optional session instructions to apply on connect."},
    )
    voice: Optional[str] = field(
        default=None,
        metadata={
            "help": (
                "TTS voice sent as session.audio.output.voice. "
                "Local Kokoro: e.g. bm_fable, af_heart, am_adam. "
                "OpenAI Realtime: e.g. marin, cedar, alloy."
            ),
        },
    )
    print_json: bool = field(
        default=False,
        metadata={"help": "Print raw event payloads in addition to friendly logs."},
    )
    block_mic_during_playback: bool = field(
        default=False,
        metadata={"help": "If set, pause microphone capture while speaker audio is playing. Disabled by default so barge-in works."},
    )
    endpoint: str = field(
        default="audio",
        metadata={"help": "Realtime endpoint type: 'audio' for /v1/realtime/audio (speech-to-speech) or 'text' for /v1/realtime/text (speech-to-text, no TTS). Default is 'audio'."},
    )
    audio_file: Optional[str] = field(
        default=None,
        metadata={"help": "Path to an audio file (WAV/PCM) to send instead of mic input. Chunks are sent at real-time pace to trigger VAD. Implies --endpoint text."},
    )
    speed: float = field(
        default=1.0,
        metadata={"help": "Playback speed multiplier for --audio-file mode. E.g. 2.0 sends audio at 2x real-time. Default is 1.0."},
    )

def _make_client(args: ListenAndPlayRealtimeArguments) -> AsyncOpenAI:
    base_url = args.base_url or f"http://{args.host}:{args.port}/v1"
    websocket_base_url = args.websocket_base_url or f"ws://{args.host}:{args.port}/v1"
    return AsyncOpenAI(
        api_key=args.api_key,
        base_url=base_url,
        websocket_base_url=websocket_base_url,
    )


def _build_session_update(args: ListenAndPlayRealtimeArguments) -> dict:
    def maybe_pcm_format(rate: int) -> Optional[dict]:
        # The OpenAI realtime Pydantic models only validate audio/pcm at 24 kHz.
        # Our local pipeline defaults to 16 kHz internally when format is omitted,
        # so omit the field for the common local case instead of sending an
        # invalid 16 kHz declaration.
        if rate == 16000:
            return None
        if rate == 24000:
            return {"type": "audio/pcm", "rate": 24000}
        raise ValueError(
            f"Unsupported rate {rate}. Use 16000 for the local pipeline default "
            f"or 24000 to match the OpenAI realtime audio format schema."
        )

    input_cfg = {}
    output_cfg = {}

    input_format = maybe_pcm_format(args.send_rate)
    output_format = maybe_pcm_format(args.recv_rate)
    if input_format is not None:
        input_cfg["format"] = input_format
    if output_format is not None:
        output_cfg["format"] = output_format
    if args.voice:
        output_cfg["voice"] = args.voice

    session = {
        "type": "realtime",
        "audio": {
            "input": input_cfg,
            "output": output_cfg,
        },
    }
    if args.instructions:
        session["instructions"] = args.instructions
    return {"type": "session.update", "session": session}


async def listen_and_play_realtime(args: ListenAndPlayRealtimeArguments) -> None:
    import sounddevice as sd

    client = _make_client(args)

    mic_queue: Queue[bytes] = Queue(maxsize=128)
    stop_event = Event()
    playback_buffer = bytearray()
    playback_lock = Lock()
    speaker_active_until = [0.0]
    partial_user_text = ""
    live_user_width = 0
    saw_user_speech = False

    def render_live_user_text(text: str, final: bool = False) -> None:
        nonlocal live_user_width
        line = f"USER: {text}"
        padded = line
        if live_user_width > len(line):
            padded += " " * (live_user_width - len(line))

        if final:
            print(f"\r{padded}", flush=True)
            live_user_width = 0
            return

        print(f"\r{padded}", end="", flush=True)
        live_user_width = len(line)

    def clear_live_user_text() -> None:
        nonlocal live_user_width
        if live_user_width == 0:
            return
        print("\r" + (" " * live_user_width) + "\r", end="", flush=True)
        live_user_width = 0

    def clear_playback_buffer() -> None:
        speaker_active_until[0] = 0.0
        with playback_lock:
            playback_buffer.clear()

    def callback_recv(outdata, _frames, _time_info, status):
        if status:
            print(f"Speaker status: {status}", flush=True)

        needed = len(outdata)
        with playback_lock:
            available = min(needed, len(playback_buffer))
            if available:
                outdata[:available] = playback_buffer[:available]
                del playback_buffer[:available]
            if available < needed:
                outdata[available:] = b"\x00" * (needed - available)

    def callback_send(indata, _frames, _time_info, status):
        if status:
            print(f"Mic status: {status}", flush=True)

        if args.block_mic_during_playback:
            with playback_lock:
                speaker_active = bool(playback_buffer)
            if speaker_active or time.monotonic() < speaker_active_until[0]:
                return

        try:
            mic_queue.put_nowait(bytes(indata))
        except Exception:
            pass

    async def send_audio(conn):
        while not stop_event.is_set():
            try:
                chunk = await asyncio.to_thread(mic_queue.get, True, 0.1)
            except Empty:
                continue

            await conn.send(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(chunk).decode("ascii"),
                }
            )

    async def receive_events(conn):
        nonlocal partial_user_text, saw_user_speech

        while not stop_event.is_set():
            event = await conn.recv()

            if args.print_json:
                try:
                    print(f"EVENT: {event.model_dump_json()}", flush=True)
                except Exception:
                    print(f"EVENT: {event}", flush=True)

            if event.type == "session.created":
                print("Connected.", flush=True)
            elif event.type == "input_audio_buffer.speech_started":
                clear_playback_buffer()
                partial_user_text = ""
                if saw_user_speech:
                    print("", flush=True)
                saw_user_speech = True
            elif event.type == "input_audio_buffer.speech_stopped":
                pass
            elif event.type == "conversation.item.input_audio_transcription.delta":
                # This server currently sends the latest partial hypothesis in
                # each "delta" event rather than a token-level suffix, so render
                # the newest snapshot instead of concatenating repeated text.
                partial_user_text = event.delta.strip()
                if partial_user_text:
                    render_live_user_text(partial_user_text)
            elif event.type == "conversation.item.input_audio_transcription.completed":
                partial_user_text = ""
                render_live_user_text(event.transcript.strip(), final=True)
            elif event.type == "response.created":
                clear_live_user_text()
                print("ASSISTANT: ", end="", flush=True)
            elif event.type == "response.output_audio.delta":
                audio = base64.b64decode(event.delta)
                with playback_lock:
                    playback_buffer.extend(audio)
                speaker_active_until[0] = time.monotonic() + max(0.15, len(audio) / (2 * args.recv_rate))
            elif event.type == "response.output_audio.done":
                pass
            elif event.type == "response.output_audio_transcript.done":
                print(event.transcript, end="", flush=True)
            elif event.type == "response.function_call_arguments.done":
                tool_name = event.name
                tool_call_id = event.call_id
                tool_args_str = event.arguments
                print(
                    f"\nTOOL CALL: {tool_name}(call_id={tool_call_id}, args={tool_args_str})",
                    flush=True,
                )
            elif event.type == "response.done":
                if event.response.status == "cancelled":
                    clear_playback_buffer()
                print("", flush=True)
            elif event.type == "error":
                clear_live_user_text()
                print(f"ERROR: {event.error.type}: {event.error.message}", flush=True)
            elif event.type not in ("llm_metrics", "response.tool_result", "tool_result"):
                clear_live_user_text()
                print(f"EVENT: {event.type}", flush=True)

    async def wait_for_stop():
        await asyncio.to_thread(input, "Press Enter to stop...\n")
        stop_event.set()

    input_stream = sd.RawInputStream(
        samplerate=args.send_rate,
        channels=1,
        dtype="int16",
        blocksize=args.chunk_size,
        callback=callback_send,
        device=args.input_device,
    )
    output_stream = sd.RawOutputStream(
        samplerate=args.recv_rate,
        channels=1,
        dtype="int16",
        blocksize=args.chunk_size,
        callback=callback_recv,
        device=args.output_device,
    )

    input_stream.start()
    output_stream.start()

    try:
        async with client.realtime.connect(model=args.model) as conn:
            await conn.send(_build_session_update(args))

            sender_task = asyncio.create_task(send_audio(conn))
            receiver_task = asyncio.create_task(receive_events(conn))
            stopper_task = asyncio.create_task(wait_for_stop())

            done, pending = await asyncio.wait(
                {sender_task, receiver_task, stopper_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            stop_event.set()
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

            for task in done:
                exc = task.exception()
                if exc is not None:
                    raise exc
    finally:
        stop_event.set()
        clear_live_user_text()
        input_stream.stop()
        output_stream.stop()
        input_stream.close()
        output_stream.close()


async def listen_text_only(args: ListenAndPlayRealtimeArguments) -> None:
    """Text-only mode: mic input → /v1/realtime/text → print LLM text (no speaker)."""
    import sounddevice as sd
    import websockets

    ws_base = args.websocket_base_url or f"ws://{args.host}:{args.port}/v1"
    ws_url = f"{ws_base}/realtime/text"

    mic_queue: Queue[bytes] = Queue(maxsize=128)
    stop_event = Event()
    partial_user_text = ""
    live_user_width = 0
    saw_user_speech = False

    def render_live_user_text(text: str, final: bool = False) -> None:
        nonlocal live_user_width
        line = f"USER: {text}"
        padded = line
        if live_user_width > len(line):
            padded += " " * (live_user_width - len(line))
        if final:
            print(f"\r{padded}", flush=True)
            live_user_width = 0
            return
        print(f"\r{padded}", end="", flush=True)
        live_user_width = len(line)

    def clear_live_user_text() -> None:
        nonlocal live_user_width
        if live_user_width == 0:
            return
        print("\r" + (" " * live_user_width) + "\r", end="", flush=True)
        live_user_width = 0

    def callback_send(indata, _frames, _time_info, status):
        if status:
            print(f"Mic status: {status}", flush=True)
        try:
            mic_queue.put_nowait(bytes(indata))
        except Exception:
            pass

    async def send_audio(ws):
        while not stop_event.is_set():
            try:
                chunk = await asyncio.to_thread(mic_queue.get, True, 0.1)
            except Empty:
                continue
            msg = json.dumps({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(chunk).decode("ascii"),
            })
            await ws.send(msg)

    async def receive_events(ws):
        nonlocal partial_user_text, saw_user_speech
        in_assistant_response = False

        async for raw in ws:
            if stop_event.is_set():
                break
            event = json.loads(raw)
            etype = event.get("type", "")

            if args.print_json:
                print(f"EVENT: {json.dumps(event, ensure_ascii=False)}", flush=True)

            if etype == "session.created":
                print("Connected (text-only mode).", flush=True)
            elif etype == "input_audio_buffer.speech_started":
                partial_user_text = ""
                if in_assistant_response:
                    print("", flush=True)
                    in_assistant_response = False
                if saw_user_speech:
                    print("", flush=True)
                saw_user_speech = True
            elif etype == "conversation.item.input_audio_transcription.delta":
                partial_user_text = event.get("delta", "").strip()
                if partial_user_text:
                    render_live_user_text(partial_user_text)
            elif etype == "conversation.item.input_audio_transcription.completed":
                partial_user_text = ""
                render_live_user_text(event.get("transcript", "").strip(), final=True)
            elif etype == "response.created":
                clear_live_user_text()
                print("ASSISTANT: ", end="", flush=True)
                in_assistant_response = True
            elif etype == "response.output_audio_transcript.done":
                # Stream each text fragment inline
                print(event.get("transcript", ""), end="", flush=True)
            elif etype == "response.function_call_arguments.done":
                tool_name = event.get("name", "")
                tool_call_id = event.get("call_id", "")
                tool_args_str = event.get("arguments", "")
                print(f"\nTOOL CALL: {tool_name}(call_id={tool_call_id}, args={tool_args_str})", flush=True)
            elif etype == "response.done":
                if in_assistant_response:
                    print("", flush=True)
                    in_assistant_response = False
            elif etype == "error":
                clear_live_user_text()
                if in_assistant_response:
                    print("", flush=True)
                    in_assistant_response = False
                err = event.get("error", {})
                print(f"ERROR: {err.get('type')}: {err.get('message')}", flush=True)

    async def wait_for_stop():
        await asyncio.to_thread(input, "Press Enter to stop...\n")
        stop_event.set()

    input_stream = sd.RawInputStream(
        samplerate=args.send_rate,
        channels=1,
        dtype="int16",
        blocksize=args.chunk_size,
        callback=callback_send,
        device=args.input_device,
    )
    input_stream.start()

    try:
        async with websockets.connect(ws_url) as ws:
            # Send session config
            session_update = _build_session_update(args)
            await ws.send(json.dumps(session_update))

            sender_task = asyncio.create_task(send_audio(ws))
            receiver_task = asyncio.create_task(receive_events(ws))
            stopper_task = asyncio.create_task(wait_for_stop())

            done, pending = await asyncio.wait(
                {sender_task, receiver_task, stopper_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            stop_event.set()
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exc = task.exception()
                if exc is not None:
                    raise exc
    finally:
        stop_event.set()
        clear_live_user_text()
        input_stream.stop()
        input_stream.close()


def _load_audio_file(path: str, target_rate: int) -> bytes:
    """Load an audio file and return raw int16 PCM bytes at target_rate."""
    import subprocess
    import os

    if not os.path.isfile(path):
        raise FileNotFoundError(f"Audio file not found: {path}")

    # Use ffmpeg to convert any audio format to int16 PCM at target_rate
    cmd = [
        "ffmpeg", "-i", path,
        "-f", "s16le", "-acodec", "pcm_s16le",
        "-ar", str(target_rate), "-ac", "1",
        "-v", "quiet",
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()}")
    return result.stdout


async def send_audio_file(args: ListenAndPlayRealtimeArguments) -> None:
    """File mode: send audio file through /v1/realtime/text at real-time pace, print responses."""
    import websockets

    ws_base = args.websocket_base_url or f"ws://{args.host}:{args.port}/v1"
    ws_url = f"{ws_base}/realtime/text"

    pcm_data = _load_audio_file(args.audio_file, args.send_rate)
    total_samples = len(pcm_data) // 2  # int16 = 2 bytes per sample
    duration = total_samples / args.send_rate
    print(f"Audio: {args.audio_file} ({duration:.1f}s, {args.send_rate}Hz, {total_samples} samples)")

    chunk_bytes = args.chunk_size * 2  # int16 = 2 bytes per sample
    chunk_duration = args.chunk_size / args.send_rate  # seconds per chunk
    send_interval = chunk_duration / args.speed

    stop_event = Event()
    assistant_text_parts: list[str] = []
    transcription = ""
    response_done_event = asyncio.Event()

    async def send_audio(ws):
        offset = 0
        while offset < len(pcm_data) and not stop_event.is_set():
            chunk = pcm_data[offset:offset + chunk_bytes]
            offset += chunk_bytes
            msg = json.dumps({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(chunk).decode("ascii"),
            })
            await ws.send(msg)
            await asyncio.sleep(send_interval)
        print(f"Audio file sent ({offset // 2} samples)")

        # Append 1s of silence so VAD detects end-of-speech
        silence_samples = args.send_rate  # 1 second
        silence = b"\x00" * (silence_samples * 2)
        for sil_offset in range(0, len(silence), chunk_bytes):
            chunk = silence[sil_offset:sil_offset + chunk_bytes]
            msg = json.dumps({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(chunk).decode("ascii"),
            })
            await ws.send(msg)
            await asyncio.sleep(send_interval)

    async def receive_events(ws):
        nonlocal transcription
        in_assistant_response = False

        async for raw in ws:
            if stop_event.is_set():
                break
            event = json.loads(raw)
            etype = event.get("type", "")

            if args.print_json:
                print(f"EVENT: {json.dumps(event, ensure_ascii=False)}", flush=True)

            if etype == "session.created":
                print("Connected (file mode).", flush=True)
            elif etype == "conversation.item.input_audio_transcription.completed":
                transcription = event.get("transcript", "").strip()
                print(f"USER: {transcription}", flush=True)
            elif etype == "response.created":
                in_assistant_response = True
            elif etype == "response.output_audio_transcript.done":
                text = event.get("transcript", "")
                if text:
                    assistant_text_parts.append(strip_brackets(text))
            elif etype == "response.function_call_arguments.done":
                tool_name = event.get("name", "")
                tool_call_id = event.get("call_id", "")
                tool_args_str = event.get("arguments", "")
                print(f"TOOL CALL: {tool_name}(call_id={tool_call_id}, args={tool_args_str})", flush=True)
            elif etype == "response.done":
                if in_assistant_response:
                    in_assistant_response = False
                    response_done_event.set()
            elif etype == "error":
                err = event.get("error", {})
                print(f"ERROR: {err.get('type')}: {err.get('message')}", flush=True)
                response_done_event.set()

    try:
        async with websockets.connect(ws_url) as ws:
            session_update = _build_session_update(args)
            await ws.send(json.dumps(session_update))

            receiver_task = asyncio.create_task(receive_events(ws))
            await send_audio(ws)

            # Wait for LLM response to complete (timeout after 30s of silence)
            try:
                await asyncio.wait_for(response_done_event.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                print("Timeout waiting for response.", flush=True)

            stop_event.set()
            receiver_task.cancel()
            try:
                await receiver_task
            except asyncio.CancelledError:
                pass

        full_response = "".join(assistant_text_parts)
        print(f"ASSISTANT: {full_response}", flush=True)

    except Exception as e:
        print(f"Error: {e}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Talk to the local OpenAI-compatible realtime speech pipeline.")
    defaults = ListenAndPlayRealtimeArguments()
    parser.add_argument("--host", default=defaults.host)
    parser.add_argument("--port", type=int, default=defaults.port)
    parser.add_argument("--model", default=defaults.model)
    parser.add_argument("--api-key", default=defaults.api_key)
    parser.add_argument("--base-url", default=defaults.base_url)
    parser.add_argument("--websocket-base-url", default=defaults.websocket_base_url)
    parser.add_argument("--send-rate", type=int, default=defaults.send_rate)
    parser.add_argument("--recv-rate", type=int, default=defaults.recv_rate)
    parser.add_argument("--chunk-size", type=int, default=defaults.chunk_size)
    parser.add_argument("--input-device", type=int, default=defaults.input_device)
    parser.add_argument("--output-device", type=int, default=defaults.output_device)
    parser.add_argument("--instructions", default=defaults.instructions)
    parser.add_argument(
        "--voice",
        default=defaults.voice,
        help=(
            "session.audio.output.voice (Kokoro id like bm_fable, or OpenAI name like marin)."
        ),
    )
    parser.add_argument("--print-json", action="store_true", default=defaults.print_json)
    parser.add_argument(
        "--block-mic-during-playback",
        action="store_true",
        default=defaults.block_mic_during_playback,
    )
    parser.add_argument(
        "--endpoint",
        default=defaults.endpoint,
        choices=["audio", "text"],
        help="Endpoint type: 'audio' for speech-to-speech (/v1/realtime/audio), 'text' for speech-to-text (/v1/realtime/text). Default is 'audio'.",
    )
    parser.add_argument(
        "--audio-file",
        default=defaults.audio_file,
        help="Path to an audio file to send instead of mic input. Implies --endpoint text.",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=defaults.speed,
        help="Playback speed for --audio-file mode (e.g. 2.0 = 2x real-time). Default is 1.0.",
    )
    namespace = parser.parse_args()
    args = ListenAndPlayRealtimeArguments(
        host=namespace.host,
        port=namespace.port,
        model=namespace.model,
        api_key=namespace.api_key,
        base_url=namespace.base_url,
        websocket_base_url=namespace.websocket_base_url,
        send_rate=namespace.send_rate,
        recv_rate=namespace.recv_rate,
        chunk_size=namespace.chunk_size,
        input_device=namespace.input_device,
        output_device=namespace.output_device,
        instructions=namespace.instructions,
        voice=namespace.voice,
        print_json=namespace.print_json,
        block_mic_during_playback=namespace.block_mic_during_playback,
        endpoint=namespace.endpoint,
        audio_file=namespace.audio_file,
        speed=namespace.speed,
    )
    try:
        if args.audio_file:
            asyncio.run(send_audio_file(args))
        elif args.endpoint == "text":
            asyncio.run(listen_text_only(args))
        else:
            asyncio.run(listen_and_play_realtime(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
