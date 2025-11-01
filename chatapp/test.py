#!/usr/bin/env python3
"""
Script de test complet pour l'application Chat
Teste: DB, Messages, WebSocket, Fichiers, Notifications
"""

import os
import sys
import django

# Configuration Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chatproject.settings')
django.setup()

from django.contrib.auth import get_user_model
from django.utils import timezone
from chat.models import Conversation, Membership, Message, Contact, GroupInvitation, Notification
from chat.consumers import ChatConsumer
from chat.notification_consumer import NotificationConsumer
from channels.db import database_sync_to_async
import asyncio

User = get_user_model()


def test_database():
    """Test des opérations de base de données"""
    print("\n=== TEST DATABASE ===")
    
    # Créer des utilisateurs de test
    try:
        user1, created1 = User.objects.get_or_create(username='testuser1', defaults={'email': 'test1@test.com'})
        user2, created2 = User.objects.get_or_create(username='testuser2', defaults={'email': 'test2@test.com'})
        print(f"✓ Utilisateurs créés/récupérés: {user1.username}, {user2.username}")
    except Exception as e:
        print(f"✗ Erreur création utilisateurs: {e}")
        return False
    
    # Créer une conversation directe
    try:
        conv, created = Conversation.objects.get_or_create(
            type='direct',
            created_by=user1,
            defaults={'name': ''}
        )
        Membership.objects.get_or_create(conversation=conv, user=user1)
        Membership.objects.get_or_create(conversation=conv, user=user2)
        print(f"✓ Conversation créée/récupérée: {conv.id}")
    except Exception as e:
        print(f"✗ Erreur création conversation: {e}")
        return False
    
    # Créer des messages
    try:
        msg1 = Message.objects.create(conversation=conv, sender=user1, content="Test message 1")
        msg2 = Message.objects.create(conversation=conv, sender=user2, content="Test message 2")
        print(f"✓ Messages créés: {msg1.id}, {msg2.id}")
    except Exception as e:
        print(f"✗ Erreur création messages: {e}")
        return False
    
    # Créer un contact
    try:
        contact, created = Contact.objects.get_or_create(
            from_user=user1,
            to_user=user2,
            defaults={'status': 'accepted'}
        )
        print(f"✓ Contact créé/récupéré: {contact.id}, status: {contact.status}")
    except Exception as e:
        print(f"✗ Erreur création contact: {e}")
        return False
    
    # Créer une notification
    try:
        notif = Notification.objects.create(
            user=user2,
            type='message',
            title='Test notification',
            content='Ceci est un test',
            conversation=conv
        )
        print(f"✓ Notification créée: {notif.id}")
    except Exception as e:
        print(f"✗ Erreur création notification: {e}")
        return False
    
    print("✓ Tous les tests de base de données sont passés!")
    return True


def test_conversation_operations():
    """Test des opérations sur les conversations"""
    print("\n=== TEST CONVERSATIONS ===")
    
    try:
        user1 = User.objects.get(username='testuser1')
        
        # Créer une conversation de groupe
        group_conv = Conversation.objects.create(
            type='group',
            name='Test Group',
            created_by=user1
        )
        Membership.objects.create(conversation=group_conv, user=user1, is_admin=True)
        print(f"✓ Groupe créé: {group_conv.id}")
        
        # Récupérer les conversations de l'utilisateur
        user_convs = Conversation.objects.filter(memberships__user=user1).distinct()
        print(f"✓ Conversations de {user1.username}: {user_convs.count()}")
        
        print("✓ Tests de conversations passés!")
        return True
    except Exception as e:
        print(f"✗ Erreur tests conversations: {e}")
        return False


