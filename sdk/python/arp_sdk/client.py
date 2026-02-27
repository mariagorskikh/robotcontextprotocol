"""ARP Client — connect to ARP servers and control robots."""

from __future__ import annotations

import uuid
import logging
from typing import Any, Callable, Awaitable

from arp_sdk.types import (
    PhysicalTool,
    ContextSource,
    SafetyConstraint,
    ServerInfo,
    Capabilities,
    CallToolResult,
    ToolProgressParams,
    ContextUpdateParams,
    ToolState,
    ClientInfo,
)
from arp_sdk.transport import WebSocketClientTransport

logger = logging.getLogger("arp.client")

ProgressCallback = Callable[[ToolProgressParams], Awaitable[None]]
ContextCallback = Callable[[ContextUpdateParams], Awaitable[None]]


class ARPClient:
    """Client for connecting to ARP robot servers.

    Usage:
        client = ARPClient("ws://localhost:8765")
        await client.connect()
        await client.initialize()

        tools = await client.list_tools()
        result = await client.call_tool("move_to", target=[1.0, 0.5, 0.0])

        await client.disconnect()
    """

    def __init__(
        self,
        url: str = "ws://localhost:8765",
        client_name: str = "arp-client",
        client_version: str = "0.1.0",
    ):
        self.url = url
        self.client_info = ClientInfo(name=client_name, version=client_version)
        self.server_info: ServerInfo | None = None
        self.server_capabilities: Capabilities | None = None
        self._initialized = False

        self._transport = WebSocketClientTransport(url=url)
        self._tools: dict[str, PhysicalTool] = {}
        self._context_sources: dict[str, ContextSource] = {}
        self._constraints: dict[str, SafetyConstraint] = {}

        self._progress_callbacks: dict[str, ProgressCallback] = {}
        self._context_callbacks: dict[str, ContextCallback] = {}

        self._transport.on_notification("arp.toolProgress", self._handle_tool_progress)
        self._transport.on_notification("arp.contextUpdate", self._handle_context_update)

    # --- Connection ---

    async def connect(self) -> None:
        await self._transport.connect()

    async def disconnect(self) -> None:
        if self._initialized:
            try:
                await self._transport.send_request("arp.shutdown")
            except Exception:
                pass
        await self._transport.disconnect()

    async def initialize(self) -> InitializeInfo:
        response = await self._transport.send_request(
            "arp.initialize",
            {
                "protocolVersion": "0.1.0",
                "clientInfo": self.client_info.model_dump(by_alias=True),
                "capabilities": {"planning": True, "confirmation": True},
            },
        )

        if "error" in response and response["error"]:
            raise ARPClientError(response["error"]["message"])

        result = response.get("result", {})
        self.server_info = ServerInfo(**result.get("serverInfo", {}))
        self.server_capabilities = Capabilities(**result.get("capabilities", {}))
        self._initialized = True

        return InitializeInfo(
            server_info=self.server_info,
            capabilities=self.server_capabilities,
        )

    # --- Tools ---

    async def list_tools(self) -> list[PhysicalTool]:
        self._ensure_initialized()
        response = await self._transport.send_request("arp.listTools")

        if "error" in response and response["error"]:
            raise ARPClientError(response["error"]["message"])

        result = response.get("result", {})
        self._tools = {}
        tools = []
        for tool_data in result.get("tools", []):
            tool = PhysicalTool(**tool_data)
            self._tools[tool.name] = tool
            tools.append(tool)
        return tools

    async def call_tool(
        self,
        name: str,
        on_progress: ProgressCallback | None = None,
        **arguments: Any,
    ) -> CallToolResult:
        self._ensure_initialized()
        call_id = str(uuid.uuid4())

        if on_progress:
            self._progress_callbacks[call_id] = on_progress

        try:
            response = await self._transport.send_request(
                "arp.callTool",
                {"name": name, "callId": call_id, "arguments": arguments},
            )

            if "error" in response and response["error"]:
                error = response["error"]
                return CallToolResult(
                    callId=call_id,
                    state=ToolState.FAILED,
                    error=error.get("message", "Unknown error"),
                )

            result = response.get("result", {})
            return CallToolResult(**result)
        finally:
            self._progress_callbacks.pop(call_id, None)

    async def cancel_tool(self, call_id: str) -> dict[str, Any]:
        self._ensure_initialized()
        response = await self._transport.send_request(
            "arp.cancelTool", {"callId": call_id}
        )
        return response.get("result", {})

    # --- Context ---

    async def list_context(self) -> list[ContextSource]:
        self._ensure_initialized()
        response = await self._transport.send_request("arp.listContext")

        if "error" in response and response["error"]:
            raise ARPClientError(response["error"]["message"])

        result = response.get("result", {})
        sources = []
        for source_data in result.get("sources", []):
            source = ContextSource(**source_data)
            self._context_sources[source.name] = source
            sources.append(source)
        return sources

    async def subscribe_context(
        self,
        name: str,
        callback: ContextCallback,
        max_rate: float | None = None,
    ) -> None:
        self._ensure_initialized()
        self._context_callbacks[name] = callback

        params: dict[str, Any] = {"name": name}
        if max_rate is not None:
            params["maxRate"] = max_rate

        response = await self._transport.send_request("arp.subscribeContext", params)
        if "error" in response and response["error"]:
            self._context_callbacks.pop(name, None)
            raise ARPClientError(response["error"]["message"])

    async def unsubscribe_context(self, name: str) -> None:
        self._ensure_initialized()
        self._context_callbacks.pop(name, None)
        await self._transport.send_request("arp.unsubscribeContext", {"name": name})

    # --- Constraints ---

    async def list_constraints(self) -> list[SafetyConstraint]:
        self._ensure_initialized()
        response = await self._transport.send_request("arp.listConstraints")

        if "error" in response and response["error"]:
            raise ARPClientError(response["error"]["message"])

        result = response.get("result", {})
        constraints = []
        for c_data in result.get("constraints", []):
            c = SafetyConstraint(**c_data)
            self._constraints[c.name] = c
            constraints.append(c)
        return constraints

    # --- Workspace ---

    async def set_workspace(
        self,
        name: str,
        bounds: dict[str, Any],
        objects: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self._ensure_initialized()
        response = await self._transport.send_request(
            "arp.setWorkspace",
            {"name": name, "bounds": bounds, "objects": objects or []},
        )
        return response.get("result", {})

    # --- Emergency Stop ---

    async def emergency_stop(self, reason: str) -> None:
        await self._transport.send_notification(
            "arp.emergencyStop", {"reason": reason}
        )

    # --- Notification Handlers ---

    async def _handle_tool_progress(self, params: dict[str, Any]) -> None:
        call_id = params.get("callId", "")
        callback = self._progress_callbacks.get(call_id)
        if callback:
            progress = ToolProgressParams(**params)
            await callback(progress)

    async def _handle_context_update(self, params: dict[str, Any]) -> None:
        name = params.get("name", "")
        callback = self._context_callbacks.get(name)
        if callback:
            update = ContextUpdateParams(**params)
            await callback(update)

    # --- Helpers ---

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            raise ARPClientError("Client not initialized. Call connect() and initialize() first.")


class InitializeInfo:
    """Information returned after initialization."""

    def __init__(self, server_info: ServerInfo, capabilities: Capabilities):
        self.server_info = server_info
        self.capabilities = capabilities

    def __repr__(self) -> str:
        return (
            f"InitializeInfo(server={self.server_info.name}, "
            f"robot={self.server_info.robot_model})"
        )


class ARPClientError(Exception):
    """ARP client error."""

    pass
