import json
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from django.contrib.auth.models import AnonymousUser

from .models import Conversation, Membership, Message


class ChatConsumer(AsyncWebsocketConsumer):
	async def connect(self):
		user = self.scope.get("user")
		if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
			await self.close(code=4401)
			return
		self.room_name = self.scope["url_route"]["kwargs"]["room_name"]
		# Accept either numeric conversation id or slug-like
		self.conversation = await self._get_conversation(self.room_name)
		if not self.conversation:
			await self.close(code=4404)
			return
		is_member = await self._is_member(self.conversation.id, user.id)
		if not is_member:
			await self.close(code=4403)
			return
		self.room_group_name = f"chat_{self.conversation.id}"

		await self.channel_layer.group_add(self.room_group_name, self.channel_name)
		await self.accept()

	async def disconnect(self, close_code):
		# Guard in case connect was refused before room_group_name was set
		room = getattr(self, "room_group_name", None)
		if room:
			await self.channel_layer.group_discard(room, self.channel_name)

	async def receive(self, text_data):
		data = json.loads(text_data)
		content = data.get("message", "").strip()
		if not content:
			return
		user = self.scope.get("user")
		
		# Vérifier les contacts pour les conversations privées
		if self.conversation.type == "direct":
			can_send = await self._check_contact_status(self.conversation.id, user.id)
			if not can_send:
				await self.send(text_data=json.dumps({
					"error": "Impossible d'envoyer un message : vous n'êtes plus en contact avec cet utilisateur"
				}))
				return
		
		message_obj = await self._create_message(self.conversation.id, user.id, content)
		await self.channel_layer.group_send(
			self.room_group_name,
			{
				"type": "chat_message",
				"message": {
					"id": message_obj["id"],
					"conversation": message_obj["conversation"],
					"sender": message_obj["sender"],
					"sender_username": message_obj["sender_username"],
					"content": message_obj["content"],
					"created_at": message_obj["created_at"],
				},
			},
		)

	async def chat_message(self, event):
		await self.send(text_data=json.dumps({"message": event["message"]}))

	@database_sync_to_async
	def _get_conversation(self, room_name):
		try:
			if room_name.isdigit():
				return Conversation.objects.get(pk=int(room_name))
			# fallback: allow using name for group rooms if unique
			return Conversation.objects.filter(name=room_name).first()
		except Conversation.DoesNotExist:
			return None

	@database_sync_to_async
	def _is_member(self, conversation_id: int, user_id: int) -> bool:
		return Membership.objects.filter(conversation_id=conversation_id, user_id=user_id).exists()

	@database_sync_to_async
	def _check_contact_status(self, conversation_id: int, user_id: int) -> bool:
		"""Vérifier si les utilisateurs sont toujours en contact pour une conversation privée"""
		from django.db.models import Q
		from .models import Contact
		
		# Récupérer l'autre utilisateur de la conversation
		other_membership = Membership.objects.filter(
			conversation_id=conversation_id
		).exclude(user_id=user_id).first()
		
		if not other_membership:
			return False
		
		other_user_id = other_membership.user_id
		
		# Vérifier si les utilisateurs sont toujours en contact
		return Contact.objects.filter(
			Q(from_user_id=user_id, to_user_id=other_user_id, status='accepted') |
			Q(from_user_id=other_user_id, to_user_id=user_id, status='accepted')
		).exists()

	@database_sync_to_async
	def _create_message(self, conversation_id: int, user_id: int, content: str):
		msg = Message.objects.create(conversation_id=conversation_id, sender_id=user_id, content=content)
		# Récupérer le nom d'utilisateur
		from django.contrib.auth import get_user_model
		User = get_user_model()
		sender = User.objects.get(id=user_id)
		return {
			"id": msg.id,
			"conversation": msg.conversation_id,
			"sender": user_id,
			"sender_username": sender.username,
			"content": msg.content,
			"created_at": msg.created_at.isoformat(),
		}
