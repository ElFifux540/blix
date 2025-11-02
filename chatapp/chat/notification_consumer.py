import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from .models import Notification

logger = logging.getLogger(__name__)


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        logger.info(f"[NOTIF-CONNECT] Tentative de connexion WebSocket notifications par user {user.username if user and not isinstance(user, AnonymousUser) else 'Anonymous'}")
        if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
            logger.warning(f"[NOTIF-CONNECT] Connexion refusée: user non authentifié")
            await self.close(code=4401)
            return
        
        self.user_id = user.id
        self.user_group_name = f"notifications_{self.user_id}"
        logger.info(f"[NOTIF-CONNECT] User {user.username} (ID: {self.user_id}) connecté aux notifications")
        
        # Rejoindre le groupe de notifications de l'utilisateur
        await self.channel_layer.group_add(self.user_group_name, self.channel_name)
        await self.accept()
        logger.info(f"[NOTIF-CONNECT] Connexion WebSocket notifications acceptée")
        
        # Envoyer les notifications non lues existantes
        await self.send_existing_notifications()

    async def disconnect(self, close_code):
        logger.info(f"[NOTIF-DISCONNECT] User {self.user_id} déconnecté des notifications (close_code: {close_code})")
        # Quitter le groupe de notifications
        await self.channel_layer.group_discard(self.user_group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        action = data.get("action")
        logger.info(f"[NOTIF-RECEIVE] Action reçue: {action} de user {self.user_id}")
        
        if action == "mark_read":
            notification_id = data.get("notification_id")
            logger.info(f"[NOTIF-RECEIVE] Marquer notification {notification_id} comme lue")
            await self.mark_notification_read(notification_id)
        elif action == "get_notifications":
            logger.info(f"[NOTIF-RECEIVE] Demande notifications existantes")
            await self.send_existing_notifications()

    async def notification_message(self, event):
        # Envoyer la notification au client
        notif_data = event["notification"]
        logger.info(f"[NOTIF-MESSAGE] Envoi notification {notif_data.get('id')} de type {notif_data.get('type')} à user {self.user_id}")
        await self.send(text_data=json.dumps({
            "type": "notification",
            "notification": event["notification"]
        }))

    async def send_existing_notifications(self):
        """Envoyer les notifications non lues existantes"""
        notifications = await self._get_unread_notifications()
        logger.info(f"[NOTIF-SEND-EXISTING] Envoi {len(notifications)} notifications non lues à user {self.user_id}")
        
        for notification in notifications:
            await self.send(text_data=json.dumps({
                "type": "notification",
                "notification": {
                    "id": notification.id,
                    "type": notification.type,
                    "title": notification.title,
                    "content": notification.content,
                    "conversation_id": notification.conversation_id,
                    "created_at": notification.created_at.isoformat(),
                    "read": notification.read,
                    "action": {
                        "conversationId": notification.conversation_id,
                        "label": "Ouvrir"
                    } if notification.conversation_id else None
                }
            }))
    
    @database_sync_to_async
    def _get_unread_notifications(self):
        """Récupérer les notifications non lues"""
        return list(Notification.objects.filter(
            user_id=self.user_id,
            read=False
        ).order_by('-created_at')[:10])

    @database_sync_to_async
    def mark_notification_read(self, notification_id):
        """Marquer une notification comme lue"""
        try:
            notification = Notification.objects.get(
                id=notification_id,
                user_id=self.user_id
            )
            notification.read = True
            notification.save()
            logger.info(f"[NOTIF-MARK-READ] Notification {notification_id} marquée comme lue pour user {self.user_id}")
        except Notification.DoesNotExist:
            logger.warning(f"[NOTIF-MARK-READ] Notification {notification_id} introuvable pour user {self.user_id}")


