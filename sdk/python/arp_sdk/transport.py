"""WebSocket transport layer for ARP protocol."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Awaitable

import websockets
from websockets.asyncio.server import ServerConnection
from websockets.asyncio.client import ClientConnection

from arp_sdk.types import JSONRPCRequest, JSONRPCResponse, JSONRPCNotification, JSONRPCError

logger = logging.getLogger("arp.transport")

MessageHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]


class WebSocketServerTransport:
    """WebSocket server transport for ARP."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self._handler: MessageHandler | None = None
        self._notification_handler: Callable[[dict[str, Any]], Awaitable[None]] | None = None
        self._connections: set[ServerConnection] = set()
        self._server: Any = None

    def on_message(self, handler: MessageHandler) -> None:
        self._handler = handler

    def on_notification(self, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self._notification_handler = handler

    async def _handle_connection(self, websocket: ServerConnection) -> None:
        self._connections.add(websocket)
        logger.info("Client connected")
        try:
            async for raw_message in websocket:
                try:
                    message = json.loads(raw_message)
                except json.JSONDecodeError:
                    error_resp = JSONRPCResponse(
                        id=0,
                        error=JSONRPCError(code=-32700, message="Parse error"),
                    )
                    await websocket.send(error_resp.model_dump_json(by_alias=True))
                    continue

                if "id" in message and self._handler:
                    response = await self._handler(message)
                    if response is not None:
                        await websocket.send(json.dumps(response))
                elif self._notification_handler:
                    await self._notification_handler(message)
        except websockets.exceptions.ConnectionClosed:
            logger.info("Client disconnected")
        finally:
            self._connections.discard(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        if not self._connections:
            return
        data = json.dumps(message)
        await asyncio.gather(
            *(conn.send(data) for conn in self._connections),
            return_exceptions=True,
        )

    async def send_to(self, websocket: ServerConnection, message: dict[str, Any]) -> None:
        await websocket.send(json.dumps(message))

    async def start(self) -> None:
        self._server = await websockets.serve(
            self._handle_connection,
            self.host,
            self.port,
        )
        logger.info(f"ARP server listening on ws://{self.host}:{self.port}")

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("ARP server stopped")

    @property
    def connections(self) -> set[ServerConnection]:
        return self._connections


class WebSocketClientTransport:
    """WebSocket client transport for ARP."""

    def __init__(self, url: str = "ws://localhost:8765"):
        self.url = url
        self._ws: ClientConnection | None = None
        self._notification_handlers: dict[str, Callable[[dict[str, Any]], Awaitable[None]]] = {}
        self._pending_requests: dict[int | str, asyncio.Future[dict[str, Any]]] = {}
        self._next_id = 1
        self._receive_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        self._ws = await websockets.connect(self.url)
        self._receive_task = asyncio.create_task(self._receive_loop())
        logger.info(f"Connected to {self.url}")

    async def disconnect(self) -> None:
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
            logger.info("Disconnected")

    def on_notification(self, method: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self._notification_handlers[method] = handler

    async def send_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._ws:
            raise RuntimeError("Not connected")

        request_id = self._next_id
        self._next_id += 1

        request = JSONRPCRequest(id=request_id, method=method, params=params or {})
        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        await self._ws.send(request.model_dump_json(by_alias=True))
        return await future

    async def send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        if not self._ws:
            raise RuntimeError("Not connected")
        notification = JSONRPCNotification(method=method, params=params or {})
        await self._ws.send(notification.model_dump_json(by_alias=True))

    async def _receive_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw_message in self._ws:
                try:
                    message = json.loads(raw_message)
                except json.JSONDecodeError:
                    continue

                if "id" in message and message["id"] in self._pending_requests:
                    future = self._pending_requests.pop(message["id"])
                    future.set_result(message)
                elif "method" in message:
                    method = message["method"]
                    if method in self._notification_handlers:
                        await self._notification_handlers[method](message.get("params", {}))
        except websockets.exceptions.ConnectionClosed:
            logger.info("Connection closed")
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(ConnectionError("Connection closed"))
            self._pending_requests.clear()
        except asyncio.CancelledError:
            pass
