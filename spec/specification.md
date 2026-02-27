# Autonomous Robot Protocol (ARP) — Specification

**Version:** 0.1.0
**Status:** Draft
**Date:** 2026-02-27

---

## 1. Introduction

The Autonomous Robot Protocol (ARP) is an open protocol that enables Large Language Model (LLM) agents to communicate with and control physical robots through a standardized interface. ARP provides structured primitives for action execution, sensor data streaming, and safety enforcement.

### 1.1 Design Goals

- **Safety-first**: Non-overridable safety constraints enforced at the protocol level
- **LLM-native**: Designed for natural language agents, not just programmatic control
- **Transport-agnostic**: JSON-RPC 2.0 messages, default transport is WebSocket
- **Minimal surface area**: Small number of primitives that compose well
- **Real-time capable**: Streaming sensor data and execution state updates

### 1.2 Architecture

```
┌─────────────┐         ARP (JSON-RPC / WebSocket)         ┌─────────────┐
│  LLM Agent  │ ◄──────────────────────────────────────────► │    Robot     │
│  (Client)   │                                              │  (Server)   │
└─────────────┘                                              └─────────────┘
```

The **ARP Server** runs on or near the robot. It exposes the robot's capabilities as Physical Tools, streams sensor data as Physical Context, and enforces Safety Constraints.

The **ARP Client** runs alongside the LLM agent. It discovers available tools, calls them, subscribes to context streams, and responds to server requests for planning or confirmation.

---

## 2. Transport Layer

### 2.1 Protocol

ARP uses **JSON-RPC 2.0** as its message format. The default transport is **WebSocket** (`ws://` or `wss://`).

All messages are UTF-8 encoded JSON. Binary payloads (e.g., images) are Base64-encoded within JSON fields.

### 2.2 Connection Lifecycle

```
Client                              Server
  │                                    │
  │──── WebSocket Connect ────────────►│
  │                                    │
  │──── arp.initialize ───────────────►│
  │◄─── InitializeResult ─────────────│
  │                                    │
  │──── arp.listTools ────────────────►│
  │◄─── ListToolsResult ──────────────│
  │                                    │
  │──── arp.callTool ─────────────────►│
  │◄─── Progress notifications ───────│
  │◄─── CallToolResult ───────────────│
  │                                    │
  │──── arp.shutdown ─────────────────►│
  │◄─── ShutdownResult ───────────────│
  │                                    │
  │──── WebSocket Close ──────────────►│
```

### 2.3 Message Format

All requests follow JSON-RPC 2.0:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "arp.callTool",
  "params": { ... }
}
```

Responses:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": { ... }
}
```

Notifications (no `id`):

```json
{
  "jsonrpc": "2.0",
  "method": "arp.toolProgress",
  "params": { ... }
}
```

---

## 3. Server Primitives (Robot → LLM)

### 3.1 Physical Tools

Physical Tools are callable robot actions. Each tool has:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Unique identifier (e.g., `move_to`, `pick_up`) |
| `description` | string | yes | Human-readable description for the LLM |
| `parameters` | JSON Schema | yes | Input parameters schema |
| `safety` | SafetyMetadata | yes | Safety classification and metadata |
| `preconditions` | Condition[] | no | Conditions that must be true before execution |
| `effects` | Effect[] | no | Expected state changes after execution |
| `estimatedDuration` | number | no | Expected execution time in seconds |

#### 3.1.1 SafetyMetadata

```json
{
  "level": "normal | elevated | critical",
  "requiresConfirmation": false,
  "reversible": true,
  "description": "Moves the arm to a position within the workspace"
}
```

Safety levels:
- **normal**: Safe to execute without confirmation
- **elevated**: May affect environment; confirmation recommended
- **critical**: Could cause damage or harm; confirmation required

#### 3.1.2 Tool Execution State Machine

```
         call
IDLE ──────────► RUNNING ──────► COMPLETED
                    │
                    ├──────► FAILED
                    │
                    └──────► CANCELLED
```

Progress notifications are sent during `RUNNING`:

```json
{
  "jsonrpc": "2.0",
  "method": "arp.toolProgress",
  "params": {
    "callId": "call_123",
    "progress": 0.45,
    "message": "Moving to waypoint 3/7",
    "state": "running"
  }
}
```

### 3.2 Physical Context

Physical Context provides streaming sensor and state data from the robot.

#### 3.2.1 Context Sources

Each context source has:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Unique identifier (e.g., `odometry`, `camera_front`) |
| `description` | string | yes | Human-readable description |
| `dataType` | string | yes | One of: `pose`, `joints`, `pointcloud`, `image`, `imu`, `custom` |
| `coordinateFrame` | string | no | Reference frame (e.g., `world`, `base_link`, `camera_optical`) |
| `updateRate` | number | no | Expected updates per second |
| `schema` | JSON Schema | no | Schema for the data payload |