def test_websocket_consumer():
    """Test du consumer WebSocket"""
    print("\n=== TEST WEBSOCKET CONSUMER ===")
    
    try:
        from asgiref.sync import async_to_sync
        
        user1 = User.objects.get(username='testuser1')
        conv = Conversation.objects.filter(memberships__user=user1).first()
        
        if not conv:
            print("✗ Aucune conversation trouvée")
            return False
        
        # Créer le consumer et tester
        consumer = ChatConsumer()
        
        # Test la création de notifications de manière synchrone
        async_to_sync(consumer._create_message_notifications)(
            sender_id=user1.id,
            conversation_id=conv.id,
            sender_username=user1.username,
            content="Test WebSocket message"
        )
        print("✓ Notifications créées via WebSocket")
        
        print("✓ Tests WebSocket passés!")
        return True
    except Exception as e:
        print(f"✗ Erreur tests WebSocket: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_notification_consumer():
    """Test du consumer de notifications"""
    print("\n=== TEST NOTIFICATION CONSUMER ===")
    
    try:
        user1 = User.objects.get(username='testuser1')
        
        # Simuler un scope WebSocket
        scope = {
            'user': user1
        }
        
        # Créer le consumer
        consumer = NotificationConsumer()
        consumer.scope = scope
        
        print("✓ NotificationConsumer créé")
        
        # Vérifier les notifications
        notifs = Notification.objects.filter(user=user1, read=False)
        print(f"✓ Notifications non lues: {notifs.count()}")
        
        print("✓ Tests notification consumer passés!")
        return True
    except Exception as e:
        print(f"✗ Erreur tests notification consumer: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_views():
    """Test des vues"""
    print("\n=== TEST VUES ===")
    
    try:
        from chat.views import ConversationViewSet
        from chat.notification_views import NotificationViewSet
        
        user1 = User.objects.get(username='testuser1')
        conv = Conversation.objects.filter(memberships__user=user1).first()
        
        # Créer une requête mock
        class MockRequest:
            user = user1
        
        request = MockRequest()
        
        # Test ConversationViewSet
        cvs = ConversationViewSet()
        cvs.request = request
        queryset = cvs.get_queryset()
        print(f"✓ ConversationViewSet - conversations: {queryset.count()}")
        
        # Test NotificationViewSet
        nvs = NotificationViewSet()
        nvs.request = request
        notif_queryset = nvs.get_queryset()
        print(f"✓ NotificationViewSet - notifications: {notif_queryset.count()}")
        
        print("✓ Tests de vues passés!")
        return True
    except Exception as e:
        print(f"✗ Erreur tests vues: {e}")
        import traceback
        traceback.print_exc()
        return False


def cleanup_test_data():
    """Nettoyer les données de test"""
    print("\n=== NETTOYAGE ===")
    
    try:
        User.objects.filter(username__startswith='testuser').delete()
        print("✓ Données de test nettoyées")
        return True
    except Exception as e:
        print(f"✗ Erreur nettoyage: {e}")
        return False


def main():
    """Fonction principale"""
    print("=" * 50)
    print("TESTS DE L'APPLICATION CHAT")
    print("=" * 50)
    
    results = []
    
    # Tests
    results.append(("Database", test_database()))
    results.append(("Conversations", test_conversation_operations()))
    results.append(("WebSocket Consumer", test_websocket_consumer()))
    results.append(("Notification Consumer", test_notification_consumer()))
    results.append(("Views", test_views()))
    
    # Résumé
    print("\n" + "=" * 50)
    print("RÉSUMÉ DES TESTS")
    print("=" * 50)
    
    for test_name, result in results:
        status = "✓ PASSÉ" if result else "✗ ÉCHEC"
        print(f"{test_name}: {status}")
    
    total = len(results)
    passed = sum(1 for _, result in results if result)
    
    print(f"\nTotal: {passed}/{total} tests passés")
    
    if passed == total:
        print("🎉 TOUS LES TESTS SONT PASSÉS!")
    else:
        print("⚠️  CERTAINS TESTS ONT ÉCHOUÉ")
    
    # Nettoyer (optionnel)
    # cleanup_test_data()
    
    return passed == total


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)

