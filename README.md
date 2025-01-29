# Myboun Panel Chat

## Description
Application de chat basée sur Panel, utilisant WebSocket pour la communication avec un backend intelligent.

## Fonctionnalités
- Interface de chat interactive
- Changement dynamique d'agent
- Connexion WebSocket sécurisée
- Téléchargement de l'historique de conversation

## Prérequis
- Python 3.10+
- UV (gestionnaire de paquets)

## Installation
```bash
uv pip install -r requirements.txt
```

## Lancement
```bash
panel serve chatbot_websocket.py
```

## Configuration
Configurez les variables d'environnement pour personnaliser :
- `WEBSOCKET_HOST`
- `WEBSOCKET_PORT`
- `WEBSOCKET_PATH`