#### 3.2.2 Subscribing to Context

```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "arp.subscribeContext",
  "params": {
    "name": "odometry",
    "maxRate": 10
  }
}
```

Context updates are sent as notifications:

```json
{
  "jsonrpc": "2.0",
  "method": "arp.contextUpdate",
  "params": {
    "name": "odometry",
    "timestamp": "2026-02-27T12:00:00.000Z",
    "data": {
      "position": { "x": 1.2, "y": 0.5, "z": 0.0 },
      "orientation": { "x": 0, "y": 0, "z": 0.1, "w": 0.995 },
      "frame": "world"
    }
  }
}
```

### 3.3 Safety Constraints

Safety Constraints are **non-overridable** rules enforced at the protocol level. The server MUST reject any tool call that would violate an active constraint.

#### 3.3.1 Constraint Types

| Type | Description | Example |
|------|-------------|---------|
| `velocity_limit` | Maximum velocity in m/s or rad/s | `{"max_linear": 0.5, "max_angular": 1.0}` |
| `workspace_bound` | Geometric boundary the robot must stay within | `{"type": "box", "min": [-1,-1,0], "max": [1,1,2]}` |
| `force_limit` | Maximum force/torque | `{"max_force": 10.0, "max_torque": 5.0}` |
| `collision_zone` | Regions the robot must avoid | `{"zones": [{"center": [0,0.5,0.5], "radius": 0.3}]}` |
| `emergency_stop` | Immediate halt condition | `{"trigger": "force_exceeded"}` |
| `rate_limit` | Maximum tool call frequency | `{"max_calls_per_second": 2}` |

#### 3.3.2 Constraint Definition

```json
{
  "name": "workspace_boundary",
  "type": "workspace_bound",
  "enabled": true,
  "priority": 100,
  "parameters": {
    "type": "box",
    "min": [-2.0, -2.0, 0.0],
    "max": [2.0, 2.0, 3.0],
    "frame": "world"
  },
  "violation_action": "reject"
}
```

`violation_action` may be:
- `reject` — Reject the tool call with an error
- `clamp` — Modify parameters to satisfy the constraint
- `emergency_stop` — Halt all motion immediately

#### 3.3.3 Emergency Stop

Any party can trigger an emergency stop:

```json
{
  "jsonrpc": "2.0",
  "method": "arp.emergencyStop",
  "params": {
    "reason": "Unexpected obstacle detected"
  }
}
```

The server MUST immediately halt all motion and cancel all running tool calls.

---

## 4. Client Primitives (LLM → Robot)

### 4.1 Planning

The server can request the client (LLM) to generate or revise a plan:

```json
{
  "jsonrpc": "2.0",
  "id": 10,
  "method": "arp.requestPlan",
  "params": {
    "goal": "Pick up the red block and place it on the shelf",
    "currentState": { ... },
    "availableTools": ["move_to", "pick_up", "place"],
    "constraints": [ ... ]
  }
}
```

The client responds with a plan:

```json
{
  "jsonrpc": "2.0",
  "id": 10,
  "result": {
    "steps": [
      { "tool": "move_to", "params": { "target": [0.5, 0.3, 0.1] }, "description": "Move to red block" },
      { "tool": "pick_up", "params": { "object": "red_block" }, "description": "Grasp the red block" },
      { "tool": "move_to", "params": { "target": [1.0, 0.0, 1.2] }, "description": "Move to shelf" },
      { "tool": "place", "params": { "surface": "shelf_top" }, "description": "Place block on shelf" }
    ],
    "reasoning": "Direct pick-and-place approach. Block is within reach from current position."
  }
}
```

### 4.2 Workspace

