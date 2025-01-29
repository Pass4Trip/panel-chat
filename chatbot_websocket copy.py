import panel as pn
import asyncio
import json
import websockets
import os
import threading
from io import StringIO
import urllib.parse

# Configuration WebSocket
WEBSOCKET_CONFIG = {
    'host': os.getenv('WEBSOCKET_HOST', 'localhost'),  
    'port': int(os.getenv('WEBSOCKET_PORT', 8001)),       
    'path': '/v1/ws'
}

model_id: str = 'gpt-4o-mini'
user_id: str = 'vinh'

class WebSocketClient:
    def __init__(self, user_id, host='localhost', port=8001, path='/v1/ws'):
        self.user_id = user_id
        self.host = host
        self.port = port
        self.path = path
        self.uri = f"ws://{host}:{port}{path}?user_id={urllib.parse.quote(user_id)}"
        self.websocket = None
        self.message_queue = asyncio.Queue()
        self.connected = False
        self._connect_task = None
        print(f"WebSocket URI initialisée : {self.uri}")

    async def connect(self):
        if self._connect_task and not self._connect_task.done():
            return await self._connect_task
        
        self._connect_task = asyncio.create_task(self._connect())
        return await self._connect_task

    async def _connect(self):
        try:
            print(f"Tentative de connexion à : {self.uri}")
            self.websocket = await websockets.connect(
                self.uri,
                extra_headers={
                    'User-Agent': 'Panel WebSocket Client',
                    'Accept': 'application/json'
                },
                ping_interval=20,
                ping_timeout=20
            )
            self.connected = True
            print("✅ Connexion WebSocket établie")
            return True
        except Exception as e:
            print(f"❌ Erreur de connexion WebSocket : {type(e).__name__} - {str(e)}")
            self.connected = False
            return False

    async def send_message(self, message: str):
        if not self.connected:
            success = await self.connect()
            if not success:
                return None

        try:
            await self.websocket.send(json.dumps({
                "query": message,
                "user_id": self.user_id,
                "model_id": model_id
            }))
            response = await self.websocket.recv()
            return json.loads(response)
        except Exception as e:
            print(f"❌ Erreur lors de l'envoi du message : {type(e).__name__} - {str(e)}")
            self.connected = False
            return None

    async def close(self):
        if self.websocket:
            await self.websocket.close()
            self.connected = False

# Initialisation du client WebSocket
websocket_client = WebSocketClient(
    user_id=user_id, 
    host=WEBSOCKET_CONFIG['host'], 
    port=WEBSOCKET_CONFIG['port'],
    path=WEBSOCKET_CONFIG['path']
)

# Fonction de callback pour le chat
async def callback(contents: str, user: str, instance: pn.chat.ChatInterface):
    """Callback pour gérer les messages du chat"""
    try:
        # Envoyer le message et attendre la réponse
        response = await websocket_client.send_message(contents)
        
        if response and isinstance(response, dict):
            if response.get('status') == 'success':
                # Extraire la réponse du message
                response_data = response.get('data', {})
                if isinstance(response_data, dict):
                    response_content = response_data.get('response', '')
                else:
                    response_content = str(response_data)
                
                if response_content:
                    instance.send(response_content, user='Assistant')
                else:
                    instance.send("Désolé, je n'ai pas de réponse à fournir.", user='Assistant')
            else:
                error_msg = response.get('message', 'Erreur inconnue')
                instance.send(f"❌ Erreur : {error_msg}", user='Système')
        else:
            instance.send("❌ Erreur : Format de réponse invalide", user='Système')
    
    except Exception as e:
        print(f"Erreur dans le callback : {str(e)}")
        instance.send(f"❌ Erreur de communication : {str(e)}", user='Système')

# Fonction pour télécharger l'historique
def download_history():
    """Télécharge l'historique de la conversation"""
    buffer = StringIO()
    for msg in chat_interface.objects:
        buffer.write(f"{msg.user}: {msg.object}\n")
    return buffer.getvalue()

# Initialisation de l'interface de chat
chat_interface = pn.chat.ChatInterface(
    callback=callback,
    callback_user="Myboun",
    show_rerun=False,
    show_undo=False,
    show_clear=True,
    sizing_mode='stretch_both',
    height=600
)

# Bouton de téléchargement
download_button = pn.widgets.FileDownload(
    callback=download_history,
    filename='chat_history.txt',
    label="Télécharger l'historique",
    button_type='primary'
)

# Switch d'agent
agent_options = ['user_proxy', 'orchestrator']
agent_switch = pn.widgets.Select(
    name='Agent actif',
    options=agent_options,
    value='user_proxy'
)

async def on_agent_switch(event):
    """Gère le changement d'agent"""
    new_agent = event.new
    try:
        switch_result = await websocket_client.send_message(f"switch_agent {new_agent}")
        if switch_result and switch_result.get('status') == 'success':
            chat_interface.send(f"✅ Passage à l'agent {new_agent}", user="Système")
        else:
            error_msg = switch_result.get('message', 'Erreur inconnue') if switch_result else 'Pas de réponse du serveur'
            chat_interface.send(f"❌ Erreur lors du changement d'agent : {error_msg}", user="Système")
    except Exception as e:
        chat_interface.send(f"❌ Erreur lors du changement d'agent : {str(e)}", user="Système")

agent_switch.param.watch(on_agent_switch, 'value')

# Mise en page
header = pn.Row(
    pn.pane.Markdown('# 💬 Chat Phidata'),
    agent_switch,
    download_button
)

# Template
template = pn.template.FastListTemplate(
    title='Chat Phidata',
    header=header,
    main=[chat_interface],
    accent_base_color="#88d8b0",
    header_background="#88d8b0",
)

# Servir l'application
template.servable()
