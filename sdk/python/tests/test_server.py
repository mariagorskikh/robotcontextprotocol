"""Tests for ARP Server."""

import pytest
from arp_sdk.server import ARPServer, ARPError
from arp_sdk.types import (
    SafetyMetadata,
    SafetyLevel,
    SafetyConstraint,
    ConstraintType,
    ViolationAction,
    ARPErrorCode,
)


@pytest.fixture
def server():
    s = ARPServer(
        name="test-robot",
        version="0.1.0",
        robot_model="Test Arm",
        robot_type="manipulator",
        port=0,
    )

    @s.tool(
        description="Move the arm to a target position",
        safety=SafetyMetadata(level=SafetyLevel.NORMAL),
        parameters={"target": {"type": "array", "items": {"type": "number"}}},
        estimated_duration=2.0,
    )
    async def move_to(target: list[float]) -> dict:
        return {"reached": target}

    @s.tool(
        description="Pick up an object",
        safety=SafetyMetadata(level=SafetyLevel.ELEVATED),
        parameters={"object_id": {"type": "string"}},
    )
    async def pick_up(object_id: str) -> dict:
        return {"picked": object_id}

    @s.tool(
        description="Activate a dangerous tool",
        safety=SafetyMetadata(level=SafetyLevel.CRITICAL, requiresConfirmation=True),
        parameters={},
    )
    async def activate_cutter() -> dict:
        return {"active": True}

    @s.context(
        name="odometry",
        description="Robot odometry",
        data_type="pose",
        coordinate_frame="world",
        update_rate=10.0,
    )
    async def get_odometry():
        return {"position": {"x": 0, "y": 0, "z": 0}}

    s.add_constraint(SafetyConstraint(
        name="workspace_limits",
        type=ConstraintType.WORKSPACE_BOUND,
        parameters={"min": [-2, -2, 0], "max": [2, 2, 3]},
        violationAction=ViolationAction.REJECT,
        priority=100,
    ))

    s.add_constraint(SafetyConstraint(
        name="speed_limit",
        type=ConstraintType.VELOCITY_LIMIT,
        parameters={"max_linear": 1.0},
        violationAction=ViolationAction.REJECT,
    ))

    return s


class TestServerInitialize:
    async def test_initialize(self, server):
        result = await server._handle_initialize({"protocolVersion": "0.1.0"})
        assert result["protocolVersion"] == "0.1.0"
        assert result["serverInfo"]["name"] == "test-robot"
        assert result["capabilities"]["tools"] is True
        assert server._initialized is True

    async def test_not_initialized_error(self, server):
        response = await server._handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "arp.listTools",
            "params": {},
        })
        assert response["error"]["code"] == ARPErrorCode.NOT_INITIALIZED


class TestServerTools:
    async def test_list_tools(self, server):
        await server._handle_initialize({})
        result = await server._handle_list_tools({})
        tools = result["tools"]
        assert len(tools) == 3
        names = {t["name"] for t in tools}
        assert "move_to" in names
        assert "pick_up" in names
        assert "activate_cutter" in names

    async def test_call_tool_success(self, server):
        await server._handle_initialize({})
        result = await server._handle_call_tool({
            "name": "move_to",
            "callId": "test_call_1",
            "arguments": {"target": [1.0, 0.5, 0.0]},
        })
        assert result["state"] == "completed"
        assert result["callId"] == "test_call_1"
        assert result["result"] == {"reached": [1.0, 0.5, 0.0]}
        assert result["duration"] is not None

    async def test_call_unknown_tool(self, server):
        await server._handle_initialize({})
        with pytest.raises(ARPError) as exc_info:
            await server._handle_call_tool({
                "name": "nonexistent",
                "callId": "test_call_2",
            })
        assert exc_info.value.code == ARPErrorCode.TOOL_NOT_FOUND

    async def test_call_tool_requires_confirmation(self, server):
        await server._handle_initialize({})
        with pytest.raises(ARPError) as exc_info:
            await server._handle_call_tool({
                "name": "activate_cutter",
                "callId": "test_call_3",
            })
        assert exc_info.value.code == ARPErrorCode.SAFETY_VIOLATION


class TestServerConstraints:
    async def test_list_constraints(self, server):
        await server._handle_initialize({})
        result = await server._handle_list_constraints({})
        assert len(result["constraints"]) == 2

    async def test_workspace_violation(self, server):
        await server._handle_initialize({})
        with pytest.raises(ARPError) as exc_info:
            await server._handle_call_tool({
                "name": "move_to",
                "callId": "test_call_4",
                "arguments": {"target": [5.0, 0.0, 0.0]},
            })
        assert exc_info.value.code == ARPErrorCode.SAFETY_VIOLATION
        assert "workspace" in exc_info.value.message.lower()

    async def test_within_workspace_ok(self, server):
        await server._handle_initialize({})
        result = await server._handle_call_tool({
            "name": "move_to",
            "callId": "test_call_5",
            "arguments": {"target": [1.0, 1.0, 1.0]},
        })
        assert result["state"] == "completed"

    async def test_velocity_violation(self, server):
        await server._handle_initialize({})
        with pytest.raises(ARPError) as exc_info:
            await server._handle_call_tool({
                "name": "move_to",
                "callId": "test_call_6",
                "arguments": {"target": [1.0, 0.0, 0.0], "velocity": 5.0},
            })
        assert exc_info.value.code == ARPErrorCode.SAFETY_VIOLATION


class TestServerContext:
    async def test_list_context(self, server):
        await server._handle_initialize({})
        result = await server._handle_list_context({})
        assert len(result["sources"]) == 1
        assert result["sources"][0]["name"] == "odometry"

    async def test_subscribe_unknown_context(self, server):
        await server._handle_initialize({})
        with pytest.raises(ARPError) as exc_info:
            await server._handle_subscribe_context({"name": "nonexistent"})
        assert exc_info.value.code == ARPErrorCode.CONTEXT_NOT_FOUND


class TestEmergencyStop:
    async def test_emergency_stop(self, server):
        await server._handle_initialize({})
        await server._handle_emergency_stop({"reason": "Test stop"})
        assert server._emergency_stopped is True

        with pytest.raises(ARPError) as exc_info:
            await server._handle_call_tool({
                "name": "move_to",
                "callId": "test_call_7",
                "arguments": {"target": [0, 0, 0]},
            })
        assert exc_info.value.code == ARPErrorCode.EMERGENCY_STOPPED


class TestServerRouting:
    async def test_unknown_method(self, server):
        server._initialized = True
        response = await server._handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "arp.unknownMethod",
            "params": {},
        })
        assert response["error"]["code"] == -32601

    async def test_shutdown(self, server):
        await server._handle_initialize({})
        result = await server._handle_shutdown({})
        assert result["status"] == "ok"
        assert server._initialized is False
