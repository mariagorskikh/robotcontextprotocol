"""ARP Server — base class for robot servers."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from arp_sdk.types import (
    PhysicalTool,
    SafetyMetadata,
    SafetyLevel,
    ContextSource,
    SafetyConstraint,
    ToolState,
    CallToolResult,
    ToolProgressParams,
    ContextUpdateParams,
    ServerInfo,
    Capabilities,
    InitializeResult,
    ARPErrorCode,
)
from arp_sdk.transport import WebSocketServerTransport

logger = logging.getLogger("arp.server")

ToolHandler = Callable[..., Awaitable[Any]]
ContextProvider = Callable[[], Awaitable[Any]]


class ARPServer:
    """Base class for ARP robot servers.

    Usage:
        server = ARPServer(
            name="my-robot",
            version="1.0.0",
            robot_model="My Robot Arm",
            robot_type="manipulator",
        )

        @server.tool(
            description="Move the robot arm to a position",
            safety=SafetyMetadata(level=SafetyLevel.NORMAL),
            parameters={"target": {"type": "array", "items": {"type": "number"}}},
        )
        async def move_to(target: list[float]) -> dict:
            # Move the robot
            return {"reached": target}

        await server.run()
    """

    def __init__(
        self,
        name: str = "arp-server",
        version: str = "0.1.0",
        robot_model: str | None = None,
        robot_type: str | None = None,
        host: str = "0.0.0.0",
        port: int = 8765,
    ):
        self.server_info = ServerInfo(
            name=name,
            version=version,
            robotModel=robot_model,
            robotType=robot_type,
        )
        self.capabilities = Capabilities(
            tools=True,
            context=True,
            constraints=True,
            planning=False,
            confirmation=False,
        )

        self._tools: dict[str, PhysicalTool] = {}
        self._tool_handlers: dict[str, ToolHandler] = {}
        self._context_sources: dict[str, ContextSource] = {}
        self._context_providers: dict[str, ContextProvider] = {}
        self._constraints: dict[str, SafetyConstraint] = {}
        self._active_calls: dict[str, ToolState] = {}
        self._initialized = False
        self._emergency_stopped = False

        self._transport = WebSocketServerTransport(host=host, port=port)
        self._transport.on_message(self._handle_request)
        self._transport.on_notification(self._handle_notification)

        self._context_tasks: dict[str, asyncio.Task[None]] = {}

    # --- Decorators ---

    def tool(
        self,
        description: str,
        safety: SafetyMetadata,
        parameters: dict[str, Any] | None = None,
        preconditions: list[dict[str, Any]] | None = None,
        effects: list[dict[str, Any]] | None = None,
        estimated_duration: float | None = None,
    ) -> Callable[[ToolHandler], ToolHandler]:
        """Register a function as a Physical Tool."""

        def decorator(func: ToolHandler) -> ToolHandler:
            tool_def = PhysicalTool(
                name=func.__name__,
                description=description,
                parameters=parameters or {},
                safety=safety,
                preconditions=preconditions or [],
                effects=effects or [],
                estimatedDuration=estimated_duration,
            )
            self._tools[func.__name__] = tool_def
            self._tool_handlers[func.__name__] = func
            return func

        return decorator

    def context(
        self,
        name: str,
        description: str,
        data_type: str,
        coordinate_frame: str | None = None,
        update_rate: float | None = None,
    ) -> Callable[[ContextProvider], ContextProvider]:
        """Register a function as a Physical Context source."""

        def decorator(func: ContextProvider) -> ContextProvider:
            source = ContextSource(
                name=name,
                description=description,
                dataType=data_type,
                coordinateFrame=coordinate_frame,
                updateRate=update_rate,
            )
            self._context_sources[name] = source
            self._context_providers[name] = func
            return func

        return decorator

    def add_constraint(self, constraint: SafetyConstraint) -> None:
        """Add a safety constraint."""
        self._constraints[constraint.name] = constraint

    # --- Request Handling ---

    async def _handle_request(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method", "")
        msg_id = message.get("id")
        params = message.get("params", {})

        handlers: dict[str, Callable[..., Awaitable[Any]]] = {
            "arp.initialize": self._handle_initialize,
            "arp.shutdown": self._handle_shutdown,
            "arp.listTools": self._handle_list_tools,
            "arp.callTool": self._handle_call_tool,
            "arp.cancelTool": self._handle_cancel_tool,
            "arp.listContext": self._handle_list_context,
            "arp.subscribeContext": self._handle_subscribe_context,
            "arp.unsubscribeContext": self._handle_unsubscribe_context,
            "arp.listConstraints": self._handle_list_constraints,
            "arp.getConstraint": self._handle_get_constraint,
            "arp.setWorkspace": self._handle_set_workspace,
        }

        handler = handlers.get(method)
        if not handler:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

        if method != "arp.initialize" and not self._initialized:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": ARPErrorCode.NOT_INITIALIZED, "message": "Not initialized"},
            }

        try:
            result = await handler(params)
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except ARPError as e:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": e.code, "message": e.message, "data": e.data},
            }

    async def _handle_notification(self, message: dict[str, Any]) -> None:
        method = message.get("method", "")
        params = message.get("params", {})

        if method == "arp.emergencyStop":
            await self._handle_emergency_stop(params)

    # --- Method Implementations ---

    async def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        self._initialized = True
        result = InitializeResult(
            protocolVersion="0.1.0",
            serverInfo=self.server_info,
            capabilities=self.capabilities,
        )
        return result.model_dump(by_alias=True)

    async def _handle_shutdown(self, params: dict[str, Any]) -> dict[str, Any]:
        for task in self._context_tasks.values():
            task.cancel()
        self._context_tasks.clear()
        self._initialized = False
        return {"status": "ok"}

    async def _handle_list_tools(self, params: dict[str, Any]) -> dict[str, Any]:
        tools = [t.model_dump(by_alias=True, exclude_none=True) for t in self._tools.values()]
        return {"tools": tools}

    async def _handle_call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        tool_name = params.get("name", "")
        call_id = params.get("callId", str(uuid.uuid4()))
        arguments = params.get("arguments", {})

        if self._emergency_stopped:
            raise ARPError(ARPErrorCode.EMERGENCY_STOPPED, "Emergency stop active")

        if tool_name not in self._tools:
            raise ARPError(ARPErrorCode.TOOL_NOT_FOUND, f"Tool not found: {tool_name}")

        if call_id in self._active_calls and self._active_calls[call_id] == ToolState.RUNNING:
            raise ARPError(ARPErrorCode.TOOL_BUSY, f"Tool call {call_id} already running")

        tool_def = self._tools[tool_name]

        # Check safety constraints
        violation = self._check_constraints(tool_name, arguments)
        if violation:
            raise ARPError(
                ARPErrorCode.SAFETY_VIOLATION,
                f"Safety violation: {violation}",
                {"constraint": violation},
            )

        # Check if confirmation is required
        if tool_def.safety.requires_confirmation:
            raise ARPError(
                ARPErrorCode.SAFETY_VIOLATION,
                f"Tool '{tool_name}' requires human confirmation",
                {"requiresConfirmation": True},
            )

        handler = self._tool_handlers[tool_name]
        self._active_calls[call_id] = ToolState.RUNNING

        # Send progress notification
        await self._send_progress(call_id, 0.0, "Starting execution", ToolState.RUNNING)

        start_time = time.monotonic()
        try:
            result = await handler(**arguments)
            duration = time.monotonic() - start_time
            self._active_calls[call_id] = ToolState.COMPLETED

            call_result = CallToolResult(
                callId=call_id,
                state=ToolState.COMPLETED,
                result=result,
                duration=duration,
            )
            return call_result.model_dump(by_alias=True, exclude_none=True)
        except Exception as e:
            duration = time.monotonic() - start_time
            self._active_calls[call_id] = ToolState.FAILED

            call_result = CallToolResult(
                callId=call_id,
                state=ToolState.FAILED,
                error=str(e),
                duration=duration,
            )
            return call_result.model_dump(by_alias=True, exclude_none=True)

    async def _handle_cancel_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        call_id = params.get("callId", "")
        if call_id in self._active_calls:
            self._active_calls[call_id] = ToolState.CANCELLED
            return {"callId": call_id, "state": "cancelled"}
        return {"callId": call_id, "state": "not_found"}

    async def _handle_list_context(self, params: dict[str, Any]) -> dict[str, Any]:
        sources = [s.model_dump(by_alias=True, exclude_none=True) for s in self._context_sources.values()]
        return {"sources": sources}

    async def _handle_subscribe_context(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name", "")
        max_rate = params.get("maxRate")

        if name not in self._context_sources:
            raise ARPError(ARPErrorCode.CONTEXT_NOT_FOUND, f"Context source not found: {name}")

        if name not in self._context_tasks:
            source = self._context_sources[name]
            rate = max_rate or source.update_rate or 1.0
            task = asyncio.create_task(self._context_stream_loop(name, rate))
            self._context_tasks[name] = task

        return {"subscribed": name}

    async def _handle_unsubscribe_context(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name", "")
        if name in self._context_tasks:
            self._context_tasks[name].cancel()
            del self._context_tasks[name]
        return {"unsubscribed": name}

    async def _handle_list_constraints(self, params: dict[str, Any]) -> dict[str, Any]:
        constraints = [c.model_dump(by_alias=True, exclude_none=True) for c in self._constraints.values()]
        return {"constraints": constraints}

    async def _handle_get_constraint(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name", "")
        if name not in self._constraints:
            raise ARPError(ARPErrorCode.SAFETY_VIOLATION, f"Constraint not found: {name}")
        return self._constraints[name].model_dump(by_alias=True, exclude_none=True)

    async def _handle_set_workspace(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"status": "ok", "workspace": params.get("name", "")}

    async def _handle_emergency_stop(self, params: dict[str, Any]) -> None:
        reason = params.get("reason", "Unknown")
        logger.warning(f"EMERGENCY STOP: {reason}")
        self._emergency_stopped = True
        for call_id, state in self._active_calls.items():
            if state == ToolState.RUNNING:
                self._active_calls[call_id] = ToolState.CANCELLED

    # --- Internal Helpers ---

    def _check_constraints(self, tool_name: str, arguments: dict[str, Any]) -> str | None:
        """Check if a tool call violates any safety constraints. Returns violation description or None."""
        for constraint in self._constraints.values():
            if not constraint.enabled:
                continue

            if constraint.type.value == "workspace_bound":
                target = arguments.get("target")
                if target and isinstance(target, (list, tuple)) and len(target) >= 3:
                    bounds = constraint.parameters
                    mins = bounds.get("min", [-float("inf")] * 3)
                    maxs = bounds.get("max", [float("inf")] * 3)
                    for i in range(3):
                        if target[i] < mins[i] or target[i] > maxs[i]:
                            return f"Position {target} exceeds workspace boundary {constraint.name}"

            if constraint.type.value == "velocity_limit":
                velocity = arguments.get("velocity") or arguments.get("speed")
                if velocity is not None:
                    max_vel = constraint.parameters.get("max_linear", float("inf"))
                    if isinstance(velocity, (int, float)) and velocity > max_vel:
                        return f"Velocity {velocity} exceeds limit {max_vel}"

        return None

    async def _send_progress(
        self, call_id: str, progress: float, message: str, state: ToolState
    ) -> None:
        notification = {
            "jsonrpc": "2.0",
            "method": "arp.toolProgress",
            "params": ToolProgressParams(
                callId=call_id,
                progress=progress,
                message=message,
                state=state,
            ).model_dump(by_alias=True),
        }
        await self._transport.broadcast(notification)

    async def send_progress(
        self, call_id: str, progress: float, message: str = ""
    ) -> None:
        """Public method for tool handlers to send progress updates."""
        await self._send_progress(call_id, progress, message, ToolState.RUNNING)

    async def _context_stream_loop(self, name: str, rate: float) -> None:
        provider = self._context_providers[name]
        interval = 1.0 / rate if rate > 0 else 1.0
        try:
            while True:
                data = await provider()
                update = {
                    "jsonrpc": "2.0",
                    "method": "arp.contextUpdate",
                    "params": ContextUpdateParams(
                        name=name,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        data=data,
                    ).model_dump(by_alias=True),
                }
                await self._transport.broadcast(update)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    # --- Run ---

    async def run(self) -> None:
        """Start the ARP server."""
        await self._transport.start()
        try:
            await asyncio.Future()  # Run forever
        except asyncio.CancelledError:
            pass
        finally:
            await self._transport.stop()

    async def start(self) -> None:
        """Start the server transport (for use in tests/embedding)."""
        await self._transport.start()

    async def stop(self) -> None:
        """Stop the server transport."""
        for task in self._context_tasks.values():
            task.cancel()
        self._context_tasks.clear()
        await self._transport.stop()


class ARPError(Exception):
    """ARP protocol error."""

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data
