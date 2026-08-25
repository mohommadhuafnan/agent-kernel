"""FoodRescue AI Custom MCP Server.

Built using the official Model Context Protocol (MCP) Python SDK.
Provides a standardized tool interface for Agent Kernel to interact with
real FoodRescue location, matching, dynamic routing, transport calculation,
and QR handover verification services without duplicating business logic.
"""

import sys
import os
import asyncio
import logging
from typing import Optional, Dict, Any, List

# Ensure foodrescue root directory is in Python path for submodule imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from mcp.server.mcpserver import MCPServer
from .location_tools import get_live_location
from .matching_tools import find_nearby_organizations, find_nearby_volunteers, match_donation
from .routing_tools import calculate_route, calculate_transport_support, calculate_task_metrics
from .qr_tools import generate_handover_qr, verify_handover_qr
from .task_tools import get_task_status, get_donation, get_foodrescue_system_status

logger = logging.getLogger("foodrescue.mcp.server")

# Cached singleton server instance
_SERVER_INSTANCE: Optional[MCPServer] = None


def create_mcp_server(name: str = "foodrescue-ai") -> MCPServer:
    """Create and configure the official FoodRescue AI MCP Server instance."""
    server = MCPServer(
        name=name,
        instructions=(
            "FoodRescue AI MCP Server exposes operational tools for surplus food recovery: "
            "GPS location lookups, proximity organization & courier matching, dynamic road routing, "
            "volunteer transport reimbursement calculations, and cryptographic QR handover verifications."
        )
    )

    # 1. Location Tools
    server.tool(name="get_live_location")(get_live_location)

    # 2. Matching Tools
    server.tool(name="find_nearby_organizations")(find_nearby_organizations)
    server.tool(name="find_nearby_volunteers")(find_nearby_volunteers)
    server.tool(name="match_donation")(match_donation)

    # 3. Routing & Logistics Tools
    server.tool(name="calculate_route")(calculate_route)
    server.tool(name="calculate_transport_support")(calculate_transport_support)
    server.tool(name="calculate_task_metrics")(calculate_task_metrics)

    # 4. QR Handover Tools
    server.tool(name="generate_handover_qr")(generate_handover_qr)
    server.tool(name="verify_handover_qr")(verify_handover_qr)

    # 5. Task & System Health Tools
    server.tool(name="get_task_status")(get_task_status)
    server.tool(name="get_donation")(get_donation)
    server.tool(name="get_foodrescue_system_status")(get_foodrescue_system_status)

    logger.info(f"Initialized FoodRescue MCP Server '{name}' with {len(server._tool_manager._tools)} registered tools")
    return server


def get_mcp_server() -> MCPServer:
    """Retrieve the cached MCP Server singleton."""
    global _SERVER_INSTANCE
    if _SERVER_INSTANCE is None:
        server_name = os.environ.get("MCP_SERVER_NAME", "foodrescue-ai")
        _SERVER_INSTANCE = create_mcp_server(server_name)
    return _SERVER_INSTANCE


def run_stdio() -> None:
    """Run the MCP server over standard input/output (stdio transport)."""
    server = get_mcp_server()
    logger.info("Starting FoodRescue MCP Server over stdio transport...")
    asyncio.run(server.run_stdio_async())


def get_sse_app():
    """Get the Starlette/ASGI app for Server-Sent Events (SSE) / HTTP transport."""
    server = get_mcp_server()
    return server.sse_app()


def get_streamable_http_app():
    """Get the Starlette/ASGI app for streamable HTTP transport."""
    server = get_mcp_server()
    return server.streamable_http_app()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    run_stdio()
