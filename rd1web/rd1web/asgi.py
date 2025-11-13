"""
ASGI config for rd1web project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.urls import path
from pxe.consumers import SOLConsumer, RemoteSOLConsumer
from django.conf import settings
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rd1web.settings')

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()

# Optionally serve static files (including admin assets) directly via ASGI
if settings.SERVE_STATIC_VIA_DJANGO:
    django_asgi_app = ASGIStaticFilesHandler(django_asgi_app)

websocket_urlpatterns = [
    # SOL (Serial Over LAN) WebSocket endpoints
    path('ws/sol/<str:folder_name>/', SOLConsumer.as_asgi()),
    path('ws/remote-sol/', RemoteSOLConsumer.as_asgi()),
    
    # KVM WebSocket endpoints removed - KVM now uses direct BMC URL approach
]

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    ),
})
