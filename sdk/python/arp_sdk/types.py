"""ARP protocol type definitions using Pydantic models."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --- Enums ---


class SafetyLevel(str, Enum):
    NORMAL = "normal"
    ELEVATED = "elevated"
    CRITICAL = "critical"


class ToolState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ContextDataType(str, Enum):
    POSE = "pose"
    JOINTS = "joints"
    POINTCLOUD = "pointcloud"
    IMAGE = "image"
    IMU = "imu"
    CUSTOM = "custom"


class ConstraintType(str, Enum):
    VELOCITY_LIMIT = "velocity_limit"
    WORKSPACE_BOUND = "workspace_bound"
    FORCE_LIMIT = "force_limit"
    COLLISION_ZONE = "collision_zone"
    EMERGENCY_STOP = "emergency_stop"
    RATE_LIMIT = "rate_limit"


class ViolationAction(str, Enum):
    REJECT = "reject"
    CLAMP = "clamp"
    EMERGENCY_STOP = "emergency_stop"


# --- Geometry ---


class Position3D(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class Quaternion(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 1.0


class Pose(BaseModel):
    position: Position3D
    orientation: Quaternion | None = None
    frame: str | None = None


# --- Safety ---


class SafetyMetadata(BaseModel):
    level: SafetyLevel
    requires_confirmation: bool = Field(False, alias="requiresConfirmation")
    reversible: bool = True
    description: str = ""

    model_config = {"populate_by_name": True}


class Condition(BaseModel):
    field: str
    operator: str
    value: Any


class Effect(BaseModel):
    field: str
    action: str
    value: Any = None


# --- Physical Tools ---


class PhysicalTool(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    safety: SafetyMetadata
    preconditions: list[Condition] = Field(default_factory=list)
    effects: list[Effect] = Field(default_factory=list)
    estimated_duration: float | None = Field(None, alias="estimatedDuration")

    model_config = {"populate_by_name": True}


# --- Context ---


class ContextSource(BaseModel):
    name: str
    description: str
    data_type: ContextDataType = Field(alias="dataType")
    coordinate_frame: str | None = Field(None, alias="coordinateFrame")
    update_rate: float | None = Field(None, alias="updateRate")
    schema_def: dict[str, Any] | None = Field(None, alias="schema")

    model_config = {"populate_by_name": True}


# --- Constraints ---


class BoundingBox(BaseModel):
    type: str = "box"
    min: list[float] = Field(min_length=3, max_length=3)
    max: list[float] = Field(min_length=3, max_length=3)
    frame: str = "world"


class SafetyConstraint(BaseModel):
    name: str
    type: ConstraintType
    enabled: bool = True
    priority: int = 0
    parameters: dict[str, Any] = Field(default_factory=dict)
    violation_action: ViolationAction = Field(alias="violationAction")

    model_config = {"populate_by_name": True}


# --- Workspace ---


class WorkspaceObject(BaseModel):
    name: str
    pose: Pose | None = None
    type: str = "static"


# --- Planning ---


class PlanStep(BaseModel):
    tool: str
    params: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


# --- Connection / Handshake ---


class ClientInfo(BaseModel):
    name: str
    version: str


class ServerInfo(BaseModel):
    name: str
    version: str
    robot_model: str | None = Field(None, alias="robotModel")
    robot_type: str | None = Field(None, alias="robotType")

    model_config = {"populate_by_name": True}


class Capabilities(BaseModel):
    tools: bool = True
    context: bool = True
    constraints: bool = True
    planning: bool = False
    confirmation: bool = False


# --- JSON-RPC Messages ---


class JSONRPCRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class JSONRPCNotification(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class JSONRPCError(BaseModel):
    code: int
    message: str
    data: Any = None


class JSONRPCResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str
    result: Any = None
    error: JSONRPCError | None = None


# --- Tool Call ---


class CallToolParams(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_id: str = Field(alias="callId")

    model_config = {"populate_by_name": True}


class CallToolResult(BaseModel):
    call_id: str = Field(alias="callId")
    state: ToolState
    result: Any = None
    error: str | None = None
    duration: float | None = None

    model_config = {"populate_by_name": True}


class ToolProgressParams(BaseModel):
    call_id: str = Field(alias="callId")
    progress: float | None = None
    message: str = ""
    state: ToolState

    model_config = {"populate_by_name": True}


# --- Context Subscription ---


class SubscribeContextParams(BaseModel):
    name: str
    max_rate: float | None = Field(None, alias="maxRate")

    model_config = {"populate_by_name": True}


class ContextUpdateParams(BaseModel):
    name: str
    timestamp: str
    data: Any


# --- Planning ---


class RequestPlanParams(BaseModel):
    goal: str
    current_state: dict[str, Any] | None = Field(None, alias="currentState")
    available_tools: list[str] = Field(alias="availableTools")
    constraints: list[SafetyConstraint] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class PlanResult(BaseModel):
    steps: list[PlanStep]
    reasoning: str = ""


# --- Workspace ---


class SetWorkspaceParams(BaseModel):
    name: str
    bounds: BoundingBox
    objects: list[WorkspaceObject] = Field(default_factory=list)


# --- Confirmation ---


class RequestConfirmationParams(BaseModel):
    action: str
    safety_level: SafetyLevel = Field(alias="safetyLevel")
    details: dict[str, Any] = Field(default_factory=dict)
    timeout: float = 30.0

    model_config = {"populate_by_name": True}


class ConfirmationResult(BaseModel):
    confirmed: bool
    confirmed_by: str | None = Field(None, alias="confirmedBy")
    timestamp: str | None = None

    model_config = {"populate_by_name": True}


# --- Emergency Stop ---


class EmergencyStopParams(BaseModel):
    reason: str


# --- Initialize ---


class InitializeParams(BaseModel):
    protocol_version: str = Field(alias="protocolVersion")
    client_info: ClientInfo = Field(alias="clientInfo")
    capabilities: Capabilities = Field(default_factory=Capabilities)

    model_config = {"populate_by_name": True}


class InitializeResult(BaseModel):
    protocol_version: str = Field(alias="protocolVersion")
    server_info: ServerInfo = Field(alias="serverInfo")
    capabilities: Capabilities

    model_config = {"populate_by_name": True}


# --- Error Codes ---


class ARPErrorCode:
    SAFETY_VIOLATION = -40001
    PRECONDITION_FAILED = -40002
    TOOL_NOT_FOUND = -40003
    TOOL_BUSY = -40004
    CONFIRMATION_TIMEOUT = -40005
    CONFIRMATION_DENIED = -40006
    EMERGENCY_STOPPED = -40007
    CONTEXT_NOT_FOUND = -40008
    NOT_INITIALIZED = -40009
