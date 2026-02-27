"""Integration tests — full client/server lifecycle over WebSocket."""

import asyncio
import pytest

from arp_sdk.server import ARPServer
from arp_sdk.client import ARPClient
from arp_sdk.types import (
    SafetyMetadata,
    SafetyLevel,
    SafetyConstraint,
    ConstraintType,
    ViolationAction,
    ToolState,
)


@pytest.fixture
async def server_and_client():
    """Start an ARP server and connect a client."""
    server = ARPServer(
        name="integration-test-robot",
        version="0.1.0",
        robot_model="Test Robot",
        robot_type="manipulator",
        host="127.0.0.1",
        port=0,  # Will be overridden
    )

    # Register tools
    @server.tool(
        description="Move the arm to a target position",
        safety=SafetyMetadata(level=SafetyLevel.NORMAL),
        parameters={"target": {"type": "array"}},
        estimated_duration=1.0,
    )
    async def move_to(target: list[float]) -> dict:
        await asyncio.sleep(0.05)  # Simulate movement
        return {"reached": target}

    @server.tool(
        description="Pick up an object",
        safety=SafetyMetadata(level=SafetyLevel.ELEVATED),
        parameters={"object_id": {"type": "string"}},
    )
    async def pick_up(object_id: str) -> dict:
        return {"picked": object_id}

    @server.tool(
        description="Failing tool",
        safety=SafetyMetadata(level=SafetyLevel.NORMAL),
        parameters={},
    )
    async def fail_tool() -> dict:
        raise RuntimeError("Simulated failure")

    # Register context
    counter = {"value": 0}

    @server.context(
        name="odometry",
        description="Robot pose",
        data_type="pose",
        coordinate_frame="world",
        update_rate=20.0,
    )
    async def get_odometry():
        counter["value"] += 1
        return {"position": {"x": counter["value"] * 0.1, "y": 0, "z": 0}}

    # Add constraints
    server.add_constraint(SafetyConstraint(
        name="workspace",
        type=ConstraintType.WORKSPACE_BOUND,
        parameters={"min": [-5, -5, 0], "max": [5, 5, 5]},
        violationAction=ViolationAction.REJECT,
    ))

    # Find a free port
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server._transport.port = port
    await server.start()

    client = ARPClient(
        url=f"ws://127.0.0.1:{port}",
        client_name="test-client",
        client_version="0.1.0",
    )
    await client.connect()

    yield server, client

    await client.disconnect()
    await server.stop()


class TestFullLifecycle:
    async def test_initialize_and_list_tools(self, server_and_client):
        server, client = server_and_client
        info = await client.initialize()
        assert info.server_info.name == "integration-test-robot"
        assert info.server_info.robot_model == "Test Robot"

        tools = await client.list_tools()
        assert len(tools) == 3
        tool_names = {t.name for t in tools}
        assert "move_to" in tool_names
        assert "pick_up" in tool_names

    async def test_call_tool_success(self, server_and_client):
        server, client = server_and_client
        await client.initialize()

        result = await client.call_tool("move_to", target=[1.0, 2.0, 0.5])
        assert result.state == ToolState.COMPLETED
        assert result.result == {"reached": [1.0, 2.0, 0.5]}
        assert result.duration is not None
        assert result.duration > 0

    async def test_call_tool_failure(self, server_and_client):
        server, client = server_and_client
        await client.initialize()

        result = await client.call_tool("fail_tool")
        assert result.state == ToolState.FAILED
        assert "Simulated failure" in result.error

    async def test_safety_constraint_blocks_call(self, server_and_client):
        server, client = server_and_client
        await client.initialize()

        # Target outside workspace bounds
        result = await client.call_tool("move_to", target=[10.0, 0.0, 0.0])
        assert result.state == ToolState.FAILED
        assert "safety" in result.error.lower() or "workspace" in result.error.lower()

    async def test_list_context_sources(self, server_and_client):
        server, client = server_and_client
        await client.initialize()

        sources = await client.list_context()
        assert len(sources) == 1
        assert sources[0].name == "odometry"

    async def test_subscribe_context(self, server_and_client):
        server, client = server_and_client
        await client.initialize()

        updates = []

        async def on_update(update):
            updates.append(update)

        await client.subscribe_context("odometry", on_update, max_rate=20.0)
        await asyncio.sleep(0.3)  # Wait for a few updates
        await client.unsubscribe_context("odometry")

        assert len(updates) > 0
        assert "position" in updates[0].data

    async def test_list_constraints(self, server_and_client):
        server, client = server_and_client
        await client.initialize()

        constraints = await client.list_constraints()
        assert len(constraints) == 1
        assert constraints[0].name == "workspace"

    async def test_set_workspace(self, server_and_client):
        server, client = server_and_client
        await client.initialize()

        result = await client.set_workspace(
            name="test_area",
            bounds={"type": "box", "min": [-1, -1, 0], "max": [1, 1, 2]},
        )
        assert result["status"] == "ok"

    async def test_emergency_stop(self, server_and_client):
        server, client = server_and_client
        await client.initialize()

        await client.emergency_stop("Integration test e-stop")
        await asyncio.sleep(0.1)

        # After e-stop, tool calls should fail
        result = await client.call_tool("move_to", target=[0, 0, 0])
        assert result.state == ToolState.FAILED

    async def test_multiple_tool_calls(self, server_and_client):
        server, client = server_and_client
        await client.initialize()

        result1 = await client.call_tool("move_to", target=[1, 0, 0])
        assert result1.state == ToolState.COMPLETED

        result2 = await client.call_tool("pick_up", object_id="block_a")
        assert result2.state == ToolState.COMPLETED
        assert result2.result == {"picked": "block_a"}

        result3 = await client.call_tool("move_to", target=[0, 0, 1])
        assert result3.state == ToolState.COMPLETED
