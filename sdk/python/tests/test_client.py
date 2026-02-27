"""Tests for ARP Client — unit tests using mocked transport."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from arp_sdk.client import ARPClient, ARPClientError
from arp_sdk.types import ToolState


class TestClientNotInitialized:
    def test_list_tools_before_init_raises(self):
        client = ARPClient()
        with pytest.raises(ARPClientError, match="not initialized"):
            # Can't use await in sync test, so just check the guard
            client._ensure_initialized()

    def test_client_defaults(self):
        client = ARPClient()
        assert client.url == "ws://localhost:8765"
        assert client.client_info.name == "arp-client"
        assert client._initialized is False

    def test_custom_client_info(self):
        client = ARPClient(
            url="ws://robot:9999",
            client_name="my-agent",
            client_version="2.0.0",
        )
        assert client.url == "ws://robot:9999"
        assert client.client_info.name == "my-agent"
        assert client.client_info.version == "2.0.0"


class TestClientInitialize:
    async def test_initialize_success(self):
        client = ARPClient()
        client._transport = AsyncMock()
        client._transport.connect = AsyncMock()
        client._transport.on_notification = MagicMock()
        client._transport.send_request = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "0.1.0",
                "serverInfo": {"name": "test-server", "version": "0.1.0"},
                "capabilities": {"tools": True, "context": True, "constraints": True},
            },
        })

        await client.connect()
        info = await client.initialize()
        assert client._initialized is True
        assert info.server_info.name == "test-server"

    async def test_initialize_error(self):
        client = ARPClient()
        client._transport = AsyncMock()
        client._transport.connect = AsyncMock()
        client._transport.on_notification = MagicMock()
        client._transport.send_request = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32603, "message": "Server error"},
        })

        await client.connect()
        with pytest.raises(ARPClientError):
            await client.initialize()


class TestClientTools:
    async def test_list_tools(self):
        client = ARPClient()
        client._initialized = True
        client._transport = AsyncMock()
        client._transport.send_request = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [
                    {
                        "name": "move_to",
                        "description": "Move the arm",
                        "parameters": {},
                        "safety": {"level": "normal"},
                    }
                ]
            },
        })

        tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "move_to"

    async def test_call_tool_success(self):
        client = ARPClient()
        client._initialized = True
        client._transport = AsyncMock()
        client._transport.send_request = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 3,
            "result": {
                "callId": "call_1",
                "state": "completed",
                "result": {"reached": [1, 0, 0]},
                "duration": 1.5,
            },
        })

        result = await client.call_tool("move_to", target=[1, 0, 0])
        assert result.state == ToolState.COMPLETED
        assert result.result == {"reached": [1, 0, 0]}

    async def test_call_tool_error(self):
        client = ARPClient()
        client._initialized = True
        client._transport = AsyncMock()
        client._transport.send_request = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 3,
            "error": {"code": -40001, "message": "Safety violation"},
        })

        result = await client.call_tool("move_to", target=[10, 0, 0])
        assert result.state == ToolState.FAILED
        assert "Safety violation" in result.error


class TestClientContext:
    async def test_list_context(self):
        client = ARPClient()
        client._initialized = True
        client._transport = AsyncMock()
        client._transport.send_request = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 4,
            "result": {
                "sources": [
                    {"name": "odometry", "description": "Robot pose", "dataType": "pose"}
                ]
            },
        })

        sources = await client.list_context()
        assert len(sources) == 1
        assert sources[0].name == "odometry"

    async def test_subscribe_context(self):
        client = ARPClient()
        client._initialized = True
        client._transport = AsyncMock()
        client._transport.send_request = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 5,
            "result": {"subscribed": "odometry"},
        })

        callback = AsyncMock()
        await client.subscribe_context("odometry", callback, max_rate=5.0)
        assert "odometry" in client._context_callbacks


class TestClientConstraints:
    async def test_list_constraints(self):
        client = ARPClient()
        client._initialized = True
        client._transport = AsyncMock()
        client._transport.send_request = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 6,
            "result": {
                "constraints": [
                    {
                        "name": "workspace",
                        "type": "workspace_bound",
                        "parameters": {"min": [-2, -2, 0], "max": [2, 2, 3]},
                        "violationAction": "reject",
                    }
                ]
            },
        })

        constraints = await client.list_constraints()
        assert len(constraints) == 1
        assert constraints[0].name == "workspace"
