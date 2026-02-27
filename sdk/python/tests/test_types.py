"""Tests for ARP type definitions."""

import pytest
from pydantic import ValidationError

from arp_sdk.types import (
    SafetyLevel,
    ToolState,
    ContextDataType,
    ConstraintType,
    ViolationAction,
    Position3D,
    Quaternion,
    Pose,
    SafetyMetadata,
    Condition,
    Effect,
    PhysicalTool,
    ContextSource,
    SafetyConstraint,
    BoundingBox,
    WorkspaceObject,
    PlanStep,
    ClientInfo,
    ServerInfo,
    Capabilities,
    JSONRPCRequest,
    JSONRPCResponse,
    JSONRPCNotification,
    JSONRPCError,
    CallToolParams,
    CallToolResult,
    ToolProgressParams,
    SubscribeContextParams,
    ContextUpdateParams,
    RequestPlanParams,
    PlanResult,
    SetWorkspaceParams,
    RequestConfirmationParams,
    ConfirmationResult,
    EmergencyStopParams,
    InitializeParams,
    InitializeResult,
    ARPErrorCode,
)


class TestEnums:
    def test_safety_levels(self):
        assert SafetyLevel.NORMAL == "normal"
        assert SafetyLevel.ELEVATED == "elevated"
        assert SafetyLevel.CRITICAL == "critical"

    def test_tool_states(self):
        assert ToolState.IDLE == "idle"
        assert ToolState.RUNNING == "running"
        assert ToolState.COMPLETED == "completed"
        assert ToolState.FAILED == "failed"
        assert ToolState.CANCELLED == "cancelled"

    def test_context_data_types(self):
        assert ContextDataType.POSE == "pose"
        assert ContextDataType.JOINTS == "joints"
        assert ContextDataType.IMAGE == "image"

    def test_constraint_types(self):
        assert ConstraintType.VELOCITY_LIMIT == "velocity_limit"
        assert ConstraintType.WORKSPACE_BOUND == "workspace_bound"
        assert ConstraintType.FORCE_LIMIT == "force_limit"

    def test_violation_actions(self):
        assert ViolationAction.REJECT == "reject"
        assert ViolationAction.CLAMP == "clamp"
        assert ViolationAction.EMERGENCY_STOP == "emergency_stop"


class TestGeometry:
    def test_position3d(self):
        pos = Position3D(x=1.0, y=2.0, z=3.0)
        assert pos.x == 1.0
        assert pos.y == 2.0
        assert pos.z == 3.0

    def test_position3d_defaults(self):
        pos = Position3D()
        assert pos.x == 0.0
        assert pos.y == 0.0
        assert pos.z == 0.0

    def test_quaternion(self):
        q = Quaternion(x=0.0, y=0.0, z=0.0, w=1.0)
        assert q.w == 1.0

    def test_pose(self):
        pose = Pose(
            position=Position3D(x=1.0, y=2.0, z=3.0),
            orientation=Quaternion(x=0, y=0, z=0, w=1),
            frame="world",
        )
        assert pose.position.x == 1.0
        assert pose.frame == "world"

    def test_pose_minimal(self):
        pose = Pose(position=Position3D())
        assert pose.orientation is None
        assert pose.frame is None


class TestSafety:
    def test_safety_metadata(self):
        sm = SafetyMetadata(level=SafetyLevel.CRITICAL, requiresConfirmation=True)
        assert sm.level == SafetyLevel.CRITICAL
        assert sm.requires_confirmation is True

    def test_safety_metadata_defaults(self):
        sm = SafetyMetadata(level=SafetyLevel.NORMAL)
        assert sm.requires_confirmation is False
        assert sm.reversible is True

    def test_condition(self):
        c = Condition(field="gripper.state", operator="eq", value="open")
        assert c.field == "gripper.state"

    def test_effect(self):
        e = Effect(field="gripper.state", action="set", value="closed")
        assert e.action == "set"


class TestPhysicalTool:
    def test_basic_tool(self):
        tool = PhysicalTool(
            name="move_to",
            description="Move the arm to a target position",
            parameters={"target": {"type": "array"}},
            safety=SafetyMetadata(level=SafetyLevel.NORMAL),
        )
        assert tool.name == "move_to"
        assert tool.safety.level == SafetyLevel.NORMAL

    def test_tool_serialization(self):
        tool = PhysicalTool(
            name="pick_up",
            description="Pick up an object",
            parameters={"object_id": {"type": "string"}},
            safety=SafetyMetadata(level=SafetyLevel.ELEVATED, requiresConfirmation=True),
            estimatedDuration=5.0,
        )
        data = tool.model_dump(by_alias=True)
        assert data["name"] == "pick_up"
        assert data["estimatedDuration"] == 5.0
        assert data["safety"]["requiresConfirmation"] is True

    def test_tool_deserialization(self):
        data = {
            "name": "move_to",
            "description": "Move arm",
            "parameters": {},
            "safety": {"level": "normal"},
        }
        tool = PhysicalTool(**data)
        assert tool.name == "move_to"
        assert tool.safety.level == SafetyLevel.NORMAL


