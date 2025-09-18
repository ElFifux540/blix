from django.urls import path, include
from django.shortcuts import render, redirect
from rest_framework.routers import DefaultRouter
from .views import ConversationViewSet, get_csrf_token, get_all_users, test_page
from .contact_views import ContactViewSet, GroupInvitationViewSet

router = DefaultRouter()
router.register(r"conversations", ConversationViewSet, basename="conversation")
router.register(r"contacts", ContactViewSet, basename="contact")
router.register(r"group-invitations", GroupInvitationViewSet, basename="group-invitation")

def main_view(request):
    if not request.user.is_authenticated:
        return redirect("/accounts/login/")
    return render(request, "chat/main.html")

urlpatterns = [
	path("", main_view, name="main"),
	path("test/", test_page, name="test"),
	path("api/csrf-token/", get_csrf_token, name="csrf_token"),
	path("api/users/all/", get_all_users, name="all_users"),
	path("api/", include(router.urls)),
]
