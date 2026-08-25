"""FoodRescue AI MCP Task & Health Tools.

Provides task status inspection, donation lookups, and overall system health diagnostics.
"""

import os
import logging
from typing import Optional, Dict, Any
import database
import qr_service
import routing

logger = logging.getLogger("foodrescue.mcp.task")


async def get_task_status(task_id: str) -> Dict[str, Any]:
    """Retrieve full details, status, linked parties, and active QR codes for a pickup task.

    Args:
        task_id: Unique pickup task identifier.

    Returns:
        Comprehensive task operational card with status, donor, recipient, courier, and route.
    """
    clean_task_id = str(task_id).strip()
    logger.info(f"MCP_TOOL_CALLED: get_task_status for '{clean_task_id}'")

    task = database.get_pickup_task_record(clean_task_id)
    if not task:
        logger.warning(f"MCP_TOOL_FAILURE: Task '{clean_task_id}' not found")
        return {
            "status": "not_found",
            "task_id": clean_task_id,
            "message": f"Task '{clean_task_id}' not found in database."
        }

    don = database.get_donation_record(task.get("donation_id", ""))
    org = database.get_organization_record(task.get("organization_id", ""))
    vol = database.get_volunteer_record(task.get("volunteer_id", "")) if task.get("volunteer_id") else None
    task_qrs = database.get_qr_codes_for_task(clean_task_id)

    pk_qr = next((q for q in task_qrs if q.get("qr_type") == "PICKUP" and q.get("status") == "ACTIVE"), None)
    dl_qr = next((q for q in task_qrs if q.get("qr_type") == "DELIVERY" and q.get("status") == "ACTIVE"), None)

    logger.info(f"MCP_TOOL_SUCCESS: get_task_status completed for '{clean_task_id}' (status: {task.get('status')})")
    return {
        "status": "success",
        "task_id": clean_task_id,
        "current_status": task.get("status", "OPEN"),
        "donation": {
            "id": task.get("donation_id"),
            "food_type": don.get("food_type", "") if don else "",
            "quantity": don.get("quantity", 0) if don else 0,
            "unit": don.get("unit", "portions") if don else "portions",
            "pickup_deadline": don.get("pickup_deadline", "") if don else ""
        } if don else None,
        "donor": {
            "name": don.get("donor_name", "Donor Partner") if don else "Donor Partner",
            "pickup_location": task.get("pickup_location", ""),
        },
        "recipient_organization": {
            "id": task.get("organization_id"),
            "name": org.get("name", "Recipient Organization") if org else "Recipient Organization",
            "delivery_location": task.get("delivery_location", ""),
        } if org else None,
        "assigned_volunteer": {
            "id": vol.get("id"),
            "name": vol.get("name"),
            "transport_mode": vol.get("transport_mode", "Motorbike"),
        } if vol else None,
        "qr_tokens": {
            "pickup_active": pk_qr is not None,
            "pickup_token": pk_qr.get("token") if pk_qr else None,
            "delivery_active": dl_qr is not None,
            "delivery_token": dl_qr.get("token") if dl_qr else None,
        },
        "timestamps": {
            "created_at": task.get("created_at", ""),
            "updated_at": task.get("updated_at", "")
        }
    }


async def get_donation(donation_id: str) -> Dict[str, Any]:
    """Retrieve full details of a food surplus donation record.

    Args:
        donation_id: Unique donation identifier.

    Returns:
        Donation entity including food description, quantity, donor name, location, and status.
    """
    clean_don_id = str(donation_id).strip()
    logger.info(f"MCP_TOOL_CALLED: get_donation for '{clean_don_id}'")

    don = database.get_donation_record(clean_don_id)
    if not don:
        logger.warning(f"MCP_TOOL_FAILURE: Donation '{clean_don_id}' not found")
        return {
            "status": "not_found",
            "donation_id": clean_don_id,
            "message": f"Donation '{clean_don_id}' not found in database."
        }

    logger.info(f"MCP_TOOL_SUCCESS: get_donation retrieved '{clean_don_id}'")
    return {
        "status": "success",
        "donation": don
    }


async def get_foodrescue_system_status() -> Dict[str, Any]:
    """Check and return actual health metrics of all FoodRescue underlying subsystems."""
    logger.info("MCP_TOOL_CALLED: get_foodrescue_system_status")

    # 1. Database Health
    db_backend = os.environ.get("FOODRESCUE_DB_BACKEND", "sqlite").lower()
    db_ok = False
    try:
        database.get_repository().get_dashboard_stats()
        db_ok = True
    except Exception:
        db_ok = False

    # 2. Routing Engine Health
    routing_ok = bool(routing.geocode_location("Kegalle") is not None)

    # 3. QR Engine Health
    qr_ok = bool(qr_service.get_base_url() != "")

    # 4. WhatsApp Cloud API Configuration
    wa_token = bool(os.environ.get("WHATSAPP_ACCESS_TOKEN"))
    wa_phone_id = bool(os.environ.get("WHATSAPP_PHONE_NUMBER_ID"))
    wa_configured = wa_token and wa_phone_id

    overall = "operational" if (db_ok and routing_ok and qr_ok) else "degraded"
    logger.info(f"MCP_TOOL_SUCCESS: get_foodrescue_system_status reports '{overall}'")

    return {
        "status": "success",
        "system_health": overall,
        "mcp_server": "active",
        "database": {
            "backend": db_backend,
            "connected": db_ok
        },
        "routing_service": {
            "status": "operational" if routing_ok else "unavailable",
            "district_directory": "ready"
        },
        "qr_service": {
            "status": "operational" if qr_ok else "unavailable",
            "base_url": qr_service.get_base_url()
        },
        "whatsapp_integration": {
            "configured": wa_configured,
            "mode": "live" if wa_configured else "simulator/mock"
        }
    }
