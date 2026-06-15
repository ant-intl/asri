"""
Environment configuration loader.

Determines Django settings module based on SERVER_ENV environment variable.
Defaults to base.py for all environments; users can override via DJANGO_SETTINGS_MODULE.
"""
import os


def env_settings() -> None:
    """
    Set DJANGO_SETTINGS_MODULE based on SERVER_ENV environment variable.
    
    If DJANGO_SETTINGS_MODULE is already set, this function does nothing.
    """
    if "DJANGO_SETTINGS_MODULE" in os.environ:
        return
    
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
