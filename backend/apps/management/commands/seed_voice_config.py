"""
Seed default VoiceAgentConfig from voice/configs/asri-voice.yaml.

Usage:
    python3 manage.py seed_voice_config

Idempotent — safe to run multiple times. Creates or updates the default
VoiceAgentConfig for the 'default' tenant based on the YAML config file.
"""
import logging
import os
from pathlib import Path

import yaml
from django.core.management.base import BaseCommand

from apps.entities import VoiceAgentConfig

logger = logging.getLogger(__name__)

DEFAULT_TENANT_ID = "default"
DEFAULT_CONFIG_NAME = "default"


class Command(BaseCommand):
    help = "Seed default VoiceAgentConfig from voice/configs/asri-voice.yaml"

    def handle(self, *args, **options):
        # Locate the YAML config file
        project_root = Path(__file__).resolve().parents[4]
        yaml_path = project_root / "voice" / "configs" / "asri-voice.yaml"

        if not yaml_path.exists():
            self.stderr.write(self.style.ERROR(f"YAML config not found: {yaml_path}"))
            return

        with open(yaml_path, "r", encoding="utf-8") as f:
            yaml_cfg = yaml.safe_load(f)

        # Parse voice_settings from YAML structure
        voice_settings = self._parse_yaml_to_voice_settings(yaml_cfg)

        # Create or update default VoiceAgentConfig
        config, created = VoiceAgentConfig.objects.get_or_create(
            tenant_id=DEFAULT_TENANT_ID,
            name=DEFAULT_CONFIG_NAME,
            defaults={
                "is_active": True,
                "voice_settings": voice_settings,
            },
        )

        if created:
            self.stdout.write(self.style.SUCCESS(
                f"Created VoiceAgentConfig '{config.name}' with settings from {yaml_path.name}"
            ))
        else:
            # Do NOT overwrite existing config — user may have customized via frontend.
            # Only merge fields that are missing (None or empty) from the YAML seed.
            merged = self._merge_missing(config.voice_settings or {}, voice_settings)
            if merged != config.voice_settings:
                config.voice_settings = merged
                config.save()
                self.stdout.write(self.style.SUCCESS(
                    f"Merged missing fields into VoiceAgentConfig '{config.name}' from {yaml_path.name}"
                ))
            else:
                self.stdout.write(
                    f"VoiceAgentConfig '{config.name}' already exists, skipping."
                )

        self.stdout.write(f"  voice_settings: {voice_settings}")

    def _parse_yaml_to_voice_settings(self, yaml_cfg: dict) -> dict:
        """Parse asri-voice.yaml structure into voice_settings dict."""
        settings = {}

        # STT config
        stt_backend = yaml_cfg.get("stt", "vadasr")
        stt_config = {"backend": stt_backend}
        # STT-specific fields are under stt_config
        stt_yaml = yaml_cfg.get("stt_config", {})
        for key in ("vadasr_asr_backend", "vadasr_url", "vadasr_timeout",
                     "vadasr_block_duration_ms"):
            if key in stt_yaml:
                stt_config[key] = stt_yaml[key]
        settings["stt"] = stt_config

        # TTS config
        tts_backend = yaml_cfg.get("tts", "omnivoice")
        tts_config = {"backend": tts_backend}
        # TTS-specific fields are under tts_config
        tts_yaml = yaml_cfg.get("tts_config", {})
        # Map omnivoice_tts_base_url → base_url, omnivoice_tts_num_step → num_step
        prefix = f"{tts_backend}_tts_"
        for key, val in tts_yaml.items():
            if key.startswith(prefix):
                mapped = key[len(prefix):]
                tts_config[mapped] = val
            else:
                tts_config[key] = val
        settings["tts"] = tts_config

        # VAD config
        vad_config = yaml_cfg.get("vad_config", {})
        if vad_config:
            settings["vad"] = vad_config
        else:
            settings["vad"] = {
                "thresh": 0.5,
                "min_silence_ms": 500,
                "min_speech_ms": 200,
                "speech_pad_ms": 300,
            }

        # Behavior toggles
        settings["enable_barge_in"] = yaml_cfg.get("enable_barge_in", True)
        settings["enable_heartbeat_interaction"] = yaml_cfg.get(
            "enable_heartbeat_interaction", True
        )

        # Heartbeat config
        heartbeat_config = yaml_cfg.get("heartbeat_interaction_config")
        if heartbeat_config:
            settings["heartbeat"] = heartbeat_config

        return settings

    @staticmethod
    def _merge_missing(existing: dict, seed: dict) -> dict:
        """Recursively merge seed fields into existing, only filling missing/empty values.

        - If a top-level key is missing from existing, add it from seed.
        - If both values are dicts, recurse.
        - Never overwrite an existing non-empty value.
        """
        result = dict(existing)
        for key, seed_val in seed.items():
            if key not in result or result[key] is None or result[key] == "" or result[key] == {}:
                result[key] = seed_val
            elif isinstance(result[key], dict) and isinstance(seed_val, dict):
                result[key] = Command._merge_missing(result[key], seed_val)
        return result
