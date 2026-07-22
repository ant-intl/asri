import threading
import sounddevice as sd
import numpy as np

import time
import logging

logger = logging.getLogger(__name__)


class LocalAudioStreamer:
    def __init__(
        self,
        input_queue,
        output_queue,
        list_play_chunk_size=512,
        enable_barge_in=False,
        should_listen=None,
        runtime_config=None,
        input_device=None,
        output_device=None,
    ):
        self.list_play_chunk_size = list_play_chunk_size

        self.stop_event = threading.Event()
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.enable_barge_in = enable_barge_in
        self.should_listen = should_listen
        self.runtime_config = runtime_config
        self.input_device = input_device
        self.output_device = output_device

    def run(self):
        dither = np.random.randint(
            -1, 2, size=(self.list_play_chunk_size, 1), dtype=np.int16
        )

        enable_barge_in = self.enable_barge_in
        should_listen = self.should_listen
        runtime_config = self.runtime_config

        def callback(indata, outdata, frames, time, status):
            if self.stop_event.is_set():
                outdata[:] = 0 * outdata
                return

            if self.output_queue.empty():
                self.input_queue.put(indata.copy())
                outdata[:] = dither
            else:
                # Always record mic when barge-in is enabled
                if enable_barge_in:
                    self.input_queue.put(indata.copy())
                try:
                    audio_chunk = self.output_queue.get_nowait()
                    if isinstance(audio_chunk, bytes) and audio_chunk == b"__RESPONSE_DONE__":
                        # All audio for this response has been played
                        if should_listen is not None and not runtime_config:
                            should_listen.set()
                        outdata[:] = dither
                    elif isinstance(audio_chunk, np.ndarray):
                        outdata[:] = audio_chunk[:, np.newaxis]
                    else:
                        outdata[:] = 0 * outdata
                except Exception:
                    outdata[:] = 0 * outdata

        # Resolve device IDs to names for logging
        in_dev = self.input_device
        out_dev = self.output_device
        if in_dev is None and out_dev is None:
            in_dev = sd.default.device[0]
            out_dev = sd.default.device[1]
        elif in_dev is None:
            in_dev = sd.default.device[0]
        elif out_dev is None:
            out_dev = sd.default.device[1]

        try:
            in_name = sd.query_devices(in_dev)["name"]
        except Exception:
            in_name = f"device #{in_dev}"
        try:
            out_name = sd.query_devices(out_dev)["name"]
        except Exception:
            out_name = f"device #{out_dev}"

        logger.info("Audio devices: input=%s (#%s), output=%s (#%s)",
                     in_name, in_dev, out_name, out_dev)

        stream_device = (self.input_device, self.output_device) if (
            self.input_device is not None or self.output_device is not None
        ) else None

        with sd.Stream(
            samplerate=16000,
            dtype="int16",
            channels=1,
            callback=callback,
            blocksize=self.list_play_chunk_size,
            device=stream_device,
        ):
            logger.info("Starting local audio stream (barge_in=%s)", enable_barge_in)
            while not self.stop_event.is_set():
                time.sleep(0.001)
            print("Stopping recording")
