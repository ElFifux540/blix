from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.middleware.csrf import get_token
from django.http import JsonResponse

from .models import Conversation, Membership, Message, Contact
from .serializers import ConversationSerializer, MessageSerializer


class IsAuthenticated(permissions.IsAuthenticated):
	pass


@method_decorator(csrf_exempt, name="dispatch")
class ConversationViewSet(viewsets.ModelViewSet):
	permission_classes = [IsAuthenticated]
	serializer_class = ConversationSerializer

	def get_queryset(self):
		return Conversation.objects.filter(memberships__user=self.request.user).distinct()

	def perform_create(self, serializer):
		conversation = serializer.save(created_by=self.request.user)
		Membership.objects.get_or_create(conversation=conversation, user=self.request.user, defaults={"is_admin": True})

	@action(detail=False, methods=["post"], url_path="create-direct")
	def create_direct(self, request):
		User = get_user_model()
		target_user_id = request.data.get("user_id")
		if not target_user_id:
			return Response({"detail": "user_id requis"}, status=status.HTTP_400_BAD_REQUEST)
		target_user = get_object_or_404(User, pk=target_user_id)
		# For direct, reuse existing direct conversation between the two users if any
		conv = (
			Conversation.objects
			.filter(type="direct", memberships__user=request.user)
			.filter(memberships__user=target_user)
			.distinct()
			.first()
		)
		if not conv:
			conv = Conversation.objects.create(type="direct", created_by=request.user)
			Membership.objects.bulk_create([
				Membership(conversation=conv, user=request.user, is_admin=True),
				Membership(conversation=conv, user=target_user, is_admin=False),
			])
		return Response(ConversationSerializer(conv).data, status=status.HTTP_201_CREATED)

	@action(detail=True, methods=["post"], url_path="join")
	def join(self, request, pk=None):
		conversation = self.get_object()
		Membership.objects.get_or_create(conversation=conversation, user=request.user)
		return Response({"status": "joined"})

	@action(detail=True, methods=["get"], url_path="messages")
	def list_messages(self, request, pk=None):
		conversation = self.get_object()
		if not Membership.objects.filter(conversation=conversation, user=request.user).exists():
			return Response({"detail": "Accès refusé"}, status=status.HTTP_403_FORBIDDEN)
		messages = Message.objects.filter(conversation=conversation).select_related("sender")[:200]
		return Response(MessageSerializer(messages, many=True).data)

	@action(detail=True, methods=["post"], url_path="send")
	def send_message(self, request, pk=None):
		conversation = self.get_object()
		if not Membership.objects.filter(conversation=conversation, user=request.user).exists():
			return Response({"detail": "Accès refusé"}, status=status.HTTP_403_FORBIDDEN)
		
		# Pour les conversations privées, vérifier que les utilisateurs sont toujours en contact
		if conversation.type == "direct":
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
					return Response({
						"detail": "Impossible d'envoyer un message : vous n'êtes plus en contact avec cet utilisateur"
					}, status=status.HTTP_403_FORBIDDEN)
		
		content = request.data.get("content", "").strip()
		if not content:
			return Response({"detail": "content requis"}, status=status.HTTP_400_BAD_REQUEST)
		message = Message.objects.create(conversation=conversation, sender=request.user, content=content)
		# Notify via channel layer group
		from asgiref.sync import async_to_sync
		from channels.layers import get_channel_layer
		channel_layer = get_channel_layer()
		async_to_sync(channel_layer.group_send)(
			f"chat_{conversation.id}",
			{"type": "chat_message", "message": MessageSerializer(message).data},
		)
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
			last_ts = mem.last_read_at or timezone.datetime.fromtimestamp(0, tz=timezone.utc)
			counts[mem.conversation_id] = Message.objects.filter(conversation=mem.conversation, created_at__gt=last_ts).count()
		return Response({"by_conversation": counts, "total": sum(counts.values())})

	@action(detail=False, methods=["post"], url_path="create-group")
	def create_group(self, request):
		"""Créer une conversation de groupe par nom"""
		name = request.data.get("name")
		if not name:
			return Response({"detail": "name requis"}, status=status.HTTP_400_BAD_REQUEST)
		
		# Vérifier si un groupe avec ce nom existe déjà
		if Conversation.objects.filter(name=name, type="group").exists():
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
		return Response(ConversationSerializer(conversation).data, status=status.HTTP_201_CREATED)

	@action(detail=False, methods=["post"], url_path="create-direct-by-username")
	def create_direct_by_username(self, request):
		"""Créer une conversation privée par nom d'utilisateur"""
		username = request.data.get("username")
		if not username:
			return Response({"detail": "username requis"}, status=status.HTTP_400_BAD_REQUEST)
		
		try:
			target_user = get_user_model().objects.get(username=username)
		except get_user_model().DoesNotExist:
			return Response({"detail": "Utilisateur introuvable"}, status=status.HTTP_404_NOT_FOUND)
		
		if target_user == request.user:
			return Response({"detail": "Impossible de créer une conversation avec soi-même"}, status=status.HTTP_400_BAD_REQUEST)
		
		# Vérifier si les utilisateurs sont en contact
		contact_exists = Contact.objects.filter(
			Q(from_user=request.user, to_user=target_user, status='accepted') |
			Q(from_user=target_user, to_user=request.user, status='accepted')
		).exists()
		
		if not contact_exists:
			return Response({"detail": "Vous devez être en contact avec cet utilisateur"}, status=status.HTTP_403_FORBIDDEN)
		
		# Chercher une conversation directe existante
		conv = Conversation.objects.filter(
			type="direct",
			memberships__user=request.user
		).filter(
			memberships__user=target_user
		).distinct().first()
		
		if not conv:
			conv = Conversation.objects.create(type="direct", created_by=request.user)
			Membership.objects.bulk_create([
				Membership(conversation=conv, user=request.user, is_admin=True),
				Membership(conversation=conv, user=target_user, is_admin=False),
			])
		
		return Response(ConversationSerializer(conv).data, status=status.HTTP_201_CREATED)

	@action(detail=False, methods=["get"], url_path="by-type")
	def conversations_by_type(self, request):
		"""Lister les conversations par type (direct/group)"""
		conv_type = request.query_params.get("type", "direct")
		conversations = Conversation.objects.filter(
			memberships__user=request.user,
			type=conv_type
		).prefetch_related('memberships__user').distinct().order_by('-created_at')
		return Response(ConversationSerializer(conversations, many=True).data)


@api_view(['GET'])
def get_csrf_token(request):
	"""Récupérer le token CSRF"""
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

