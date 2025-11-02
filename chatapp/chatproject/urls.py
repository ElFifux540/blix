from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Rediriger /accounts/login/ vers la version HTMX
    path("accounts/login/", RedirectView.as_view(url='/accounts/htmx-login/', permanent=False), name='login'),
    # Garder les autres routes auth Django
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("chat.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
