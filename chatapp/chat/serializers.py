from django.contrib.auth import get_user_model
from rest_framework import serializers
from .models import Conversation, Membership, Message, Contact, GroupInvitation


class UserSerializer(serializers.ModelSerializer):
	class Meta:
		model = get_user_model()
		fields = ("id", "username")


class MembershipSerializer(serializers.ModelSerializer):
	user = UserSerializer(read_only=True)

	class Meta:
		model = Membership
		fields = ("id", "user", "is_admin", "joined_at", "last_read_at")


class ConversationSerializer(serializers.ModelSerializer):
	created_by = UserSerializer(read_only=True)
	memberships = MembershipSerializer(many=True, read_only=True)

	class Meta:
		model = Conversation
		fields = ("id", "type", "name", "created_by", "created_at", "memberships")


class MessageSerializer(serializers.ModelSerializer):
	sender = UserSerializer(read_only=True)
	sender_username = serializers.CharField(source='sender.username', read_only=True)

	class Meta:
		model = Message
		fields = ("id", "conversation", "sender", "sender_username", "content", "created_at")
		read_only_fields = ("sender", "sender_username", "created_at")


class ContactSerializer(serializers.ModelSerializer):
	from_user = UserSerializer(read_only=True)
	to_user = UserSerializer(read_only=True)

	class Meta:
		model = Contact
		fields = ("id", "from_user", "to_user", "status", "created_at", "updated_at")
		read_only_fields = ("from_user", "created_at", "updated_at")


class GroupInvitationSerializer(serializers.ModelSerializer):
	from_user = UserSerializer(read_only=True)
	to_user = UserSerializer(read_only=True)
	conversation_name = serializers.CharField(source='conversation.name', read_only=True)

	class Meta:
		model = GroupInvitation
		fields = ("id", "conversation", "conversation_name", "from_user", "to_user", "status", "created_at", "updated_at")
		read_only_fields = ("from_user", "created_at", "updated_at")


