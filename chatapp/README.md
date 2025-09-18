# ChatApp - Application de Chat Django

## Configuration des Variables d'Environnement

Ce projet utilise des variables d'environnement pour sécuriser les informations confidentielles.

### Installation

1. Clonez le repository
2. Installez les dépendances :
   ```bash
   pip install -r requirements.txt
   ```

3. Copiez le fichier d'exemple de configuration :
   ```bash
   cp .env.example .env
   ```

4. Modifiez le fichier `.env` avec vos propres valeurs :
   ```bash
   nano .env
   ```

### Variables d'Environnement

Le fichier `.env` contient les variables suivantes :

- `SECRET_KEY` : Clé secrète Django (obligatoire)
- `DEBUG` : Mode debug (True/False)
- `ALLOWED_HOSTS` : Domaines autorisés (séparés par des virgules)
- `CSRF_TRUSTED_ORIGINS` : URLs de confiance CSRF (séparées par des virgules)
- `CSRF_COOKIE_DOMAIN` : Domaine des cookies CSRF
- `SESSION_COOKIE_DOMAIN` : Domaine des cookies de session
- `REDIS_HOST` : Adresse du serveur Redis
- `REDIS_PORT` : Port du serveur Redis
- `WEBSOCKET_ORIGINS` : Origines WebSocket autorisées (séparées par des virgules)

### Sécurité

⚠️ **IMPORTANT** : 
- Le fichier `.env` est dans `.gitignore` et ne sera pas versionné
- Ne partagez jamais votre fichier `.env` en production
- Utilisez des valeurs sécurisées pour `SECRET_KEY` en production
- Changez `DEBUG=False` en production

### Démarrage

```bash
python3 manage.py runserver
```

### Structure des Fichiers

- `.env` : Variables d'environnement (non versionné)
- `.env.example` : Exemple de configuration (versionné)
- `.gitignore` : Fichiers à ignorer par Git