Workspace defines the physical and logical boundaries the robot operates within:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "arp.setWorkspace",
  "params": {
    "name": "assembly_station",
    "bounds": {
      "type": "box",
      "min": [-1.0, -1.0, 0.0],
      "max": [1.0, 1.0, 2.0],
      "frame": "world"
    },
    "objects": [
      { "name": "table", "pose": { "position": [0, 0, 0.75] }, "type": "static" },
      { "name": "red_block", "pose": { "position": [0.5, 0.3, 0.8] }, "type": "manipulable" }
    ]
  }
}
```

### 4.3 Confirmation

The server requests human approval for dangerous actions:

```json
{
  "jsonrpc": "2.0",
  "id": 20,
  "method": "arp.requestConfirmation",
  "params": {
    "action": "Activate cutting tool at position [0.3, 0.1, 0.5]",
    "safetyLevel": "critical",
    "details": {
      "tool": "activate_cutter",
      "params": { "position": [0.3, 0.1, 0.5], "speed": 1000 }
    },
    "timeout": 30
  }
}
```

The client MUST present this to a human operator. Response:

```json
{
  "jsonrpc": "2.0",
  "id": 20,
  "result": {
    "confirmed": true,
    "confirmedBy": "operator_jane",
    "timestamp": "2026-02-27T12:05:00Z"
  }
}
```

If no confirmation within `timeout` seconds, the action is automatically rejected.

---

## 5. Standard Methods

### 5.1 Lifecycle Methods

| Method | Direction | Description |
|--------|-----------|-------------|
| `arp.initialize` | Client → Server | Initialize connection, exchange capabilities |
| `arp.shutdown` | Client → Server | Graceful shutdown |
| `arp.emergencyStop` | Either → Either | Immediate halt |

### 5.2 Tool Methods

| Method | Direction | Description |
|--------|-----------|-------------|
| `arp.listTools` | Client → Server | List available tools |
| `arp.callTool` | Client → Server | Execute a tool |
| `arp.cancelTool` | Client → Server | Cancel a running tool call |
| `arp.toolProgress` | Server → Client | Execution progress notification |

### 5.3 Context Methods

| Method | Direction | Description |
|--------|-----------|-------------|
| `arp.listContext` | Client → Server | List available context sources |
| `arp.subscribeContext` | Client → Server | Subscribe to a context source |
| `arp.unsubscribeContext` | Client → Server | Unsubscribe from a context source |
| `arp.contextUpdate` | Server → Client | Context data notification |

### 5.4 Constraint Methods

| Method | Direction | Description |
|--------|-----------|-------------|
| `arp.listConstraints` | Client → Server | List active safety constraints |
| `arp.getConstraint` | Client → Server | Get details of a specific constraint |

### 5.5 Client Primitives

| Method | Direction | Description |
|--------|-----------|-------------|
| `arp.requestPlan` | Server → Client | Request LLM to generate a plan |
| `arp.setWorkspace` | Client → Server | Define workspace boundaries |
| `arp.requestConfirmation` | Server → Client | Request human confirmation |

---

## 6. Error Handling

### 6.1 Standard Error Codes

| Code | Name | Description |
|------|------|-------------|
| -32700 | Parse Error | Invalid JSON |
| -32600 | Invalid Request | Invalid JSON-RPC |
| -32601 | Method Not Found | Unknown method |
| -32602 | Invalid Params | Invalid parameters |
| -32603 | Internal Error | Server internal error |
| -40001 | Safety Violation | Tool call violates a safety constraint |
| -40002 | Precondition Failed | Tool preconditions not met |
| -40003 | Tool Not Found | Unknown tool name |
| -40004 | Tool Busy | Tool is already executing |
| -40005 | Confirmation Timeout | Human confirmation timed out |
| -40006 | Confirmation Denied | Human denied the action |
| -40007 | Emergency Stopped | Operation halted by e-stop |
| -40008 | Context Not Found | Unknown context source |
| -40009 | Not Initialized | Connection not initialized |

### 6.2 Error Response Format

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -40001,
    "message": "Safety violation: position [3.0, 0, 0] exceeds workspace boundary",
    "data": {
      "constraint": "workspace_boundary",
      "requested": [3.0, 0.0, 0.0],
      "limit": [2.0, 2.0, 3.0]
    }
  }
}
```

---

## 7. Initialize Handshake

### 7.1 Request

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "arp.initialize",
  "params": {
    "protocolVersion": "0.1.0",
    "clientInfo": {
      "name": "claude-robot-agent",
      "version": "1.0.0"
    },
    "capabilities": {
      "planning": true,
      "confirmation": true
    }
  }
}
```

### 7.2 Response

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "0.1.0",
    "serverInfo": {
      "name": "franka-arp-server",
      "version": "0.1.0",
      "robotModel": "Franka Emika Panda",
      "robotType": "manipulator"
    },
    "capabilities": {
      "tools": true,
      "context": true,
      "constraints": true,
      "planning": true,
      "confirmation": true
    }
  }
}
```

---

## 8. Versioning

ARP follows semantic versioning. The protocol version is exchanged during initialization. Servers and clients SHOULD support at least one previous minor version for backward compatibility.

---

## 9. Security Considerations

- **Authentication**: Implementations SHOULD support token-based authentication during the WebSocket handshake
- **Encryption**: Production deployments MUST use `wss://` (TLS)
- **Rate limiting**: Servers SHOULD enforce rate limits on tool calls
- **Audit logging**: All tool calls and safety events SHOULD be logged
- **Principle of least privilege**: Clients should only be granted access to tools they need

---

## 10. Appendix: Type Definitions

See `schema/arp.schema.json` for the complete JSON Schema defining all protocol types and messages.

See `sdk/python/arp_sdk/types.py` for Pydantic model implementations.
