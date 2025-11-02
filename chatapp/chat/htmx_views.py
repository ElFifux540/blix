import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login
from django.contrib.auth.views import LoginView
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from .models import Conversation, Message, Membership
from .serializers import MessageSerializer

logger = logging.getLogger(__name__)


@require_http_methods(["GET", "POST"])
def htmx_login_view(request):
    """Vue de login personnalisée avec support HTMX"""
    logger.info(f"[HTMX-LOGIN] Requête {request.method} pour login")
    
    if request.user.is_authenticated:
        logger.info(f"[HTMX-LOGIN] User déjà authentifié: {request.user.username}")
        if request.headers.get('HX-Request'):
            return HttpResponse('<script>window.location.href = "/";</script>')
        return redirect('/')
    
    if request.method == 'POST':
        logger.info(f"[HTMX-LOGIN] Tentative de connexion")
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        if not username or not password:
            logger.warning(f"[HTMX-LOGIN] Identifiants manquants")
            error_html = '<div class="errorlist">Veuillez remplir tous les champs.</div>'
            if request.headers.get('HX-Request'):
                return HttpResponse(error_html, status=400)
            messages.error(request, "Veuillez remplir tous les champs.")
            return render(request, 'registration/login.html', {'form': {}})
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            logger.info(f"[HTMX-LOGIN] Authentification réussie pour user {username}")
            login(request, user)
            
            # Si c'est une requête HTMX, retourner un script pour rediriger
            if request.headers.get('HX-Request'):
                return HttpResponse('<script>window.location.href = "/";</script>')
            
            next_url = request.GET.get('next', '/')
            return redirect(next_url)
        else:
            logger.warning(f"[HTMX-LOGIN] Authentification échouée pour username {username}")
            error_html = '<div class="errorlist">Identifiants invalides. Réessaie.</div>'
            if request.headers.get('HX-Request'):
                return HttpResponse(error_html, status=400)
            messages.error(request, "Identifiants invalides. Réessaie.")
    
    # GET request ou POST avec erreur
    logger.info(f"[HTMX-LOGIN] Affichage formulaire de login")
    return render(request, 'registration/login.html')


