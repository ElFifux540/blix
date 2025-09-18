from django.contrib import admin
from .models import Conversation, Membership, Message, Contact, GroupInvitation


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
	list_display = ("id", "type", "name", "created_by", "created_at")
	search_fields = ("name",)
	list_filter = ("type",)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
	list_display = ("id", "conversation", "user", "is_admin", "joined_at")
	search_fields = ("user__username",)
	list_filter = ("is_admin",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
	list_display = ("id", "conversation", "sender", "created_at")
	search_fields = ("content",)
	list_filter = ("conversation",)


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
	list_display = ("from_user", "to_user", "status", "created_at")
	list_filter = ("status", "created_at")
	search_fields = ("from_user__username", "to_user__username")


@admin.register(GroupInvitation)
class GroupInvitationAdmin(admin.ModelAdmin):
	list_display = ("conversation", "from_user", "to_user", "status", "created_at")
	list_filter = ("status", "created_at")
	search_fields = ("conversation__name", "from_user__username", "to_user__username")


