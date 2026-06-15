"""
URL configuration for ASRI project.
"""
import os
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import TemplateView


from django.shortcuts import render
from django.utils.cache import add_never_cache_headers

def serve_frontend(request, path=''):
    """Serve the frontend page and handle frontend routing (e.g. /chat)"""
    context = {
        'SERVER_ENV': os.environ.get('SERVER_ENV', 'prod'),
        'DEBUG': settings.DEBUG,
    }
    response = render(request, 'frontend/index.html', context)
    add_never_cache_headers(response)
    return response


urlpatterns = [
    path('admin/', admin.site.urls),
    path('health_check/', include('health_check.urls')),
    path('chatbot/', include('apps.urls')),
]

# Serve static files in DEBUG mode (must be placed before catch-all)
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])

# Frontend catch-all route (must be placed last, matches all non-API paths)
urlpatterns.append(re_path(r'^(?P<path>.*)$', serve_frontend))
