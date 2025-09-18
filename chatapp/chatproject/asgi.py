import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chatproject.settings")
from django.core.asgi import get_asgi_application
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator, OriginValidator

# Initialize Django first to ensure apps are loaded
django_asgi_app = get_asgi_application()
http_app = ASGIStaticFilesHandler(django_asgi_app)

# Import routing only after Django setup
from chat.routing import websocket_urlpatterns

# Allow WebSocket origins based on ALLOWED_HOSTS and explicit origins
from django.conf import settings
import os
from dotenv import load_dotenv

load_dotenv()
explicit_allowed_origins = os.getenv('WEBSOCKET_ORIGINS', 'http://localhost:8000,http://127.0.0.1:8000').split(',')


application = ProtocolTypeRouter({
	"http": http_app,
	"websocket": AllowedHostsOriginValidator(
		OriginValidator(
			AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
			explicit_allowed_origins,
		)
	),
})
