"""WebSocket hub: pushes readings, alerts, state changes and transfer plans to dashboards."""

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


class Hub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def broadcast(self, *events: dict) -> None:
        for event in events:
            message = json.dumps(event, default=str)
            for ws in list(self.clients):
                try:
                    await ws.send_text(message)
                except Exception:
                    self.disconnect(ws)


hub = Hub()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()  # clients don't need to send anything; keeps the socket open
    except WebSocketDisconnect:
        hub.disconnect(ws)