class TestContextSource:
    def test_context_source(self):
        source = ContextSource(
            name="odometry",
            description="Robot odometry",
            dataType="pose",
            coordinateFrame="world",
            updateRate=10.0,
        )
        assert source.name == "odometry"
        assert source.data_type == ContextDataType.POSE
        assert source.update_rate == 10.0


class TestConstraints:
    def test_bounding_box(self):
        bb = BoundingBox(
            type="box",
            min=[-1.0, -1.0, 0.0],
            max=[1.0, 1.0, 2.0],
            frame="world",
        )
        assert len(bb.min) == 3
        assert len(bb.max) == 3

    def test_safety_constraint(self):
        sc = SafetyConstraint(
            name="workspace_limits",
            type=ConstraintType.WORKSPACE_BOUND,
            parameters={"min": [-2, -2, 0], "max": [2, 2, 3]},
            violationAction=ViolationAction.REJECT,
            priority=100,
        )
        assert sc.name == "workspace_limits"
        assert sc.violation_action == ViolationAction.REJECT

    def test_constraint_serialization(self):
        sc = SafetyConstraint(
            name="vel_limit",
            type=ConstraintType.VELOCITY_LIMIT,
            parameters={"max_linear": 0.5},
            violationAction=ViolationAction.CLAMP,
        )
        data = sc.model_dump(by_alias=True)
        assert data["violationAction"] == "clamp"


class TestJSONRPC:
    def test_request(self):
        req = JSONRPCRequest(id=1, method="arp.listTools")
        assert req.jsonrpc == "2.0"
        assert req.id == 1

    def test_response_success(self):
        resp = JSONRPCResponse(id=1, result={"tools": []})
        assert resp.error is None
        assert resp.result == {"tools": []}

    def test_response_error(self):
        resp = JSONRPCResponse(
            id=1,
            error=JSONRPCError(code=-40001, message="Safety violation"),
        )
        assert resp.error is not None
        assert resp.error.code == -40001

    def test_notification(self):
        notif = JSONRPCNotification(
            method="arp.toolProgress",
            params={"callId": "abc", "progress": 0.5, "state": "running"},
        )
        assert "id" not in notif.model_dump()


class TestToolCall:
    def test_call_tool_params(self):
        params = CallToolParams(name="move_to", callId="call_1", arguments={"target": [1, 2, 3]})
        assert params.name == "move_to"
        assert params.call_id == "call_1"

    def test_call_tool_result(self):
        result = CallToolResult(callId="call_1", state=ToolState.COMPLETED, result={"reached": True})
        assert result.state == ToolState.COMPLETED
        data = result.model_dump(by_alias=True)
        assert data["callId"] == "call_1"

    def test_progress(self):
        prog = ToolProgressParams(callId="call_1", progress=0.75, message="Moving", state=ToolState.RUNNING)
        assert prog.progress == 0.75


class TestPlanning:
    def test_plan_step(self):
        step = PlanStep(tool="move_to", params={"target": [1, 0, 0]}, description="Go to block")
        assert step.tool == "move_to"

    def test_plan_result(self):
        result = PlanResult(
            steps=[PlanStep(tool="move_to", params={})],
            reasoning="Direct approach",
        )
        assert len(result.steps) == 1

    def test_request_plan_params(self):
        params = RequestPlanParams(
            goal="Pick up the box",
            availableTools=["move_to", "pick_up"],
        )
        assert params.goal == "Pick up the box"


class TestInitialize:
    def test_initialize_params(self):
        params = InitializeParams(
            protocolVersion="0.1.0",
            clientInfo=ClientInfo(name="test", version="1.0"),
        )
        assert params.protocol_version == "0.1.0"

    def test_initialize_result(self):
        result = InitializeResult(
            protocolVersion="0.1.0",
            serverInfo=ServerInfo(name="test-server", version="0.1.0"),
            capabilities=Capabilities(),
        )
        data = result.model_dump(by_alias=True)
        assert data["protocolVersion"] == "0.1.0"


class TestConfirmation:
    def test_request_confirmation(self):
        params = RequestConfirmationParams(
            action="Activate cutter",
            safetyLevel=SafetyLevel.CRITICAL,
            timeout=30.0,
        )
        assert params.safety_level == SafetyLevel.CRITICAL

    def test_confirmation_result(self):
        result = ConfirmationResult(confirmed=True, confirmedBy="operator")
        assert result.confirmed is True


class TestErrorCodes:
    def test_error_codes(self):
        assert ARPErrorCode.SAFETY_VIOLATION == -40001
        assert ARPErrorCode.TOOL_NOT_FOUND == -40003
        assert ARPErrorCode.EMERGENCY_STOPPED == -40007
        assert ARPErrorCode.NOT_INITIALIZED == -40009
