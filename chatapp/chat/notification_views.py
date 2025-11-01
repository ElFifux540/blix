from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from .models import Notification, Conversation, Contact, GroupInvitation
from .serializers import NotificationSerializer


class IsAuthenticated(permissions.IsAuthenticated):
	pass


@method_decorator(csrf_exempt, name="dispatch")
class NotificationViewSet(viewsets.ModelViewSet):
	permission_classes = [IsAuthenticated]
	serializer_class = NotificationSerializer
	
	def get_queryset(self):
		return Notification.objects.filter(user=self.request.user)
	
	def list(self, request, *args, **kwargs):
		"""Récupérer toutes les notifications de l'utilisateur"""
		notifications = self.get_queryset()
		serializer = self.get_serializer(notifications, many=True)
		return Response({
			'notifications': serializer.data,
			'unread_count': notifications.filter(read=False).count()
		})
	
	def create(self, request, *args, **kwargs):
		"""Créer une nouvelle notification"""
		serializer = self.get_serializer(data=request.data)
		if serializer.is_valid():
			serializer.save()
			return Response(serializer.data, status=status.HTTP_201_CREATED)
		return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
	
	@action(detail=True, methods=['post'], url_path='mark-read')
	def mark_read(self, request, pk=None):
		"""Marquer une notification comme lue"""
		notification = self.get_object()
		notification.read = True
		notification.save()
		return Response({'status': 'marked as read'})
	
	@action(detail=False, methods=['post'], url_path='mark-all-read')
	def mark_all_read(self, request):
		"""Marquer toutes les notifications comme lues"""
		notifications = self.get_queryset().filter(read=False)
		notifications.update(read=True)
		return Response({'status': f'{notifications.count()} notifications marked as read'})
	
	@action(detail=False, methods=['delete'], url_path='clear-read')
	def clear_read(self, request):
		"""Supprimer toutes les notifications lues"""
		deleted_count, _ = self.get_queryset().filter(read=True).delete()
		return Response({'status': f'{deleted_count} notifications deleted'})
	
	@action(detail=False, methods=['delete'], url_path='clear-all')
	def clear_all(self, request):
		"""Supprimer toutes les notifications"""
		deleted_count, _ = self.get_queryset().delete()
		return Response({'status': f'{deleted_count} notifications deleted'})
	
	@action(detail=False, methods=['get'], url_path='unread-count')
	def unread_count(self, request):
		"""Récupérer le nombre de notifications non lues"""
		count = self.get_queryset().filter(read=False).count()
		return Response({'unread_count': count})


# Fonctions utilitaires pour créer des notifications
def create_message_notification(user, conversation, sender_username, message_content):
	"""Créer une notification pour un nouveau message"""
	title = f"Nouveau message de {sender_username}"
	content = message_content[:100] + "..." if len(message_content) > 100 else message_content
	
	notification = Notification.objects.create(
		user=user,
		type='message',
		title=title,
		content=content,
		conversation=conversation
	)
	
	# Envoyer via WebSocket
	send_notification_websocket(user.id, notification)
	
	return notification


def create_contact_notification(user, contact):
	"""Créer une notification pour une nouvelle demande de contact"""
	title = "Nouvelle demande de contact"
	content = f"{contact.from_user.username} souhaite vous ajouter en contact"
	
	notification = Notification.objects.create(
		user=user,
		type='contact',
		title=title,
		content=content,
		contact=contact
	)
	
	# Envoyer via WebSocket
	send_notification_websocket(user.id, notification)
	
	return notification


def create_group_invitation_notification(user, group_invitation):
	"""Créer une notification pour une nouvelle invitation de groupe"""
	title = "Nouvelle invitation de groupe"
	content = f"Vous êtes invité à rejoindre '{group_invitation.conversation.name}' par {group_invitation.from_user.username}"
	
	notification = Notification.objects.create(
		user=user,
		type='group',
		title=title,
		content=content,
		conversation=group_invitation.conversation,
		group_invitation=group_invitation
	)
	
	# Envoyer via WebSocket
	send_notification_websocket(user.id, notification)
	
	return notification


def send_notification_websocket(user_id, notification):
	"""Envoyer une notification via WebSocket"""
	from asgiref.sync import async_to_sync
	from channels.layers import get_channel_layer
	
	channel_layer = get_channel_layer()
	user_group_name = f"notifications_{user_id}"
	
	async_to_sync(channel_layer.group_send)(
		user_group_name,
		{
			"type": "notification_message",
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
		}
	)


def cleanup_old_notifications(days=30):
	"""Nettoyer les anciennes notifications lues"""
	cutoff_date = timezone.now() - timezone.timedelta(days=days)
	deleted_count, _ = Notification.objects.filter(
		read=True,
		created_at__lt=cutoff_date
	).delete()
	return deleted_count
