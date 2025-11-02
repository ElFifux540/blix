import json
import logging
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from django.contrib.auth.models import AnonymousUser

from .models import Conversation, Membership, Message

logger = logging.getLogger(__name__)


class ChatConsumer(AsyncWebsocketConsumer):
	async def connect(self):
		user = self.scope.get("user")
		logger.info(f"[WS-CONNECT] Tentative de connexion WebSocket par user {user.username if user and not isinstance(user, AnonymousUser) else 'Anonymous'}")
		if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
			logger.warning(f"[WS-CONNECT] Connexion refusée: user non authentifié")
			await self.close(code=4401)
			return
		self.room_name = self.scope["url_route"]["kwargs"]["room_name"]
		logger.info(f"[WS-CONNECT] Room name: {self.room_name}")
		# Accept either numeric conversation id or slug-like
		self.conversation = await self._get_conversation(self.room_name)
		if not self.conversation:
			logger.warning(f"[WS-CONNECT] Conversation {self.room_name} introuvable")
			await self.close(code=4404)
			return
		is_member = await self._is_member(self.conversation.id, user.id)
		if not is_member:
			logger.warning(f"[WS-CONNECT] User {user.id} n'est pas membre de conversation {self.conversation.id}")
			await self.close(code=4403)
			return
		self.room_group_name = f"chat_{self.conversation.id}"
		logger.info(f"[WS-CONNECT] User {user.username} (ID: {user.id}) connecté au chat {self.conversation.id}")

		await self.channel_layer.group_add(self.room_group_name, self.channel_name)
		await self.accept()
		logger.info(f"[WS-CONNECT] Connexion WebSocket acceptée pour chat {self.conversation.id}")

	async def disconnect(self, close_code):
		# Guard in case connect was refused before room_group_name was set
		room = getattr(self, "room_group_name", None)
		user = self.scope.get("user")
		username = user.username if user and hasattr(user, 'username') else 'Unknown'
		logger.info(f"[WS-DISCONNECT] User {username} déconnecté du chat (close_code: {close_code})")
		if room:
			await self.channel_layer.group_discard(room, self.channel_name)
			logger.info(f"[WS-DISCONNECT] Retiré du groupe {room}")

	async def receive(self, text_data):
		data = json.loads(text_data)
		content = data.get("message", "").strip()
		user = self.scope.get("user")
		logger.info(f"[WS-RECEIVE] Message reçu de user {user.username} (ID: {user.id}) dans conversation {self.conversation.id}: '{content[:50]}...'")
		if not content:
			logger.warning(f"[WS-RECEIVE] Message vide ignoré")
			return
		
		# Vérifier les contacts pour les conversations privées
		if self.conversation.type == "direct":
			logger.info(f"[WS-RECEIVE] Vérification contact pour conversation directe {self.conversation.id}")
			can_send = await self._check_contact_status(self.conversation.id, user.id)
			if not can_send:
				logger.warning(f"[WS-RECEIVE] Contact refusé pour user {user.id}")
				await self.send(text_data=json.dumps({
					"error": "Impossible d'envoyer un message : vous n'êtes plus en contact avec cet utilisateur"
				}))
				return
		
		message_obj = await self._create_message(self.conversation.id, user.id, content)
		logger.info(f"[WS-RECEIVE] Message créé avec ID: {message_obj['id']}")
		logger.info(f"[WS-RECEIVE] Envoi via channel layer vers groupe {self.room_group_name}")
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
		
		# Créer des notifications pour les autres membres de la conversation
		logger.info(f"[WS-RECEIVE] Création notifications pour les autres membres")
		await self._create_message_notifications(user.id, self.conversation.id, message_obj["sender_username"], content)

	async def chat_message(self, event):
		logger.info(f"[WS-CHAT-MESSAGE] Envoi message {event['message'].get('id')} via WebSocket")
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
	
	@database_sync_to_async
	def _create_message_notifications(self, sender_id: int, conversation_id: int, sender_username: str, content: str):
		"""Créer des notifications pour les autres membres de la conversation"""
		from .notification_views import create_message_notification
		from .models import Conversation
		
		conversation = Conversation.objects.get(pk=conversation_id)
		other_members = Membership.objects.filter(conversation_id=conversation_id).exclude(user_id=sender_id)
		
		for membership in other_members:
			create_message_notification(
				user=membership.user,
				conversation=conversation,
				sender_username=sender_username,
				message_content=content
			)
