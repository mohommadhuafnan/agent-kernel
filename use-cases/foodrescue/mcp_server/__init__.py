"""FoodRescue AI MCP Server Package.

Exposes the official MCP server instance, tool modules, and runners.
"""

from .server import (
    create_mcp_server,
    get_mcp_server,
    run_stdio,
    get_sse_app,
    get_streamable_http_app
)

from .location_tools import get_live_location
from .matching_tools import find_nearby_organizations, find_nearby_volunteers, match_donation
from .routing_tools import calculate_route, calculate_transport_support, calculate_task_metrics
from .qr_tools import generate_handover_qr, verify_handover_qr
from .task_tools import get_task_status, get_donation, get_foodrescue_system_status

__all__ = [
    "create_mcp_server",
    "get_mcp_server",
    "run_stdio",
    "get_sse_app",
    "get_streamable_http_app",
    "get_live_location",
    "find_nearby_organizations",
    "find_nearby_volunteers",
    "match_donation",
    "calculate_route",
    "calculate_transport_support",
    "calculate_task_metrics",
    "generate_handover_qr",
    "verify_handover_qr",
    "get_task_status",
    "get_donation",
    "get_foodrescue_system_status",
]
