from dataclasses import dataclass, field


@dataclass
class VADHandlerArguments:
    thresh: float = field(
        default=0.3,
        metadata={"help": "The threshold value for voice activity detection (VAD). Default is 0.3."},
    )
    sample_rate: int = field(
        default=16000,
        metadata={"help": "The sample rate of the audio in Hertz. Default is 16000 Hz."},
    )
    min_silence_ms: int = field(
        default=300,
        metadata={"help": "Minimum length of silence intervals in milliseconds. Default is 300 ms."},
    )
    min_speech_ms: int = field(
        default=500,
        metadata={"help": "Minimum length of speech segments in milliseconds. Default is 500 ms."},
    )
    max_speech_ms: float = field(
        default=float("inf"),
        metadata={"help": "Maximum length of continuous speech before forcing a split. Default is infinite."},
    )
    speech_pad_ms: int = field(
        default=500,
        metadata={"help": "Padding added to speech segments in milliseconds. Default is 500 ms."},
    )
    audio_enhancement: bool = field(
        default=False,
        metadata={"help": "Enable audio enhancement (noise reduction, etc.). Default is False."},
    )
    enable_realtime_transcription: bool = field(
        default=False,
        metadata={"help": "Enable progressive audio release for live transcription. Default is False."},
    )
    realtime_processing_pause: float = field(
        default=0.2,
        metadata={"help": "Interval for releasing progressive audio chunks. Default is 0.2s."},
    )
    enable_vadasr: bool = field(
        default=False,
        metadata={"help": "Enable VADASR mode: forward progressive audio to main STT during speech, send TURN_END at end. Default is False."},
    )
