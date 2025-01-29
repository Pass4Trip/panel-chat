import panel as pn
import httpx
from io import StringIO
import json
import urllib.parse
import os
import pika
import threading
import asyncio

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
    credentials = pika.PlainCredentials(RABBITMQ_CONFIG['user'], RABBITMQ_CONFIG['password'])
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_CONFIG['host'], 
        port=RABBITMQ_CONFIG['port'], 
        credentials=credentials,
        virtual_host='/'
    )
    
    def callback(ch, method, properties, body):
        try:
            message_str = body.decode('utf-8')
            
            try:
                message_data = json.loads(message_str)
            except json.JSONDecodeError:
                chat_interface.send(message_str, user="Myboun")
                return
            
            # Vérifier si le message contient un résultat
            if 'result' in message_data and isinstance(message_data['result'], dict):
                content = message_data['result'].get('content')
                
                if content:
                    chat_interface.send(content, user="Myboun")
                else:
                    chat_interface.send(str(message_data), user="Myboun")
            elif 'message_type' in message_data:
                content = (
                    message_data.get('result', {}).get('content') or 
                    message_data.get('metadata', {}).get('original_request') or 
                    str(message_data)
                )
                
                chat_interface.send(content, user="Myboun")
            else:
                chat_interface.send(str(message_data), user="Myboun")
        except Exception as e:
            pass

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
    
    except pika.exceptions.AMQPConnectionError as e:
        print(f"Erreur de connexion à RabbitMQ : {e}")
    except pika.exceptions.ChannelClosedByBroker as e:
        print(f"Erreur de canal RabbitMQ : {e}")
    except Exception as e:
        print(f"Erreur inattendue lors de la connexion à RabbitMQ : {e}")

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
    
    # Construire les données de requête
    data = {
        'query': last_message,
        'model_id': model_id,
        'user_id': user_id
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(llm_endpoint, json=data, headers={'accept': 'application/json'})
            response.raise_for_status()
            
            # Supposant que la réponse est un JSON avec un champ 'result'
            data = response.json()
            message = data.get('result', 'Pas de réponse')
            
            yield message
        except httpx.RequestError as e:
            yield f"Erreur de connexion au service LLM : {e}"
        except Exception as e:
            yield f"Une erreur inattendue s'est produite : {e}"

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