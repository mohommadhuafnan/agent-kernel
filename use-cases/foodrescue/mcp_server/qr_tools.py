"""FoodRescue AI MCP QR Handover Tools.

Exposes physical handover QR code generation and mobile camera verification
interfaces through standardized MCP tools, reusing the core verification engine.
"""

import logging
from typing import Optional, Dict, Any
import database
import qr_service

logger = logging.getLogger("foodrescue.mcp.qr")


async def generate_handover_qr(task_id: str, qr_type: str) -> Dict[str, Any]:
    """Generate a secure, cryptographically hashed handover QR code token and URL.

    Args:
        task_id: Unique pickup task identifier.
        qr_type: Type of handover QR ('pickup' or 'delivery').

    Returns:
        Dictionary containing QR ID, token, verification URL, image link, and expiry.
    """
    clean_task_id = str(task_id).strip()
    clean_type = str(qr_type).strip().upper()
    if clean_type not in ["PICKUP", "DELIVERY"]:
        return {"status": "error", "message": "qr_type must be either 'pickup' or 'delivery'"}

    logger.info(f"MCP_TOOL_CALLED: generate_handover_qr for task '{clean_task_id}' ({clean_type})")

    task = database.get_pickup_task_record(clean_task_id)
    if not task:
        return {"status": "error", "message": f"Task '{clean_task_id}' not found."}

    # Check for existing active QR of this type
    task_qrs = database.get_qr_codes_for_task(clean_task_id)
    existing_qr = next((q for q in task_qrs if q.get("qr_type") == clean_type and q.get("status") == "ACTIVE"), None)

    if existing_qr:
        token = existing_qr.get("token")
    else:
        prefix = "PK" if clean_type == "PICKUP" else "DL"
        token = qr_service.generate_secure_token(prefix)
        token_hash = qr_service.hash_token(token)
        qr_id = f"qr-{prefix.lower()}-{clean_task_id}"

        existing_qr = database.create_qr_code_record(
            qr_id=qr_id,
            task_id=clean_task_id,
            donation_id=task.get("donation_id", ""),
            qr_type=clean_type,
            token=token,
            token_hash=token_hash,
            organization_id=task.get("organization_id"),
            assigned_volunteer_id=task.get("volunteer_id"),
            status="ACTIVE"
        )

    verif_url = qr_service.build_verification_url(clean_type, token)
    image_url = f"{qr_service.get_base_url()}/api/qr/{token}.png"

    logger.info(f"MCP_TOOL_SUCCESS: generate_handover_qr created {clean_type} QR token for '{clean_task_id}'")
    return {
        "status": "success",
        "qr_id": existing_qr.get("id") or existing_qr.get("qr_id"),
        "task_id": clean_task_id,
        "qr_type": clean_type,
        "token": token,
        "verification_url": verif_url,
        "image_url": image_url,
        "created_at": existing_qr.get("created_at") or ""
    }


async def verify_handover_qr(
    token: str,
    volunteer_id: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None
) -> Dict[str, Any]:
    """Verify and consume a physical handover QR code token at pickup or delivery doorstep.

    Args:
        token: Secure token extracted from the scanned QR code (e.g. 'FR-PK-...', 'FR-DL-...').
        volunteer_id: Optional unique identifier of the scanning volunteer courier.
        latitude: Optional GPS latitude where the scan occurred.
        longitude: Optional GPS longitude where the scan occurred.

    Returns:
        Verification status, updated task state, next operational instructions.
    """
    clean_token = str(token).strip()
    logger.info(f"MCP_TOOL_CALLED: verify_handover_qr for token '{clean_token[:15]}...' by vol '{volunteer_id}'")

    gps_coords = None
    if latitude is not None and longitude is not None:
        gps_coords = {"latitude": float(latitude), "longitude": float(longitude)}

    res = database.verify_qr_code_record(
        token=clean_token,
        volunteer_id=volunteer_id,
        gps_coords=gps_coords
    )

    if res.get("success"):
        updated_task = res.get("task") or {}
        new_status = updated_task.get("status")
        logger.info(f"MCP_TOOL_SUCCESS: verify_handover_qr successfully verified token for task '{res.get('task_id')}'")
        return {
            "status": "success",
            "success": True,
            "qr_type": res.get("qr_type"),
            "task_id": res.get("task_id"),
            "new_status": new_status,
            "verified_at": res.get("verified_at"),
            "verified_by": res.get("verified_by"),
            "message": f"QR code verified successfully. Task status updated to {new_status}."
        }
    else:
        logger.warning(f"MCP_TOOL_FAILURE: verify_handover_qr rejected token: {res.get('message')}")
        return {
            "status": "error",
            "success": False,
            "error": res.get("error", "VERIFICATION_FAILED"),
            "message": res.get("message", "QR verification failed.")
        }
