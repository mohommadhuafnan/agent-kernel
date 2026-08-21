"""FoodRescue AI Custom Web API & Frontend Router.

Provides dashboard statistics, live donation/pickup inspection, partner directory,
session state diagnostics, and web UI asset delivery mounted on Agent Kernel RESTAPI.
"""

import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel, Field
import database
from agentkernel.core import Session
from agentkernel.core.session import SessionStore


router = APIRouter()

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@router.get("/", response_class=HTMLResponse)
@router.get("/ui", response_class=HTMLResponse)
async def serve_index():
    """Serve the FoodRescue Single Page Application interface."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="Web UI assets not found.")
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read(), status_code=200)


@router.get("/static/{file_path:path}")
async def serve_static(file_path: str):
    """Serve static assets (CSS, JS, media)."""
    full_path = os.path.join(STATIC_DIR, file_path)
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="Static asset not found.")
    
    media_type = "text/plain"
    if file_path.endswith(".css"):
        media_type = "text/css"
    elif file_path.endswith(".js"):
        media_type = "application/javascript"
    elif file_path.endswith(".html"):
        media_type = "text/html"
    elif file_path.endswith(".json"):
        media_type = "application/json"
    elif file_path.endswith(".svg"):
        media_type = "image/svg+xml"
    elif file_path.endswith(".png"):
        media_type = "image/png"
        
    return FileResponse(full_path, media_type=media_type)


@router.get("/api/stats")
async def get_stats():
    """Get aggregated dashboard KPIs and metrics."""
    stats = database.get_dashboard_stats()
    return JSONResponse(content={"status": "success", "stats": stats})


@router.get("/api/donations")
async def get_donations(status: Optional[str] = Query(None, description="Filter by donation status")):
    """Get all food donations, optionally filtered by status."""
    donations = database.get_all_donations(status=status)
    return JSONResponse(content={"status": "success", "count": len(donations), "donations": donations})


@router.get("/api/donations/{donation_id}")
async def get_donation_detail(donation_id: str):
    """Get detailed donation record with linked pickup tasks, donor, and recipient info."""
    don = database.get_donation_record(donation_id)
    if not don:
        raise HTTPException(status_code=404, detail=f"Donation '{donation_id}' not found.")
    
    donor = database.get_donor_record(don.get("donor_id", ""))
    tasks = database.get_pickup_tasks_by_donation_id(donation_id)
    
    enriched_tasks = []
    for t in tasks:
        td = dict(t)
        if td.get("organization_id"):
            td["organization"] = database.get_organization_record(td["organization_id"])
        if td.get("volunteer_id"):
            td["volunteer"] = database.get_volunteer_record(td["volunteer_id"])
        enriched_tasks.append(td)
        
    return JSONResponse(content={
        "status": "success",
        "donation": don,
        "donor": donor,
        "pickup_tasks": enriched_tasks,
    })


@router.get("/api/organizations")
async def get_organizations():
    """Get list of all registered recipient organizations."""
    orgs = database.get_all_organizations()
    return JSONResponse(content={"status": "success", "count": len(orgs), "organizations": orgs})


@router.get("/api/volunteers")
async def get_volunteers():
    """Get list of all registered volunteers."""
    vols = database.get_all_volunteers()
    return JSONResponse(content={"status": "success", "count": len(vols), "volunteers": vols})


class VolunteerCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    phone: str = Field(..., min_length=6, max_length=32)
    service_area: str = Field(..., min_length=2, max_length=256)
    transport_mode: Optional[str] = Field("Motorbike", max_length=64)
    availability: Optional[str] = Field("immediate, evenings", max_length=128)
    location: Optional[str] = Field(None, max_length=128)


@router.post("/api/volunteers")
async def create_volunteer_endpoint(body: VolunteerCreateRequest):
    """Register a new volunteer courier."""
    import uuid
    vol_id = f"v{uuid.uuid4().hex[:6]}"
    loc = body.location or body.service_area.split(",")[0].strip()
    vol = database.create_volunteer_record(
        volunteer_id=vol_id,
        name=body.name.strip(),
        phone=body.phone.strip(),
        service_area=body.service_area.strip(),
        transport_mode=body.transport_mode or "Motorbike",
        availability=body.availability or "immediate, evenings",
        current_status="available",
        location=loc
    )
    return JSONResponse(content={"status": "success", "volunteer": vol, "message": f"Volunteer '{body.name}' registered successfully."})



@router.get("/api/pickups")
async def get_pickups():
    """Get list of all pickup tasks."""
    tasks = database.get_all_pickup_tasks()
    return JSONResponse(content={"status": "success", "count": len(tasks), "pickup_tasks": tasks})


@router.get("/api/notifications")
async def get_notifications(limit: int = Query(50, ge=1, le=200)):
    """Get recent system notifications feed."""
    notifs = database.get_all_notifications(limit=limit)
    return JSONResponse(content={"status": "success", "count": len(notifs), "notifications": notifs})


@router.get("/api/session-context/{session_id}")
async def get_session_state(session_id: str):
    """Inspect active Agent Kernel session context cache (sanitized for production)."""
    try:
        store = SessionStore.get()
        if store and store.has(session_id):
            sess = store.get(session_id)
            cache = sess.get_non_volatile_cache()
            raw_ctx = dict(cache.items()) if cache else {}
            # Sanitize context dictionary: strip any internal or sensitive fields
            safe_context = {
                k: v for k, v in raw_ctx.items()
                if not k.startswith("_") and "key" not in k.lower() and "token" not in k.lower() and "secret" not in k.lower()
            }
            return JSONResponse(content={
                "status": "success",
                "session_id": session_id,
                "exists": True,
                "context": safe_context,
                "active_donation_id": safe_context.get("current_donation_id"),
                "active_task_id": safe_context.get("current_task_id"),
                "workflow_step": safe_context.get("workflow_step", "IDLE"),
            })
    except Exception:
        pass
    
    return JSONResponse(content={
        "status": "success",
        "session_id": session_id,
        "exists": False,
        "context": {},
        "active_donation_id": None,
        "active_task_id": None,
        "workflow_step": "IDLE",
    })


# =========================================================================
# ADVANCED LOGISTICS, ROUTING & REIMBURSEMENT ENDPOINTS (Phase 7)
# =========================================================================

class RouteCalculationRequest(BaseModel):
    origin: str = Field(..., min_length=1, max_length=256)
    destination: str = Field(..., min_length=1, max_length=256)
    transport_mode: Optional[str] = Field("motorbike", max_length=32)


@router.post("/api/routing/calculate")
async def calculate_route_endpoint(body: RouteCalculationRequest):
    """Compute road/haversine route distance, estimated travel duration, and reimbursement cost."""
    import routing
    res = await routing.calculate_route(
        origin=body.origin,
        destination=body.destination,
        transport_mode=body.transport_mode or "motorbike"
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message", "Route calculation failed."))
    return JSONResponse(content=res)


class LocationUpdateRequest(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    accuracy_m: Optional[float] = Field(None, ge=0.0)
    volunteer_id: Optional[str] = Field(None, max_length=64)


@router.post("/api/pickups/{pickup_id}/location")
async def record_pickup_location_endpoint(pickup_id: str, body: LocationUpdateRequest):
    """Record a live GPS coordinate point for an active pickup task."""
    import uuid
    task = database.get_pickup_task_record(pickup_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Pickup task '{pickup_id}' not found.")

    if task.get("status") not in ["ASSIGNED", "EN_ROUTE"]:
        raise HTTPException(
            status_code=400,
            detail=f"Location tracking rejected: task is in '{task.get('status')}' state. Tracking active only when ASSIGNED or EN_ROUTE."
        )

    vol_id = body.volunteer_id or task.get("volunteer_id") or "v1"
    loc_id = f"loc-{uuid.uuid4().hex[:8]}"
    record = database.record_pickup_location(
        location_id=loc_id,
        pickup_task_id=pickup_id,
        volunteer_id=vol_id,
        latitude=body.latitude,
        longitude=body.longitude,
        accuracy_m=body.accuracy_m
    )
    return JSONResponse(content={"status": "success", "location": record})


@router.get("/api/pickups/{pickup_id}/location")
async def get_pickup_location_endpoint(pickup_id: str):
    """Retrieve latest GPS coordinates and tracking status for a pickup task."""
    task = database.get_pickup_task_record(pickup_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Pickup task '{pickup_id}' not found.")

    latest = database.get_latest_pickup_location(pickup_id)
    return JSONResponse(content={
        "status": "success",
        "pickup_id": pickup_id,
        "task_status": task.get("status"),
        "tracking_active": task.get("status") in ["ASSIGNED", "EN_ROUTE"],
        "latest_location": latest
    })


@router.get("/api/pickups/{pickup_id}/location-history")
async def get_pickup_location_history_endpoint(pickup_id: str, limit: int = Query(50, ge=1, le=200)):
    """Retrieve recent GPS breadcrumbs for a pickup task."""
    task = database.get_pickup_task_record(pickup_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Pickup task '{pickup_id}' not found.")

    history = database.get_pickup_location_history(pickup_id, limit=limit)
    return JSONResponse(content={
        "status": "success",
        "pickup_id": pickup_id,
        "count": len(history),
        "history": history
    })


@router.get("/api/reimbursements")
async def get_reimbursements_endpoint(status: Optional[str] = Query(None)):
    """List volunteer travel reimbursement records."""
    reimbs = database.get_all_reimbursements(status=status)
    return JSONResponse(content={
        "status": "success",
        "count": len(reimbs),
        "reimbursements": reimbs
    })


@router.get("/api/reimbursements/{reimb_id}")
async def get_reimbursement_detail_endpoint(reimb_id: str):
    """Get single reimbursement record."""
    reimb = database.get_reimbursement_record(reimb_id)
    if not reimb:
        raise HTTPException(status_code=404, detail=f"Reimbursement '{reimb_id}' not found.")
    return JSONResponse(content={"status": "success", "reimbursement": reimb})


@router.get("/api/reimbursements/pickup/{pickup_id}")
async def get_pickup_reimbursement_endpoint(pickup_id: str):
    """Get reimbursement record linked to a pickup task."""
    reimb = database.get_reimbursement_by_pickup_id(pickup_id)
    if not reimb:
        return JSONResponse(content={"status": "success", "exists": False, "reimbursement": None})
    return JSONResponse(content={"status": "success", "exists": True, "reimbursement": reimb})


class ReimbursementStatusUpdate(BaseModel):
    status: str = Field(..., description="PENDING, APPROVED, PAID, CANCELLED")
    notes: Optional[str] = Field(None, max_length=500)


@router.post("/api/reimbursements/{reimb_id}/status")
async def update_reimbursement_status_endpoint(reimb_id: str, body: ReimbursementStatusUpdate):
    """Update reimbursement status (e.g. APPROVED, PAID, CANCELLED)."""
    norm = body.status.strip().upper()
    if norm not in {"PENDING", "APPROVED", "PAID", "CANCELLED"}:
        raise HTTPException(status_code=400, detail=f"Invalid status '{body.status}'. Allowed: PENDING, APPROVED, PAID, CANCELLED")

    reimb = database.get_reimbursement_record(reimb_id)
    if not reimb:
        raise HTTPException(status_code=404, detail=f"Reimbursement '{reimb_id}' not found.")

    success = database.update_reimbursement_status_record(reimb_id, norm, notes=body.notes)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update reimbursement record.")

    return JSONResponse(content={
        "status": "success",
        "reimbursement_id": reimb_id,
        "reimbursement_status": norm,
        "message": f"Reimbursement {reimb_id} status updated to {norm}."
    })


from pydantic import BaseModel, Field
from resilient_executor import run_resilient_chat



class ChatRequestBody(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000, description="User prompt text")
    session_id: Optional[str] = Field("default_session", max_length=128)
    agent: Optional[str] = Field("foodrescue_coordinator", max_length=64)


@router.post("/api/v1/chat")
async def chat_endpoint(body: ChatRequestBody):
    """Resilient Multi-Agent & Multi-Model Chat endpoint with automatic 429 failover."""
    res = await run_resilient_chat(
        prompt=body.prompt,
        session_id=body.session_id or "default_session",
        preferred_agent=body.agent
    )
    return JSONResponse(content={
        "result": res.get("result", ""),
        "session_id": res.get("session_id", body.session_id),
        "agent": res.get("agent_used", body.agent),
        "status": "success"
    })


@router.post("/api/reset-demo")
async def reset_demo(request: Request):
    """Reset demo data. Protected against unauthorized execution in production."""
    backend = os.environ.get("FOODRESCUE_DB_BACKEND", "sqlite").lower()
    enable_reset = os.environ.get("ENABLE_DEMO_RESET", "true" if backend == "sqlite" else "false").lower() == "true"
    admin_key = os.environ.get("ADMIN_API_KEY", "")
    req_key = request.headers.get("X-Admin-Key", "")

    if not enable_reset and (not admin_key or req_key != admin_key):
        raise HTTPException(
            status_code=403,
            detail="Administrative demo reset is disabled in production environment."
        )

    try:
        database.reset_database_data()
        database.seed_test_data()
        return JSONResponse(content={
            "status": "success",
            "message": "Demo data reset successfully."
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Database reset operation failed.")


def get_router() -> APIRouter:
    """Return the configured APIRouter for Agent Kernel RESTAPI registration."""
    return router

