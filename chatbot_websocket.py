import param
import panel as pn
import asyncio
import json
import websockets
import os
import threading
import urllib.parse
from io import StringIO

# Configuration WebSocket
WEBSOCKET_CONFIG = {
    'host': os.getenv('WEBSOCKET_HOST', 'localhost'),  
    'port': int(os.getenv('WEBSOCKET_PORT', 8001)),       
    'path': '/v1/ws'
}

model_id: str = 'gpt-4o-mini'
user_id: str = 'vinh'

# Statut de connexion personnalisé
class ConnectionStatusIndicator(pn.widgets.Widget):
    """Indicateur de statut de connexion personnalisé"""
    value = param.Boolean(default=False)
    
    def __init__(self, **params):
        super().__init__(**params)
        self._status_div = pn.pane.HTML(
            self._get_status_html(),
            height=30,
            width=150
        )
    
    def _get_status_html(self):
        """Générer le HTML pour l'indicateur"""
        color = 'green' if self.value else 'red'
        status_text = 'Connecté' if self.value else 'Déconnecté'
        return f"""
        <div style="
            display: flex; 
            align-items: center; 
            padding: 5px; 
            border-radius: 5px; 
            background-color: {color}; 
            color: white;
            font-weight: bold;
        ">
            🔌 {status_text}
        </div>
        """
    
    def _update_status(self, event=None):
        """Mettre à jour l'affichage du statut"""
        self._status_div.object = self._get_status_html()
    
    def __panel__(self):
        """Méthode requise pour les widgets Panel"""
        self.param.watch(self._update_status, 'value')
        return self._status_div
    
    def _get_model(self, doc, comm=None, **kwargs):
        """Implémentation requise pour les widgets Panel"""
        from bokeh.models import Div
        from bokeh.io import curdoc
        
        color = 'green' if self.value else 'red'
        status_text = 'Connecté' if self.value else 'Déconnecté'
        
        div = Div(text=f"""
        <div style="
            display: flex; 
            align-items: center; 
            padding: 5px; 
            border-radius: 5px; 
            background-color: {color}; 
            color: white;
            font-weight: bold;
        ">
            🔌 {status_text}
        </div>
        """, height=30, width=150)
        
        return div
    
    def _update_model(self, model, old, new):
        """Mettre à jour le modèle Bokeh"""
        color = 'green' if new else 'red'
        status_text = 'Connecté' if new else 'Déconnecté'
        
        model.text = f"""
        <div style="
            display: flex; 
            align-items: center; 
            padding: 5px; 
            border-radius: 5px; 
            background-color: {color}; 
            color: white;
            font-weight: bold;
        ">
            🔌 {status_text}
        </div>
        """

# Créer l'indicateur de connexion
connection_status = ConnectionStatusIndicator(name='🔌 Connexion')

def update_connection_status(is_connected: bool):
    """Met à jour le statut de connexion"""
    connection_status.value = is_connected

class WebSocketClient:
    def __init__(self, user_id, host='localhost', port=8001, path='/v1/ws'):
        self.user_id = user_id
        self.host = host
        self.port = port
        self.path = path
        self.uri = f"ws://{host}:{port}{path}?user_id={urllib.parse.quote(user_id)}"
        self.websocket = None
        self.connected = False
        self._connect_task = None
        self._session_id = None
        print(f"WebSocket URI initialisée : {self.uri}")

    async def connect(self):
        if self.connected:
            return True
            
        if self._connect_task and not self._connect_task.done():
            return await self._connect_task
        
        self._connect_task = asyncio.create_task(self._connect())
        return await self._connect_task

    async def _connect(self):
        try:
            print(f"Tentative de connexion à : {self.uri}")
            self.websocket = await websockets.connect(
                self.uri,
                ping_interval=20,
                ping_timeout=20
            )
            self.connected = True
            update_connection_status(True)
            print("✅ Connexion WebSocket établie")
            
            # Recevoir et traiter le message de connexion
            connection_response = await self.websocket.recv()
            connection_data = json.loads(connection_response)
            
            if connection_data.get('status') == 'success':
                self._session_id = connection_data.get('data', {}).get('session_id')
                print(f"📡 Session ID obtenu : {self._session_id}")
            
            # Lancer une tâche pour surveiller la connexion
            asyncio.create_task(self._monitor_connection())
            
            return True
        except Exception as e:
            print(f"❌ Erreur de connexion WebSocket : {type(e).__name__} - {str(e)}")
            self.connected = False
            update_connection_status(False)
            return False

    async def _monitor_connection(self):
        """Surveiller en continu l'état de la connexion"""
        try:
            while self.connected:
                try:
                    # Envoyer un ping
                    await self.websocket.ping()
                    await asyncio.sleep(15)  # Vérifier toutes les 15 secondes
                except websockets.exceptions.ConnectionClosed:
                    print("❌ Connexion WebSocket fermée de manière inattendue")
                    self.connected = False
                    update_connection_status(False)
                    await self.connect()
                    break
        except Exception as e:
            print(f"❌ Erreur lors de la surveillance de la connexion : {str(e)}")

    async def send_message(self, message: str):
        if not self.connected:
            success = await self.connect()
            if not success:
                return None

        try:
            # Préparer le message avec les informations de session
            message_payload = {
                "query": message,
                "user_id": self.user_id,
                "model_id": model_id
            }
            
            # Ajouter l'ID de session si disponible
            if self._session_id:
                message_payload["session_id"] = self._session_id
            
            await self.websocket.send(json.dumps(message_payload))
            
            # Boucle pour gérer les messages de ping
            while True:
                response = await self.websocket.recv()
                response_data = json.loads(response)
                
                # Ignorer les messages de ping
                if isinstance(response_data, dict) and response_data.get('type') == 'ping':
                    print("🏓 Message ping reçu, en attente d'une réponse valide")
                    continue
                
                # Retourner la première réponse non-ping
                return response_data
        
        except websockets.exceptions.ConnectionClosed:
            print("❌ Connexion perdue, tentative de reconnexion...")
            self.connected = False
            update_connection_status(False)
            await self.connect()
            return await self.send_message(message)
        except Exception as e:
            print(f"❌ Erreur lors de l'envoi du message : {type(e).__name__} - {str(e)}")
            self.connected = False
            update_connection_status(False)
            return None

    async def close(self):
        if self.websocket:
            await self.websocket.close()
            self.connected = False
            update_connection_status(False)
            self._session_id = None

