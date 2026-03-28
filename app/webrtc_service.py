from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        # Maps room_id -> dictionary of client_id -> WebSocket
        self.active_connections = {}

    async def connect(self, room_id: str, client_id: str, websocket: WebSocket):
        await websocket.accept()
        if room_id not in self.active_connections:
            self.active_connections[room_id] = {}
        self.active_connections[room_id][client_id] = websocket

    def disconnect(self, room_id: str, client_id: str):
        if room_id in self.active_connections:
            if client_id in self.active_connections[room_id]:
                del self.active_connections[room_id][client_id]
            if not self.active_connections[room_id]:
                del self.active_connections[room_id]

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, room_id: str, message: dict, sender_id: str):
        if room_id in self.active_connections:
            for c_id, connection in self.active_connections[room_id].items():
                if c_id != sender_id:
                    await connection.send_json(message)

manager = ConnectionManager()
