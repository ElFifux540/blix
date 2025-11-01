import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from .models import Notification


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
            await self.close(code=4401)
            return
        
        self.user_id = user.id
        self.user_group_name = f"notifications_{self.user_id}"
        
        # Rejoindre le groupe de notifications de l'utilisateur
        await self.channel_layer.group_add(self.user_group_name, self.channel_name)
        await self.accept()
        
        # Envoyer les notifications non lues existantes
        await self.send_existing_notifications()

    async def disconnect(self, close_code):
        # Quitter le groupe de notifications
        await self.channel_layer.group_discard(self.user_group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        action = data.get("action")
        
        if action == "mark_read":
            notification_id = data.get("notification_id")
            await self.mark_notification_read(notification_id)
        elif action == "get_notifications":
            await self.send_existing_notifications()

    async def notification_message(self, event):
        # Envoyer la notification au client
        await self.send(text_data=json.dumps({
            "type": "notification",
            "notification": event["notification"]
        }))

    async def send_existing_notifications(self):
        """Envoyer les notifications non lues existantes"""
        notifications = await self._get_unread_notifications()
        
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
        except Notification.DoesNotExist:
            pass


