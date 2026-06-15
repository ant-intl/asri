"""
Chatbot URL configuration.
"""
from django.urls import path, include

app_name = 'chatbot'

urlpatterns = [
    path('api/', include('apps.api.urls')),
]
