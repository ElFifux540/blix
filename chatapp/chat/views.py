import logging
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.middleware.csrf import get_token
from django.http import JsonResponse
from datetime import datetime, timezone as dt_timezone

from .models import Conversation, Membership, Message, Contact
from .serializers import ConversationSerializer, MessageSerializer
from .notification_views import create_message_notification

logger = logging.getLogger(__name__)


class IsAuthenticated(permissions.IsAuthenticated):
	pass


@method_decorator(csrf_exempt, name="dispatch")
class ConversationViewSet(viewsets.ModelViewSet):
	permission_classes = [IsAuthenticated]
	serializer_class = ConversationSerializer
	parser_classes = (MultiPartParser, FormParser, JSONParser)

	def get_queryset(self):
		return Conversation.objects.filter(memberships__user=self.request.user).distinct()

	def perform_create(self, serializer):
		conversation = serializer.save(created_by=self.request.user)
		Membership.objects.get_or_create(conversation=conversation, user=self.request.user, defaults={"is_admin": True})

	@action(detail=False, methods=["post"], url_path="create-direct")
	def create_direct(self, request):
		logger.info(f"[CREATE-DIRECT] User {request.user.username} (ID: {request.user.id}) demande création conversation directe")
		User = get_user_model()
		target_user_id = request.data.get("user_id")
		if not target_user_id:
			logger.warning(f"[CREATE-DIRECT] user_id manquant pour user {request.user.username}")
			return Response({"detail": "user_id requis"}, status=status.HTTP_400_BAD_REQUEST)
		target_user = get_object_or_404(User, pk=target_user_id)
		logger.info(f"[CREATE-DIRECT] Recherche conversation entre {request.user.username} et {target_user.username}")
		# For direct, reuse existing direct conversation between the two users if any
		conv = (
			Conversation.objects
			.filter(type="direct", memberships__user=request.user)
			.filter(memberships__user=target_user)
			.distinct()
			.first()
		)
		if not conv:
			logger.info(f"[CREATE-DIRECT] Création nouvelle conversation entre {request.user.username} et {target_user.username}")
			conv = Conversation.objects.create(type="direct", created_by=request.user)
			Membership.objects.bulk_create([
				Membership(conversation=conv, user=request.user, is_admin=True),
				Membership(conversation=conv, user=target_user, is_admin=False),
			])
			logger.info(f"[CREATE-DIRECT] Conversation créée avec ID: {conv.id}")
		else:
			logger.info(f"[CREATE-DIRECT] Conversation existante trouvée avec ID: {conv.id}")
		return Response(ConversationSerializer(conv).data, status=status.HTTP_201_CREATED)

	@action(detail=True, methods=["post"], url_path="join")
	def join(self, request, pk=None):
		conversation = self.get_object()
		logger.info(f"[JOIN] User {request.user.username} (ID: {request.user.id}) rejoint conversation {conversation.id}")
		membership, created = Membership.objects.get_or_create(conversation=conversation, user=request.user)
		if created:
			logger.info(f"[JOIN] Nouveau membership créé pour user {request.user.id} dans conversation {conversation.id}")
		else:
			logger.info(f"[JOIN] Membership existant pour user {request.user.id} dans conversation {conversation.id}")
		return Response({"status": "joined"})

	@action(detail=True, methods=["get"], url_path="messages")
	def list_messages(self, request, pk=None):
		conversation = self.get_object()
		logger.info(f"[LIST-MESSAGES] User {request.user.username} demande messages de conversation {conversation.id}")
		if not Membership.objects.filter(conversation=conversation, user=request.user).exists():
			logger.warning(f"[LIST-MESSAGES] Accès refusé: user {request.user.id} n'est pas membre de conversation {conversation.id}")
			return Response({"detail": "Accès refusé"}, status=status.HTTP_403_FORBIDDEN)
		messages = Message.objects.filter(conversation=conversation).select_related("sender")[:200]
		logger.info(f"[LIST-MESSAGES] {len(messages)} messages retournés pour conversation {conversation.id}")
		return Response(MessageSerializer(messages, many=True).data)

	@action(detail=True, methods=["post"], url_path="send")
	def send_message(self, request, pk=None):
		conversation = self.get_object()
		logger.info(f"[SEND-MESSAGE] User {request.user.username} (ID: {request.user.id}) envoie message dans conversation {conversation.id}")
		if not Membership.objects.filter(conversation=conversation, user=request.user).exists():
			logger.warning(f"[SEND-MESSAGE] Accès refusé: user {request.user.id} n'est pas membre de conversation {conversation.id}")
			return Response({"detail": "Accès refusé"}, status=status.HTTP_403_FORBIDDEN)
		
		# Pour les conversations privées, vérifier que les utilisateurs sont toujours en contact
		if conversation.type == "direct":
			logger.info(f"[SEND-MESSAGE] Vérification contact pour conversation directe {conversation.id}")
			# Récupérer l'autre utilisateur de la conversation
			other_membership = Membership.objects.filter(
				conversation=conversation
			).exclude(user=request.user).first()
			
			if other_membership:
				other_user = other_membership.user
				# Vérifier si les utilisateurs sont toujours en contact
				contact_exists = Contact.objects.filter(
					Q(from_user=request.user, to_user=other_user, status='accepted') |
					Q(from_user=other_user, to_user=request.user, status='accepted')
				).exists()
				
				if not contact_exists:
					logger.warning(f"[SEND-MESSAGE] Contact refusé: user {request.user.id} et {other_user.id} ne sont plus en contact")
					return Response({
						"detail": "Impossible d'envoyer un message : vous n'êtes plus en contact avec cet utilisateur"
					}, status=status.HTTP_403_FORBIDDEN)
		
		content = (request.data.get("content", "") or "").strip()
		attachment = request.FILES.get("attachment")
		logger.info(f"[SEND-MESSAGE] Contenu: '{content[:50]}...' (len={len(content)}), Attachment: {attachment.name if attachment else 'None'}")
		if not content and not attachment:
			logger.warning(f"[SEND-MESSAGE] Message vide refusé pour user {request.user.id}")
			return Response({"detail": "content ou attachment requis"}, status=status.HTTP_400_BAD_REQUEST)
		message = Message.objects.create(conversation=conversation, sender=request.user, content=content, attachment=attachment)
		logger.info(f"[SEND-MESSAGE] Message créé avec ID: {message.id}")
		
		# Créer des notifications pour les autres membres de la conversation
		other_members = Membership.objects.filter(conversation=conversation).exclude(user=request.user)
		for membership in other_members:
			create_message_notification(
				user=membership.user,
				conversation=conversation,
				sender_username=request.user.username,
				message_content=content or "Fichier partagé"
			)
		
		# Notify via channel layer group
		from asgiref.sync import async_to_sync
		from channels.layers import get_channel_layer
		channel_layer = get_channel_layer()
		logger.info(f"[SEND-MESSAGE] Envoi via channel layer vers groupe chat_{conversation.id}")
		async_to_sync(channel_layer.group_send)(
			f"chat_{conversation.id}",
			{"type": "chat_message", "message": MessageSerializer(message).data},
		)
		logger.info(f"[SEND-MESSAGE] Message {message.id} envoyé avec succès")
		return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)

	@action(detail=True, methods=["post"], url_path="mark-read")
	def mark_read(self, request, pk=None):
		conversation = self.get_object()
		m = Membership.objects.filter(conversation=conversation, user=request.user).first()
		if not m:
			return Response({"detail": "Accès refusé"}, status=status.HTTP_403_FORBIDDEN)
		m.last_read_at = timezone.now()
		m.save(update_fields=["last_read_at"])
		return Response({"status": "ok", "last_read_at": m.last_read_at})

	@action(detail=False, methods=["get"], url_path="unread-count")
	def unread_count(self, request):
		# return total unread messages across conversations
		qs = Membership.objects.filter(user=request.user).select_related("conversation")
		counts = {}
		for mem in qs:
			last_ts = mem.last_read_at or datetime.fromtimestamp(0, tz=dt_timezone.utc)
			counts[mem.conversation_id] = Message.objects.filter(conversation=mem.conversation, created_at__gt=last_ts).count()
		return Response({"by_conversation": counts, "total": sum(counts.values())})

	@action(detail=False, methods=["post"], url_path="create-group")
	def create_group(self, request):
		"""Créer une conversation de groupe par nom"""
		logger.info(f"[CREATE-GROUP] User {request.user.username} (ID: {request.user.id}) crée groupe")
		name = request.data.get("name")
		if not name:
			logger.warning(f"[CREATE-GROUP] Nom manquant pour user {request.user.id}")
			return Response({"detail": "name requis"}, status=status.HTTP_400_BAD_REQUEST)
		
		# Vérifier si un groupe avec ce nom existe déjà
		if Conversation.objects.filter(name=name, type="group").exists():
			logger.warning(f"[CREATE-GROUP] Groupe '{name}' existe déjà")
			return Response({"detail": "Un groupe avec ce nom existe déjà"}, status=status.HTTP_400_BAD_REQUEST)
		
		conversation = Conversation.objects.create(
			name=name,
			type="group",
			created_by=request.user
		)
		Membership.objects.create(
			conversation=conversation,
			user=request.user,
			is_admin=True
		)
		logger.info(f"[CREATE-GROUP] Groupe '{name}' créé avec ID: {conversation.id}")
		return Response(ConversationSerializer(conversation).data, status=status.HTTP_201_CREATED)

	@action(detail=False, methods=["post"], url_path="create-direct-by-username")
	def create_direct_by_username(self, request):
		"""Créer une conversation privée par nom d'utilisateur"""
		logger.info(f"[CREATE-DIRECT-BY-USERNAME] User {request.user.username} crée conversation avec username")
		username = request.data.get("username")
		if not username:
			logger.warning(f"[CREATE-DIRECT-BY-USERNAME] Username manquant pour user {request.user.id}")
			return Response({"detail": "username requis"}, status=status.HTTP_400_BAD_REQUEST)
		
		try:
			target_user = get_user_model().objects.get(username=username)
			logger.info(f"[CREATE-DIRECT-BY-USERNAME] Utilisateur cible trouvé: {target_user.username} (ID: {target_user.id})")
		except get_user_model().DoesNotExist:
			logger.warning(f"[CREATE-DIRECT-BY-USERNAME] Utilisateur '{username}' introuvable")
			return Response({"detail": "Utilisateur introuvable"}, status=status.HTTP_404_NOT_FOUND)
		
		if target_user == request.user:
			logger.warning(f"[CREATE-DIRECT-BY-USERNAME] User {request.user.id} essaie de créer conversation avec lui-même")
			return Response({"detail": "Impossible de créer une conversation avec soi-même"}, status=status.HTTP_400_BAD_REQUEST)
		
		# Vérifier si les utilisateurs sont en contact
		contact_exists = Contact.objects.filter(
			Q(from_user=request.user, to_user=target_user, status='accepted') |
			Q(from_user=target_user, to_user=request.user, status='accepted')
		).exists()
		
		if not contact_exists:
			logger.warning(f"[CREATE-DIRECT-BY-USERNAME] Contact manquant entre {request.user.id} et {target_user.id}")
			return Response({"detail": "Vous devez être en contact avec cet utilisateur"}, status=status.HTTP_403_FORBIDDEN)
		
		# Chercher une conversation directe existante
		conv = Conversation.objects.filter(
			type="direct",
			memberships__user=request.user
		).filter(
			memberships__user=target_user
		).distinct().first()
		
		if not conv:
			logger.info(f"[CREATE-DIRECT-BY-USERNAME] Création nouvelle conversation entre {request.user.username} et {target_user.username}")
			conv = Conversation.objects.create(type="direct", created_by=request.user)
			Membership.objects.bulk_create([
				Membership(conversation=conv, user=request.user, is_admin=True),
				Membership(conversation=conv, user=target_user, is_admin=False),
			])
			logger.info(f"[CREATE-DIRECT-BY-USERNAME] Conversation créée avec ID: {conv.id}")
		else:
			logger.info(f"[CREATE-DIRECT-BY-USERNAME] Conversation existante trouvée avec ID: {conv.id}")
		
		return Response(ConversationSerializer(conv).data, status=status.HTTP_201_CREATED)

	@action(detail=False, methods=["get"], url_path="by-type")
	def conversations_by_type(self, request):
		"""Lister les conversations par type (direct/group)"""
		conv_type = request.query_params.get("type", "direct")
		logger.info(f"[BY-TYPE] User {request.user.username} demande conversations de type: {conv_type}")
		conversations = Conversation.objects.filter(
			memberships__user=request.user,
			type=conv_type
		).prefetch_related('memberships__user').distinct().order_by('-created_at')
		logger.info(f"[BY-TYPE] {len(conversations)} conversations de type {conv_type} retournées")
		return Response(ConversationSerializer(conversations, many=True).data)


@api_view(['GET'])
def get_csrf_token(request):
	"""Récupérer le token CSRF"""
	logger.info(f"[CSRF-TOKEN] Token CSRF demandé par user {request.user.username if request.user.is_authenticated else 'Anonymous'}")
	return JsonResponse({'csrfToken': get_token(request)})


@api_view(['GET'])
def get_all_users(request):
	"""Récupérer tous les utilisateurs pour l'invitation aux groupes"""
	User = get_user_model()
	users = User.objects.all().values('id', 'username')
	return JsonResponse(list(users), safe=False)


def test_page(request):
	"""Page de test simple"""
	return render(request, 'chat/test.html')

