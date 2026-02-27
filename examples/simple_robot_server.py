"""Example: ARP server for a simulated robot arm.

This demonstrates how to build an ARP server that exposes
a robot's capabilities to LLM agents.

Run:
    python simple_robot_server.py
"""

import asyncio
import math
import random

from arp_sdk.server import ARPServer
from arp_sdk.types import (
    SafetyMetadata,
    SafetyLevel,
    SafetyConstraint,
    ConstraintType,
    ViolationAction,
)

# Create the server
server = ARPServer(
    name="sim-robot-arm",
    version="0.1.0",
    robot_model="Simulated 6-DOF Arm",
    robot_type="manipulator",
    host="0.0.0.0",
    port=8765,
)

# --- Simulated robot state ---
robot_state = {
    "position": [0.0, 0.0, 0.5],
    "gripper": "open",
    "holding": None,
    "joint_angles": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
}


# --- Register Physical Tools ---


@server.tool(
    description="Move the robot arm end-effector to a target [x, y, z] position in world frame",
    safety=SafetyMetadata(level=SafetyLevel.NORMAL, description="Moves within workspace"),
    parameters={
        "type": "object",
        "properties": {
            "target": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Target position [x, y, z] in meters",
            }
        },
        "required": ["target"],
    },
    estimated_duration=2.0,
)
async def move_to(target: list[float]) -> dict:
    """Simulate moving to a position over time."""
    start = robot_state["position"].copy()
    steps = 10
    for i in range(steps):
        t = (i + 1) / steps
        robot_state["position"] = [
            start[j] + t * (target[j] - start[j]) for j in range(3)
        ]
        await asyncio.sleep(0.1)
    return {"reached": robot_state["position"]}


@server.tool(
    description="Close the gripper to pick up an object at the current position",
    safety=SafetyMetadata(level=SafetyLevel.ELEVATED, description="Actuates gripper"),
    parameters={
        "type": "object",
        "properties": {
            "object_id": {
                "type": "string",
                "description": "ID of the object to pick up",
            }
        },
        "required": ["object_id"],
    },
    estimated_duration=1.0,
)
async def pick_up(object_id: str) -> dict:
    """Simulate picking up an object."""
    await asyncio.sleep(0.5)
    robot_state["gripper"] = "closed"
    robot_state["holding"] = object_id
    return {"picked": object_id, "gripper": "closed"}


@server.tool(
    description="Open the gripper to place the held object at the current position",
    safety=SafetyMetadata(level=SafetyLevel.NORMAL, description="Releases gripper"),
    parameters={
        "type": "object",
        "properties": {
            "surface": {
                "type": "string",
                "description": "Name of the surface to place on",
            }
        },
    },
    estimated_duration=0.5,
)
async def place(surface: str = "table") -> dict:
    """Simulate placing an object."""
    await asyncio.sleep(0.3)
    held = robot_state["holding"]
    robot_state["gripper"] = "open"
    robot_state["holding"] = None
    return {"placed": held, "on": surface, "gripper": "open"}


@server.tool(
    description="Return the arm to its home position [0, 0, 0.5]",
    safety=SafetyMetadata(level=SafetyLevel.NORMAL),
    parameters={},
    estimated_duration=2.0,
)
async def go_home() -> dict:
    """Move to home position."""
    robot_state["position"] = [0.0, 0.0, 0.5]
    await asyncio.sleep(0.5)
    return {"position": robot_state["position"]}


# --- Register Context Sources ---


@server.context(
    name="odometry",
    description="Current end-effector pose in world frame",
    data_type="pose",
    coordinate_frame="world",
    update_rate=10.0,
)
async def get_odometry():
    return {
        "position": {
            "x": robot_state["position"][0],
            "y": robot_state["position"][1],
            "z": robot_state["position"][2],
        },
        "frame": "world",
    }


@server.context(
    name="joint_states",
    description="Current joint angles in radians",
    data_type="joints",
    update_rate=10.0,
)
async def get_joints():
    # Simulate slight noise
    return {
        "angles": [a + random.gauss(0, 0.001) for a in robot_state["joint_angles"]],
        "names": ["joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "joint_6"],
    }


@server.context(
    name="gripper_state",
    description="Current gripper state",
    data_type="custom",
    update_rate=5.0,
)
async def get_gripper():
    return {
        "state": robot_state["gripper"],
        "holding": robot_state["holding"],
    }


# --- Register Safety Constraints ---

server.add_constraint(SafetyConstraint(
    name="workspace_boundary",
    type=ConstraintType.WORKSPACE_BOUND,
    parameters={
        "type": "box",
        "min": [-1.0, -1.0, 0.0],
        "max": [1.0, 1.0, 1.5],
        "frame": "world",
    },
    violationAction=ViolationAction.REJECT,
    priority=100,
))

server.add_constraint(SafetyConstraint(
    name="velocity_limit",
    type=ConstraintType.VELOCITY_LIMIT,
    parameters={"max_linear": 0.5, "max_angular": 1.0},
    violationAction=ViolationAction.CLAMP,
    priority=90,
))


# --- Run ---

if __name__ == "__main__":
    print("Starting ARP server for Simulated Robot Arm...")
    print("Connect with: ws://localhost:8765")
    print("Press Ctrl+C to stop.")
    asyncio.run(server.run())
