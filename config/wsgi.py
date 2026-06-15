"""
WSGI config for ASRI project.

It exposes the WSGI callable as a module-level variable named ``application``.
"""
from django.core.wsgi import get_wsgi_application

from .env import env_settings

# Initialize settings based on environment
env_settings()

application = get_wsgi_application()
