# ARP — Autonomous Robot Protocol

**The open protocol for connecting LLM agents to physical robots.**

ARP provides a standardized interface for AI agents to discover, control, and monitor physical robots with built-in safety enforcement. Think of it as [MCP](https://modelcontextprotocol.io) for the physical world.

```
┌──────────┐     ARP (JSON-RPC / WebSocket)     ┌──────────┐
│ LLM Agent│ ◄──────────────────────────────────►│  Robot   │
│ (Client) │                                     │ (Server) │
└──────────┘                                     └──────────┘
```

## Why ARP?

LLM agents can call APIs, search the web, and write code. But there's no standard way for them to control a robot arm, navigate a mobile robot, or monitor sensor data — all while enforcing safety constraints.

ARP fills this gap with six clean primitives:

| Server → LLM | LLM → Robot |
|---|---|
| **Physical Tools** — callable robot actions with safety metadata | **Planning** — LLM generates action plans on request |
| **Physical Context** — streaming sensor data with coordinate frames | **Workspace** — physical/logical operation boundaries |
| **Safety Constraints** — non-overridable rules at protocol level | **Confirmation** — human approval for dangerous actions |

## Quick Start

### Install

```bash
pip install arp-sdk

# Or from source
git clone https://github.com/mariagorskikh/robotcontextprotocol.git
cd robotcontextprotocol/sdk/python
pip install -e .
```

### Define a Robot Server

```python
from arp_sdk import ARPServer, SafetyMetadata, SafetyLevel

server = ARPServer(name="my-robot", robot_model="Robot Arm v2")

@server.tool(
    description="Move arm to [x, y, z]",
    safety=SafetyMetadata(level=SafetyLevel.NORMAL),
    parameters={"target": {"type": "array"}},
)
async def move_to(target: list[float]) -> dict:
    # Your robot control code here
    return {"reached": target}

asyncio.run(server.run())  # Starts on ws://localhost:8765
```

### Control from an LLM Agent

```python
from arp_sdk import ARPClient

client = ARPClient("ws://localhost:8765")
await client.connect()
await client.initialize()

# Discover what the robot can do
tools = await client.list_tools()

# Execute an action
result = await client.call_tool("move_to", target=[1.0, 0.5, 0.0])
print(result.state)  # "completed"

# Stream sensor data
await client.subscribe_context("odometry", callback, max_rate=10)

# Safety is enforced at the protocol level
result = await client.call_tool("move_to", target=[999, 0, 0])
print(result.error)  # "Safety violation: exceeds workspace boundary"
```

## Safety First

ARP enforces safety constraints at the protocol level — they cannot be overridden by the LLM:

- **Workspace bounds** — reject motions outside defined boundaries
- **Velocity limits** — cap speed
- **Force limits** — cap contact force
- **Collision zones** — no-go regions
- **Emergency stop** — immediate halt, callable by any party
- **Human confirmation** — required for critical actions

## Project Structure

```
├── spec/               Protocol specification
├── schema/             JSON Schema for all messages
├── sdk/python/         Python SDK (arp-sdk)
├── examples/           Working examples
├── website/            Project website
└── .github/workflows/  CI pipeline
```

## Specification

The full protocol specification is at [`spec/specification.md`](spec/specification.md). Key design choices:

- **Transport**: JSON-RPC 2.0 over WebSocket
- **Types**: Pydantic models with JSON Schema validation
- **Lifecycle**: Initialize → Discover → Execute → Shutdown
- **Error codes**: ARP-specific codes (-40001 through -40009) for safety violations, timeouts, etc.

## Development

```bash
cd sdk/python
pip install -e ".[dev]"
pytest tests/ -v
```

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Contributing

ARP is an early-stage protocol and we welcome contributions. Please open an issue to discuss your ideas before submitting a PR.

---

Built by [Maria Gorskikh](https://github.com/mariagorskikh)
