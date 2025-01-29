import panel as pn
import httpx
from io import StringIO
import json
import urllib.parse
import os
import pika
import threading
import asyncio
import re

pn.extension()

# Configuration RabbitMQ
RABBITMQ_CONFIG = {
    'host': os.getenv('RABBITMQ_HOST', 'localhost'),
    'port': int(os.getenv('RABBITMQ_PORT', 30645)),
    'user': os.getenv('RABBITMQ_USER'),
    'password': os.getenv('RABBITMQ_PASSWORD'),
    'queue_name': os.getenv('QUEUE_NAME', 'queue_chatbot')
}

llm_endpoint: str = 'http://127.0.0.1:8001/v1/user_proxy/ask'
model_id: str = 'gpt-4o-mini'
user_id: str = 'vinh'

def rabbitmq_listener():
    # Importer pika à l'intérieur de la fonction pour éviter les problèmes de portée
    import pika
    
    credentials = pika.PlainCredentials(RABBITMQ_CONFIG['user'], RABBITMQ_CONFIG['password'])
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_CONFIG['host'], 
        port=RABBITMQ_CONFIG['port'], 
        credentials=credentials,
        virtual_host='/',
        # Ajouter des paramètres de timeout et de reconnexion
        connection_attempts=3,  # Nombre de tentatives de connexion
        socket_timeout=10,  # Timeout de socket en secondes
        heartbeat=600  # Heartbeat plus long pour éviter les déconnexions
    )
    
    def callback(ch, method, properties, body):
        try:
            message_str = body.decode('utf-8')
            
            try:
                message_data = json.loads(message_str)
            except json.JSONDecodeError:
                chat_interface.send(message_str, user="Myboun")
                return
            
            # Extraction du contenu avec une logique simple et directe
            content = (
                message_data.get('content') or 
                message_data.get('result') or 
                message_data.get('message') or 
                str(message_data)
            )
            
            # Envoyer le contenu
            chat_interface.send(content, user="Myboun")
        
        except Exception as e:
            # Gestion générique des exceptions
            print(f"Erreur lors du traitement du message : {e}")
            chat_interface.send(f"Erreur de traitement : {e}", user="Myboun")

    connection = None
    try:
        # Utiliser une boucle pour gérer les reconnexions
        while True:
            try:
                connection = pika.BlockingConnection(parameters)
                channel = connection.channel()
                
                # Déclarer la file d'attente avec des paramètres explicites
                channel.queue_declare(
                    queue=RABBITMQ_CONFIG['queue_name'], 
                    durable=True,  # Rendre la file d'attente durable
                    exclusive=False,
                    auto_delete=False
                )
                
                channel.basic_consume(
                    queue=RABBITMQ_CONFIG['queue_name'], 
                    on_message_callback=callback, 
                    auto_ack=True
                )
                
                print(f"Started listening to RabbitMQ queue: {RABBITMQ_CONFIG['queue_name']}")
                channel.start_consuming()
            
            except (pika.exceptions.AMQPConnectionError, 
                    pika.exceptions.AMQPChannelError, 
                    pika.exceptions.StreamLostError) as conn_error:
                print(f"Connexion RabbitMQ perdue : {conn_error}. Tentative de reconnexion...")
                
                # Attendre avant de réessayer
                import time
                time.sleep(5)
                
                # Continuer la boucle pour une nouvelle tentative
                continue
            
            except Exception as e:
                print(f"Erreur inattendue : {e}")
                break
    
    finally:
        # Fermer proprement la connexion si elle existe
        if connection and not connection.is_closed:
            connection.close()

# Démarrer le listener RabbitMQ dans un thread séparé
rabbitmq_thread = threading.Thread(target=rabbitmq_listener, daemon=True)
rabbitmq_thread.start()

async def callback(contents: str, user: str, instance: pn.chat.ChatInterface):
    # Vérifier si le message provient de RabbitMQ
    if user == "Myboun":
        # Si le message vient de RabbitMQ, ne rien faire d'autre
        return

    messages = instance.serialize()[1:]
    
    # Prendre le dernier message comme requête
    last_message = messages[-1]['content'] if messages else contents
    
    # Construire les paramètres de requête de manière robuste
    params = {
        'query': last_message,
        'model_id': model_id,
        'user_id': user_id
    }
    query_string = urllib.parse.urlencode(params)
    url = f"{llm_endpoint}?{query_string}"
    
    print(f"Tentative de connexion à l'URL : {url}")  # Debug print
    
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:  # Augmenter le timeout et désactiver la vérification SSL
        try:
            # Utiliser post avec un corps de requête vide
            response = await client.post(url, data='', headers={'accept': 'application/json'})
            
            print(f"Statut de la réponse : {response.status_code}")  # Debug print
            print(f"En-têtes de la réponse : {response.headers}")  # Debug print
            print(f"Contenu brut de la réponse : {response.text}")  # Debug print
            
            # Tenter de décoder le JSON
            try:
                data = response.json()
                print(f"Données JSON reçues : {data}")  # Debug print
                
                # Extraction du contenu avec une logique flexible
                content = (
                    data.get('content') or 
                    data.get('result') or 
                    data.get('message') or 
                    str(data)
                )
                
                yield content
            
            except json.JSONDecodeError as json_err:
                # Si le JSON ne peut pas être décodé, utiliser le texte brut
                error_msg = f"Erreur de décodage JSON : {json_err}. Contenu brut : {response.text}"
                print(error_msg)
                yield response.text
        
        except Exception as e:
            # Capture de toutes les exceptions possibles
            error_msg = f"Erreur de connexion complète : {type(e).__name__} - {str(e)}"
            print(error_msg)
            
            # Tenter une dernière approche : utiliser l'URL originale sans modification
            try:
                # Réessayer avec l'URL originale sans paramètres encodés
                fallback_url = f"{llm_endpoint}?query={urllib.parse.quote(last_message)}&model_id={model_id}&user_id={user_id}"
                print(f"Tentative de connexion de secours : {fallback_url}")
                
                fallback_response = await client.post(fallback_url, data='', headers={'accept': 'application/json'})
                print(f"Statut de la réponse de secours : {fallback_response.status_code}")
                
                yield fallback_response.text
            
            except Exception as fallback_err:
                final_error_msg = f"Échec de la connexion de secours : {type(fallback_err).__name__} - {str(fallback_err)}"
                print(final_error_msg)
                yield final_error_msg

def download_history():
   buf = StringIO()
   json.dump(chat_interface.serialize(), buf)
   buf.seek(0)
   return buf

file_download = pn.widgets.FileDownload(
   callback=download_history, filename="history.json"
)
header = pn.Row(pn.HSpacer(), file_download)

chat_interface = pn.chat.ChatInterface(
    callback=callback, 
    callback_user="Myboun",
    header=header
    )
chat_interface.send(
    "Bonjour", user="Myboun", respond=False
)
chat_interface.servable()