@require_http_methods(["GET"])
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def htmx_load_messages(request):
    """Charger les messages d'une conversation via HTMX"""
    conversation_id = request.GET.get('conversation_id')
    
    if not conversation_id:
        logger.warning(f"[HTMX-MESSAGES] conversation_id manquant")
        return HttpResponse('<div class="errorlist">Aucune conversation sélectionnée</div>', status=400)
    
    try:
        conversation = get_object_or_404(Conversation, pk=conversation_id)
        logger.info(f"[HTMX-MESSAGES] User {request.user.username} charge messages de conversation {conversation_id}")
        
        # Vérifier que l'utilisateur est membre
        if not Membership.objects.filter(conversation=conversation, user=request.user).exists():
            logger.warning(f"[HTMX-MESSAGES] Accès refusé: user {request.user.id} n'est pas membre")
            return HttpResponse('<div class="errorlist">Accès refusé</div>', status=403)
        
        messages = Message.objects.filter(conversation=conversation).select_related("sender").order_by('created_at')[:200]
        logger.info(f"[HTMX-MESSAGES] {len(messages)} messages chargés")
        
        # Construire le HTML des messages
        html_content = ''
        prev_msg = None
        for msg in messages:
            sender_id = msg.sender.id if msg.sender else None
            is_own = sender_id == request.user.id
            sender_name = msg.sender.username if msg.sender else 'Utilisateur'
            
            # Gérer l'affichage de la date (changement de jour)
            msg_date = msg.created_at
            date_html = ''
            if not prev_msg:
                date_html = f'<div style="text-align:center; margin:10px 0; color:#8e9297; font-size:11px;">{msg_date.strftime("%d/%m/%Y")}</div>'
            else:
                prev_msg_date = prev_msg.created_at
                if msg_date.date() != prev_msg_date.date():
                    date_html = f'<div style="text-align:center; margin:10px 0; color:#8e9297; font-size:11px;">{msg_date.strftime("%d/%m/%Y")}</div>'
            
            # Gérer les attachments
            attachment_html = ''
            if msg.attachment:
                url = msg.attachment.url
                filename = msg.attachment.name.split('/')[-1]
                if any(filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg']):
                    attachment_html = f'<div style="margin-top:6px;"><img src="{url}" alt="fichier" style="max-width: 320px; border-radius: 6px;" /></div>'
                else:
                    attachment_html = f'<div style="margin-top:6px;"><a href="{url}" target="_blank" download rel="noopener">📎 Télécharger {filename}</a></div>'
            
            html_content += f'''
                <div class="message {'own' if is_own else 'other'}">
                    {date_html}
                    <strong>{sender_name}:</strong> {msg.content or ''}
                    {attachment_html}
                    <br><small>{msg.created_at.strftime("%H:%M:%S")}</small>
                </div>
            '''
            prev_msg = msg
        
        # Ajouter un script pour scroller en bas après le chargement
        html_content += '<script>setTimeout(() => { const container = document.getElementById("chat-messages"); if (container) container.scrollTop = container.scrollHeight; }, 100);</script>'
        
        return HttpResponse(html_content)
        
    except Exception as e:
        logger.error(f"[HTMX-MESSAGES] Erreur: {e}", exc_info=True)
        return HttpResponse('<div class="errorlist">Erreur lors du chargement des messages</div>', status=500)


@require_http_methods(["POST"])
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def htmx_send_message(request):
    """Envoyer un message via HTMX"""
    conversation_id = request.POST.get('conversation_id')
    content = (request.POST.get('content') or '').strip()
    
    if not conversation_id:
        logger.warning(f"[HTMX-SEND] conversation_id manquant")
        return HttpResponse('<div class="errorlist">Aucune conversation sélectionnée</div>', status=400)
    
    if not content:
        logger.warning(f"[HTMX-SEND] Message vide")
        return HttpResponse('<div class="errorlist">Le message ne peut pas être vide</div>', status=400)
    
    try:
        conversation = get_object_or_404(Conversation, pk=conversation_id)
        logger.info(f"[HTMX-SEND] User {request.user.username} envoie message dans conversation {conversation_id}")
        
        # Vérifier que l'utilisateur est membre
        if not Membership.objects.filter(conversation=conversation, user=request.user).exists():
            logger.warning(f"[HTMX-SEND] Accès refusé: user {request.user.id} n'est pas membre")
            return HttpResponse('<div class="errorlist">Accès refusé</div>', status=403)
        
        # Créer le message
        message = Message.objects.create(
            conversation=conversation,
            sender=request.user,
            content=content
        )
        logger.info(f"[HTMX-SEND] Message créé avec ID: {message.id}")
        
        # Créer des notifications pour les autres membres de la conversation
        from .notification_views import create_message_notification
        other_members = Membership.objects.filter(conversation=conversation).exclude(user=request.user)
        logger.info(f"[HTMX-SEND] Création notifications pour {other_members.count()} autres membres")
        for membership in other_members:
            create_message_notification(
                user=membership.user,
                conversation=conversation,
                sender_username=request.user.username,
                message_content=content or "Fichier partagé"
            )
        logger.info(f"[HTMX-SEND] Notifications créées")
        
        # Ne pas retourner de HTML - laisser WebSocket gérer l'affichage pour tous
        # Diffuser via WebSocket (sera affiché pour tous les utilisateurs, y compris l'expéditeur)
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"chat_{conversation.id}",
            {"type": "chat_message", "message": MessageSerializer(message).data},
        )
        logger.info(f"[HTMX-SEND] Message diffusé via WebSocket")
        
        # Script pour juste vider le champ de saisie
        script = '''
        <script>
            (function() {
                const input = document.getElementById("message-input");
                if (input) input.value = "";
            })();
        </script>
        '''
        return HttpResponse(script)
        
    except Exception as e:
        logger.error(f"[HTMX-SEND] Erreur: {e}", exc_info=True)
        return HttpResponse('<div class="errorlist">Erreur lors de l\'envoi du message</div>', status=500)