async def callback(contents: str, user: str, instance: pn.chat.ChatInterface):
    """Callback pour gérer les messages du chat"""
    try:
        # Journalisation détaillée
        print(f"📨 Message reçu - Contenu: {contents}, Utilisateur: {user}")

        # Ne pas traiter les messages système ou assistant
        if user in ['Système', 'Assistant', '🤖 Assistant']:
            return

        # Indiquer que le message est en cours de traitement
        loading_message = instance.send(
            "⏳ Traitement en cours...", 
            user='💭 Système',
            respond=False
        )

        # Envoyer le message et attendre la réponse
        response = await websocket_client.send_message(contents)
        print(f"🔬 Réponse reçue : {response}")  # Debug détaillé

        # Supprimer le message de chargement
        instance.objects = [msg for msg in instance.objects if msg != loading_message]
        
        # Vérification de la réponse
        if not response or not isinstance(response, dict):
            instance.send(
                "Désolé, aucune réponse valide n'a été reçue.", 
                user='⚠️ Système', 
                respond=False
            )
            return

        # Gestion des différents types de réponses
        if response.get('status') == 'success':
            data = response.get('data', {})
            
            # Extraction du contenu
            content = data.get('response', '')
            agent = data.get('agent', 'Assistant')
            
            if content:
                display_name = "Assistant" if agent == "Agent" else agent
                instance.send(
                    content, 
                    user=f"🤖 {display_name}", 
                    respond=False
                )
            else:
                instance.send(
                    "Désolé, je n'ai pas de réponse à fournir.", 
                    user='🤖 Assistant', 
                    respond=False
                )
        else:
            # Gestion des erreurs
            error_msg = response.get('message', 'Erreur inconnue')
            instance.send(
                f"❌ Erreur : {error_msg}", 
                user='⚠️ Système', 
                respond=False
            )
    
    except Exception as e:
        # Gestion des exceptions globales
        print(f"❌ Erreur critique dans le callback : {type(e).__name__} - {str(e)}")
        import traceback
        traceback.print_exc()  # Afficher la trace complète
        instance.send(
            f"❌ Erreur critique de communication : {str(e)}", 
            user='⚠️ Système', 
            respond=False
        )

# Initialisation du client WebSocket
websocket_client = WebSocketClient(
    user_id=user_id, 
    host=WEBSOCKET_CONFIG['host'], 
    port=WEBSOCKET_CONFIG['port'],
    path=WEBSOCKET_CONFIG['path']
)

# Initialisation de l'interface de chat
chat_interface = pn.chat.ChatInterface(
    callback=callback,
    callback_user="👤 Utilisateur",
    show_rerun=False,
    show_undo=False,
    show_clear=True,
    sizing_mode='stretch_width',
    min_height=600
)

# Message d'accueil
chat_interface.send(
    "👋 Bonjour ! Je suis votre assistant. Comment puis-je vous aider aujourd'hui ?",
    user="🤖 Assistant",
    respond=False
)

# Bouton de téléchargement
def download_history():
    """Télécharge l'historique de la conversation"""
    buffer = StringIO()
    for msg in chat_interface.objects:
        buffer.write(f"{msg.user}: {msg.object}\n")
    return buffer.getvalue()

download_button = pn.widgets.FileDownload(
    callback=download_history,
    filename='chat_history.txt',
    label="📥 Télécharger l'historique",
    button_type='primary',
    width=200
)

# Switch d'agent
agent_options = ['user_proxy', 'orchestrator']
agent_switch = pn.widgets.Select(
    name='🔄 Agent actif',
    options=agent_options,
    value='user_proxy',
    width=150
)

async def on_agent_switch(event):
    """Gère le changement d'agent"""
    new_agent = event.new
    try:
        switch_result = await websocket_client.send_message(f"switch_agent {new_agent}")
        
        if switch_result and switch_result.get('status') == 'success':
            chat_interface.send(f"✅ Passage à l'agent {new_agent}", user="🔄 Système", respond=False)
        else:
            error_msg = switch_result.get('message', 'Erreur inconnue') if switch_result else 'Pas de réponse du serveur'
            chat_interface.send(f"❌ Erreur lors du changement d'agent : {error_msg}", user="⚠️ Système", respond=False)
    except Exception as e:
        chat_interface.send(f"❌ Erreur lors du changement d'agent : {str(e)}", user="⚠️ Système", respond=False)

agent_switch.param.watch(on_agent_switch, 'value')

# Mise en page
header = pn.Row(
    pn.pane.Markdown('# 💬 Chat Phidata'),
    pn.Spacer(width=20),
    connection_status,
    pn.Spacer(width=20),
    agent_switch,
    pn.Spacer(width=20),
    download_button,
    sizing_mode='stretch_width'
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
