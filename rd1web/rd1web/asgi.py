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
from pxe.consumers import SOLConsumer
from pxe.consumers import RemoteSOLConsumer
from django.conf import settings
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rd1web.settings')

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()

# In development, serve static files (including admin CSS) directly via ASGI
if settings.DEBUG:
    django_asgi_app = ASGIStaticFilesHandler(django_asgi_app)

websocket_urlpatterns = [
    path('ws/sol/<str:folder_name>/', SOLConsumer.as_asgi()),
    path('ws/remote-sol/', RemoteSOLConsumer.as_asgi()),
]

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    ),
})
