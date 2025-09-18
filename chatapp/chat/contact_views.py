from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from .models import Contact, GroupInvitation, Conversation, Membership
from .serializers import ContactSerializer, GroupInvitationSerializer, ConversationSerializer

User = get_user_model()


@method_decorator(csrf_exempt, name="dispatch")
class ContactViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ContactSerializer

    def get_queryset(self):
        return Contact.objects.filter(
            Q(from_user=self.request.user) | Q(to_user=self.request.user)
        ).distinct()

    @action(detail=False, methods=["post"], url_path="send-request")
    def send_request(self, request):
        """Envoyer une demande de contact"""
        username = request.data.get("username")
        if not username:
            return Response({"detail": "username requis"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            target_user = User.objects.get(username=username)
        except User.DoesNotExist:
            return Response({"detail": "Utilisateur introuvable"}, status=status.HTTP_404_NOT_FOUND)
        
        if target_user == request.user:
            return Response({"detail": "Impossible de s'ajouter soi-même"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Vérifier si une demande existe déjà
        existing = Contact.objects.filter(
            Q(from_user=request.user, to_user=target_user) | 
            Q(from_user=target_user, to_user=request.user)
        ).first()
        
        if existing:
            return Response({"detail": "Une demande existe déjà"}, status=status.HTTP_400_BAD_REQUEST)
        
        contact = Contact.objects.create(
            from_user=request.user,
            to_user=target_user,
            status='pending'
        )
        return Response(ContactSerializer(contact).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="accept")
    def accept(self, request, pk=None):
        """Accepter une demande de contact"""
        contact = self.get_object()
        if contact.to_user != request.user:
            return Response({"detail": "Accès refusé"}, status=status.HTTP_403_FORBIDDEN)
        
        contact.status = 'accepted'
        contact.save()
        return Response(ContactSerializer(contact).data)

    @action(detail=True, methods=["post"], url_path="decline")
    def decline(self, request, pk=None):
        """Refuser une demande de contact"""
        contact = self.get_object()
        if contact.to_user != request.user:
            return Response({"detail": "Accès refusé"}, status=status.HTTP_403_FORBIDDEN)
        
        contact.status = 'blocked'
        contact.save()
        return Response(ContactSerializer(contact).data)

    @action(detail=False, methods=["get"], url_path="accepted")
    def accepted_contacts(self, request):
        """Liste des contacts acceptés"""
        contacts = Contact.objects.filter(
            Q(from_user=request.user, status='accepted') | 
            Q(to_user=request.user, status='accepted')
        ).distinct()
        return Response(ContactSerializer(contacts, many=True).data)

    @action(detail=False, methods=["get"], url_path="pending")
    def pending_requests(self, request):
        """Demandes en attente reçues"""
        contacts = Contact.objects.filter(
            to_user=request.user,
            status='pending'
        )
        return Response(ContactSerializer(contacts, many=True).data)

    @action(detail=True, methods=["delete"], url_path="delete")
    def delete_contact(self, request, pk=None):
        """Supprimer un contact"""
        contact = self.get_object()
        
        # Vérifier que l'utilisateur fait partie du contact
        if contact.from_user != request.user and contact.to_user != request.user:
            return Response({"detail": "Accès refusé"}, status=status.HTTP_403_FORBIDDEN)
        
        contact.delete()
        return Response({"detail": "Contact supprimé"}, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name="dispatch")
class GroupInvitationViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = GroupInvitationSerializer

    def get_queryset(self):
        return GroupInvitation.objects.filter(to_user=self.request.user)

    @action(detail=False, methods=["post"], url_path="invite")
    def invite_user(self, request):
        """Inviter un utilisateur dans un groupe"""
        conversation_id = request.data.get("conversation_id")
        username = request.data.get("username")
        
        if not conversation_id or not username:
            return Response({"detail": "conversation_id et username requis"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            conversation = Conversation.objects.get(pk=conversation_id)
            target_user = User.objects.get(username=username)
        except (Conversation.DoesNotExist, User.DoesNotExist):
            return Response({"detail": "Conversation ou utilisateur introuvable"}, status=status.HTTP_404_NOT_FOUND)
        
        # Vérifier que l'utilisateur est admin du groupe
        membership = Membership.objects.filter(
            conversation=conversation,
            user=request.user,
            is_admin=True
        ).first()
        
        if not membership:
            return Response({"detail": "Seuls les admins peuvent inviter"}, status=status.HTTP_403_FORBIDDEN)
        
        # Vérifier si l'utilisateur est déjà membre
        if Membership.objects.filter(conversation=conversation, user=target_user).exists():
            return Response({"detail": "L'utilisateur est déjà membre"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Vérifier si une invitation existe déjà
        if GroupInvitation.objects.filter(conversation=conversation, to_user=target_user).exists():
            return Response({"detail": "Une invitation existe déjà"}, status=status.HTTP_400_BAD_REQUEST)
        
        invitation = GroupInvitation.objects.create(
            conversation=conversation,
            from_user=request.user,
            to_user=target_user,
            status='pending'
        )
        return Response(GroupInvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="accept")
    def accept_invitation(self, request, pk=None):
        """Accepter une invitation de groupe"""
        invitation = self.get_object()
        if invitation.to_user != request.user:
            return Response({"detail": "Accès refusé"}, status=status.HTTP_403_FORBIDDEN)
        
        invitation.status = 'accepted'
        invitation.save()
        
        # Ajouter l'utilisateur au groupe
        Membership.objects.get_or_create(
            conversation=invitation.conversation,
            user=request.user,
            defaults={'is_admin': False}
        )
        
        return Response(GroupInvitationSerializer(invitation).data)

    @action(detail=True, methods=["post"], url_path="decline")
    def decline_invitation(self, request, pk=None):
        """Refuser une invitation de groupe"""
        invitation = self.get_object()
        if invitation.to_user != request.user:
            return Response({"detail": "Accès refusé"}, status=status.HTTP_403_FORBIDDEN)
        
        invitation.status = 'declined'
        invitation.save()
        return Response(GroupInvitationSerializer(invitation).data)

    @action(detail=False, methods=["get"], url_path="pending")
    def pending_invitations(self, request):
        """Invitations en attente"""
        invitations = GroupInvitation.objects.filter(
            to_user=request.user,
            status='pending'
        )
        return Response(GroupInvitationSerializer(invitations, many=True).data)
