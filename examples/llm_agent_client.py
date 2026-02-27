"""Example: LLM agent controlling a robot via ARP.

This demonstrates how an AI agent can discover and use
a robot's capabilities through the ARP protocol.

Run the server first:
    python simple_robot_server.py

Then run this client:
    python llm_agent_client.py
"""

import asyncio

from arp_sdk.client import ARPClient
from arp_sdk.types import ToolProgressParams, ContextUpdateParams, ToolState


async def main():
    # Connect to the robot
    client = ARPClient(
        url="ws://localhost:8765",
        client_name="claude-robot-agent",
        client_version="1.0.0",
    )

    print("Connecting to robot...")
    await client.connect()

    # Initialize the connection
    info = await client.initialize()
    print(f"Connected to: {info.server_info.name}")
    print(f"Robot model: {info.server_info.robot_model}")
    print(f"Capabilities: tools={info.capabilities.tools}, context={info.capabilities.context}")
    print()

    # Discover available tools
    tools = await client.list_tools()
    print("Available tools:")
    for tool in tools:
        print(f"  - {tool.name}: {tool.description} [safety: {tool.safety.level.value}]")
    print()

    # Discover context sources
    sources = await client.list_context()
    print("Context sources:")
    for source in sources:
        print(f"  - {source.name}: {source.description} ({source.data_type.value})")
    print()

    # Check safety constraints
    constraints = await client.list_constraints()
    print("Safety constraints:")
    for c in constraints:
        print(f"  - {c.name}: {c.type.value} → {c.violation_action.value}")
    print()

    # Subscribe to odometry updates
    odom_updates = []

    async def on_odom(update: ContextUpdateParams):
        odom_updates.append(update)

    await client.subscribe_context("odometry", on_odom, max_rate=5.0)

    # Execute a pick-and-place task
    print("=" * 50)
    print("Executing pick-and-place task")
    print("=" * 50)

    # Step 1: Move to the object
    print("\n1. Moving to object position...")
    result = await client.call_tool("move_to", target=[0.5, 0.3, 0.2])
    print(f"   Result: {result.state.value} — {result.result}")

    # Step 2: Pick up the object
    print("\n2. Picking up the red block...")
    result = await client.call_tool("pick_up", object_id="red_block")
    print(f"   Result: {result.state.value} — {result.result}")

    # Step 3: Move to the placement position
    print("\n3. Moving to shelf...")
    result = await client.call_tool("move_to", target=[0.8, 0.0, 0.7])
    print(f"   Result: {result.state.value} — {result.result}")

    # Step 4: Place the object
    print("\n4. Placing on shelf...")
    result = await client.call_tool("place", surface="shelf_top")
    print(f"   Result: {result.state.value} — {result.result}")

    # Step 5: Go home
    print("\n5. Returning home...")
    result = await client.call_tool("go_home")
    print(f"   Result: {result.state.value} — {result.result}")

    # Show odometry data collected
    await client.unsubscribe_context("odometry")
    print(f"\nCollected {len(odom_updates)} odometry updates during task")

    # Try a safety violation
    print("\n" + "=" * 50)
    print("Testing safety constraint...")
    print("=" * 50)
    print("\nAttempting to move outside workspace [5.0, 0.0, 0.0]...")
    result = await client.call_tool("move_to", target=[5.0, 0.0, 0.0])
    print(f"Result: {result.state.value} — {result.error}")

    # Clean disconnect
    print("\nDisconnecting...")
    await client.disconnect()
    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
