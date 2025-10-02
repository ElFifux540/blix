from django.conf import settings
from django.db import models


class Conversation(models.Model):
	CONVERSATION_TYPE_CHOICES = (
		("direct", "Direct"),
		("group", "Group"),
	)

	name = models.CharField(max_length=255, blank=True, default="")
	type = models.CharField(max_length=16, choices=CONVERSATION_TYPE_CHOICES)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="created_conversations")
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		indexes = [
			models.Index(fields=["type", "created_at"]),
		]

	def __str__(self) -> str:
		label = self.name or f"{self.type}"
		return f"Conversation({label})"


class Membership(models.Model):
	conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="memberships")
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_memberships")
	is_admin = models.BooleanField(default=False)
	joined_at = models.DateTimeField(auto_now_add=True)
	last_read_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		unique_together = ("conversation", "user")
		indexes = [
			models.Index(fields=["user", "conversation"]),
		]

	def __str__(self) -> str:
		return f"Membership(user={self.user_id}, conv={self.conversation_id})"


class Message(models.Model):
	conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
	sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_messages")
	content = models.TextField()
	attachment = models.FileField(upload_to="chat_attachments/", null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["created_at", "id"]
		indexes = [
			models.Index(fields=["conversation", "created_at"]),
			models.Index(fields=["conversation", "id"]),
		]

	def __str__(self) -> str:
		return f"Message({self.id}) in conv {self.conversation_id}"


class Contact(models.Model):
	STATUS_CHOICES = [
		('pending', 'En attente'),
		('accepted', 'Accepté'),
		('blocked', 'Bloqué'),
	]
	
	from_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_contacts')
	to_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_contacts')
	status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		unique_together = ('from_user', 'to_user')
		indexes = [
			models.Index(fields=['from_user', 'status']),
			models.Index(fields=['to_user', 'status']),
		]

	def __str__(self):
		return f"{self.from_user.username} -> {self.to_user.username} ({self.status})"


class GroupInvitation(models.Model):
	STATUS_CHOICES = [
		('pending', 'En attente'),
		('accepted', 'Accepté'),
		('declined', 'Refusé'),
	]
	
	conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='invitations')
	from_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_invitations')
	to_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_invitations')
	status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		unique_together = ('conversation', 'to_user')
		indexes = [
			models.Index(fields=['to_user', 'status']),
		]

	def __str__(self):
		return f"Invitation {self.conversation.name} pour {self.to_user.username}"


