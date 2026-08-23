"""FoodRescue AI Custom Web API & Frontend Router.

Provides dashboard statistics, live donation/pickup inspection, partner directory,
session state diagnostics, and web UI asset delivery mounted on Agent Kernel RESTAPI.
"""

import os
from typing import Optional, Dict, Any
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


@router.get("/favicon.ico")
@router.get("/favicon.svg")
async def serve_favicon():
    """Serve the FoodRescue SVG favicon for browsers and search crawlers."""
    fav_path = os.path.join(STATIC_DIR, "favicon.svg")
    if not os.path.exists(fav_path):
        fav_path = os.path.join(STATIC_DIR, "logo.svg")
    if not os.path.exists(fav_path):
        raise HTTPException(status_code=404, detail="Favicon not found.")
    return FileResponse(fav_path, media_type="image/svg+xml")


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


@router.get("/api/dashboard")
@router.get("/api/stats")
async def get_dashboard():
    """Get comprehensive aggregated dashboard KPIs, operational metrics, and activity stream."""
    stats = database.get_dashboard_stats()
    all_users = database.get_all_users()
    all_orgs = database.get_all_organizations()
    all_vols = database.get_all_volunteers()
    avail_vols = database.get_available_volunteers()
    all_tasks = database.get_all_pickup_tasks()
    all_dons = database.get_all_donations()
    recent_events = database.get_all_audit_events(limit=15)

    pending_donations = [d for d in all_dons if d.get("status") in ["AVAILABLE", "MATCHED", "PICKUP_PENDING"]]
    active_pickups = [t for t in all_tasks if t.get("status") in ["ASSIGNED", "EN_ROUTE", "COLLECTED", "PICKED_UP"]]
    completed_pickups = [t for t in all_tasks if t.get("status") in ["COMPLETED", "DELIVERED"]]

    total_qty = float(stats.get("total_food_quantity", 0.0) or 0.0)
    food_rescued_kg = round(total_qty * 0.45, 1)
    co2_saved_kg = round(total_qty * 2.5, 1)

    enriched_stats = {
        "total_donations": len(all_dons),
        "total_food_quantity": round(total_qty, 1),
        "meals_rescued": int(total_qty),
        "food_rescued_kg": food_rescued_kg,
        "co2_saved_kg": co2_saved_kg,
        "available_donations": len([d for d in all_dons if d.get("status") == "AVAILABLE"]),
        "active_pickups": len(active_pickups),
        "completed_deliveries": len(completed_pickups),
        "available_volunteers": len(avail_vols),
        "total_volunteers": len(all_vols),
        "total_organizations": len(all_orgs),
        "registered_organizations": len(all_orgs),
        "active_users": len(all_users),
        "pending_actions": len(pending_donations),
        "status_distribution": stats.get("status_distribution", {}),
        "recent_activity": recent_events,
        "system_health": "operational",
        "backend": os.environ.get("FOODRESCUE_DB_BACKEND", "sqlite")
    }
    return JSONResponse(content={"status": "success", "stats": enriched_stats})


@router.get("/api/users")
async def get_users_endpoint():
    """Get list of all registered WhatsApp and platform users with language, roles, and status."""
    users = database.get_all_users()
    return JSONResponse(content={"status": "success", "count": len(users), "users": users})


@router.get("/api/donors")
async def get_donors_endpoint():
    """Get list of all registered food donor partners."""
    donors = database.get_all_donors()
    return JSONResponse(content={"status": "success", "count": len(donors), "donors": donors})


class DonationCreateRequest(BaseModel):
    food_type: str = Field(..., min_length=2, max_length=128)
    quantity: float = Field(..., gt=0)
    unit: Optional[str] = Field("portions", max_length=32)
    dietary_info: Optional[str] = Field("Standard", max_length=64)
    location: str = Field(..., min_length=2, max_length=128)
    donor_name: Optional[str] = Field("Community Donor", max_length=128)
    donor_phone: Optional[str] = Field("+94770001001", max_length=32)
    pickup_deadline: Optional[str] = Field("Before 8 PM", max_length=64)


@router.post("/api/donations")
async def create_donation_endpoint(body: DonationCreateRequest):
    """Create a new food donation record directly from the web dashboard."""
    import uuid
    import tools
    don_id = f"don-{uuid.uuid4().hex[:8]}"
    d_id = f"d-{uuid.uuid4().hex[:6]}"
    database.create_donor_record(donor_id=d_id, name=body.donor_name, phone=body.donor_phone, location=body.location)
    don = database.create_donation_record(
        donation_id=don_id,
        donor_id=d_id,
        food_type=body.food_type,
        quantity=body.quantity,
        unit=body.unit or "portions",
        dietary_info=body.dietary_info or "Standard",
        location=body.location,
        available_from="Now",
        deadline=body.pickup_deadline or "Before 8 PM"
    )
    # Trigger matching via operational tool
    try:
        tools.find_matching_organizations(food_type=body.food_type, location=body.location)
    except Exception:
        pass
    return JSONResponse(content={"status": "success", "donation": don, "message": "Donation created successfully."})


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


@router.get("/api/conversations")
async def get_conversations_endpoint():
    """Get list of all active conversation threads with latest messages and user profiles."""
    convs = database.get_all_conversations()
    return JSONResponse(content={"status": "success", "count": len(convs), "conversations": convs})


@router.get("/api/conversations/{phone}/messages")
async def get_conversation_messages_endpoint(phone: str, limit: int = Query(100, ge=1, le=500)):
    """Get chronological message history for a specific WhatsApp phone number."""
    msgs = database.get_conversation_messages(phone=phone, limit=limit)
    user = database.get_user_by_phone(phone)
    return JSONResponse(content={
        "status": "success",
        "phone_number": phone,
        "user": user,
        "count": len(msgs),
        "messages": msgs
    })


class ConversationSimulateRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    is_voice: Optional[bool] = Field(False)


@router.post("/api/conversations/{phone}/simulate")
async def simulate_conversation_message_endpoint(phone: str, body: ConversationSimulateRequest):
    """Simulate sending an incoming WhatsApp message from a user for live dashboard demonstrations."""
    import whatsapp_handler
    import uuid

    clean_phone = "".join(ch for ch in str(phone) if ch.isdigit()) or str(phone).strip()
    prompt_text = body.message.strip()

    msg_payload: Dict[str, Any] = {
        "from": clean_phone,
        "id": f"sim_{uuid.uuid4().hex[:10]}",
        "type": "audio" if body.is_voice else "text",
    }
    if body.is_voice:
        msg_payload["audio"] = {"id": "sim_audio_payload", "voice": True}
        msg_payload["text"] = {"body": prompt_text}
    else:
        msg_payload["text"] = {"body": prompt_text}

    res = await whatsapp_handler.process_incoming_whatsapp_message(msg_payload)
    reply_text = res.get("reply", "Thank you. Your request was received.")

    msgs = database.get_conversation_messages(phone=clean_phone)
    user_info = database.get_user_by_phone(phone=clean_phone)
    return JSONResponse(content={
        "status": "success",
        "phone_number": clean_phone,
        "reply": reply_text,
        "user": user_info,
        "messages": msgs
    })


@router.get("/api/live-operations")
async def get_live_operations_endpoint():
    """Get real-time operational rescue pipeline stages."""
    all_dons = database.get_all_donations()
    all_tasks = database.get_all_pickup_tasks()

    task_by_don = {t.get("donation_id"): t for t in all_tasks}
    operations = []

    for don in all_dons:
        don_id = don.get("id")
        status = don.get("status", "AVAILABLE").upper()
        task = task_by_don.get(don_id, {})

        # Compute pipeline step (1 to 7)
        stage_map = {
            "AVAILABLE": {"step": 1, "label": "Donation Available", "badge": "available"},
            "MATCHED": {"step": 2, "label": "Organization Matched", "badge": "matched"},
            "ASSIGNED": {"step": 3, "label": "Volunteer Assigned", "badge": "assigned"},
            "EN_ROUTE": {"step": 4, "label": "Pickup In Progress", "badge": "in_transit"},
            "COLLECTED": {"step": 5, "label": "Food Collected", "badge": "collected"},
            "PICKED_UP": {"step": 5, "label": "Food Collected", "badge": "collected"},
            "DELIVERING": {"step": 6, "label": "Out for Delivery", "badge": "delivering"},
            "DELIVERED": {"step": 7, "label": "Delivered & Rescued", "badge": "completed"},
            "COMPLETED": {"step": 7, "label": "Delivered & Rescued", "badge": "completed"},
            "CANCELLED": {"step": 0, "label": "Cancelled", "badge": "cancelled"},
        }
        info = stage_map.get(status, {"step": 1, "label": status, "badge": "pending"})

        # Enrich entities
        donor = database.get_donor_record(don.get("donor_id", ""))
        org = database.get_organization_record(task.get("organization_id", "")) if task else None
        vol = database.get_volunteer_record(task.get("volunteer_id", "")) if task else None

        operations.append({
            "donation_id": don_id,
            "task_id": task.get("id"),
            "food_type": don.get("food_type"),
            "quantity": don.get("quantity"),
            "unit": don.get("unit", "portions"),
            "dietary_info": don.get("dietary_information", "Standard"),
            "status": status,
            "stage_step": info["step"],
            "stage_label": info["label"],
            "stage_badge": info["badge"],
            "pickup_location": don.get("pickup_location"),
            "delivery_location": task.get("delivery_location") or (org.get("location") if org else "Recipient Kitchen"),
            "pickup_deadline": don.get("pickup_deadline"),
            "donor_name": donor.get("name") if donor else "Donor Partner",
            "organization_name": org.get("name") if org else (task.get("organization_name") or "Awaiting Recipient"),
            "volunteer_name": vol.get("name") if vol else (task.get("volunteer_name") or "Awaiting Volunteer"),
            "volunteer_phone": vol.get("phone") if vol else None,
            "transport_mode": vol.get("transport_mode") if vol else "Motorbike",
            "estimated_distance_km": task.get("total_distance_km", 4.8),
            "estimated_duration_mins": task.get("pickup_duration_minutes", 15) + task.get("delivery_duration_minutes", 20),
            "estimated_transport_cost": task.get("estimated_transport_cost", 350.0),
            "created_at": don.get("created_at"),
            "updated_at": don.get("updated_at") or don.get("created_at")
        })

    return JSONResponse(content={"status": "success", "count": len(operations), "operations": operations})


@router.get("/api/agent-events")
async def get_agent_events_endpoint(limit: int = Query(100, ge=1, le=500)):
    """Get safe operational audit events representing Agent Kernel decisions and actions."""
    events = database.get_all_audit_events(limit=limit)
    return JSONResponse(content={"status": "success", "count": len(events), "events": events})


@router.get("/api/locations")
async def get_map_locations_endpoint():
    """Get privacy-preserving operational coordinates for map display across Sri Lanka."""
    import routing

    all_orgs = database.get_all_organizations()
    all_vols = database.get_all_volunteers()
    all_tasks = database.get_all_pickup_tasks()
    all_dons = database.get_all_donations()

    markers = []
    lats = []
    lngs = []

    # 1. Organization recipient hubs
    for o in all_orgs:
        lat = o.get("latitude")
        lng = o.get("longitude")
        if lat is None or lng is None:
            loc_str = str(o.get("location", "Colombo 7"))
            coords = routing.geocode_location(loc_str) or (6.9069, 79.8708)
            lat, lng = coords

        lats.append(lat)
        lngs.append(lng)
        markers.append({
            "id": f"org-{o.get('id')}",
            "type": "organization",
            "title": o.get("name"),
            "subtitle": f"Accepted: {str(o.get('accepted_food_types', 'Meals'))[:40]}...",
            "latitude": round(lat, 6),
            "longitude": round(lng, 6),
            "location_name": o.get("location"),
            "status": "active"
        })

    # 2. Volunteer couriers
    for v in all_vols:
        lat = v.get("current_latitude") or v.get("latitude")
        lng = v.get("current_longitude") or v.get("longitude")
        if lat is None or lng is None:
            loc_str = str(v.get("current_location") or v.get("service_area") or v.get("location") or "Colombo 3")
            coords = routing.geocode_location(loc_str) or (6.9056, 79.8519)
            lat, lng = coords
            # Jitter slightly for visual distinction
            lat += (hash(str(v.get("id", ""))) % 10 - 5) * 0.002
            lng += (hash(str(v.get("id", ""))[::-1]) % 10 - 5) * 0.002

        lats.append(lat)
        lngs.append(lng)
        markers.append({
            "id": f"vol-{v.get('id')}",
            "type": "volunteer",
            "title": v.get("name"),
            "subtitle": f"Status: {v.get('current_status', 'available').title()} • {v.get('transport_mode', 'Motorbike')}",
            "latitude": round(lat, 6),
            "longitude": round(lng, 6),
            "location_name": v.get("service_area") or v.get("location"),
            "status": v.get("current_status", "available")
        })

    # 3. Active pickups & Tasks
    for t in all_tasks:
        if t.get("status") in ["ASSIGNED", "EN_ROUTE", "COLLECTED", "IN_TRANSIT", "PENDING", "OFFERED"]:
            lat = t.get("pickup_latitude")
            lng = t.get("pickup_longitude")
            if lat is None or lng is None:
                p_loc = str(t.get("pickup_location", "Colombo"))
                coords = routing.geocode_location(p_loc) or (6.9344, 79.8428)
                lat, lng = coords
            lats.append(lat)
            lngs.append(lng)
            markers.append({
                "id": f"pickup-{t.get('id')}",
                "type": "pickup_point",
                "title": f"Pickup Task {t.get('id')}",
                "subtitle": f"Deliver to: {t.get('delivery_location')}",
                "latitude": round(lat, 6),
                "longitude": round(lng, 6),
                "location_name": t.get("pickup_location"),
                "status": t.get("status")
            })

    # 4. Available donations
    for d in all_dons:
        if d.get("status") in ["AVAILABLE", "MATCHED"]:
            lat = d.get("latitude")
            lng = d.get("longitude")
            if lat is None or lng is None:
                d_loc = str(d.get("pickup_location", "Colombo"))
                coords = routing.geocode_location(d_loc) or (6.9344, 79.8428)
                lat, lng = coords
            lats.append(lat)
            lngs.append(lng)
            markers.append({
                "id": f"don-{d.get('id')}",
                "type": "donation",
                "title": f"{d.get('food_type', 'Food')} ({d.get('quantity', 0)} {d.get('unit', 'portions')})",
                "subtitle": f"Location: {d.get('pickup_location')} • Status: {d.get('status')}",
                "latitude": round(lat, 6),
                "longitude": round(lng, 6),
                "location_name": d.get("pickup_location"),
                "status": d.get("status")
            })

    # Dynamic Sri Lanka center
    center_lat = round(sum(lats) / len(lats), 4) if lats else 6.9271
    center_lng = round(sum(lngs) / len(lngs), 4) if lngs else 79.8612

    return JSONResponse(content={
        "status": "success",
        "center": {"lat": center_lat, "lng": center_lng, "zoom": 12 if len(markers) > 0 else 8},
        "count": len(markers),
        "markers": markers
    })


class RouteCalculationRequest(BaseModel):
    origin: Any = Field(..., description="Origin landmark/address string or coordinate dict/array")
    destination: Any = Field(..., description="Destination landmark/address string or coordinate dict/array")
    transport_mode: Optional[str] = Field("car", description="Transport mode: car, motorbike, bicycle, walking, van, tuk")


class PickupRouteCalculationRequest(BaseModel):
    volunteer: Optional[Any] = Field(None, description="Volunteer location or coordinates")
    donation: Any = Field(..., description="Donation pickup location or coordinates")
    organization: Any = Field(..., description="Organization delivery location or coordinates")
    transport_mode: Optional[str] = Field("motorbike", description="Transport mode: motorbike, car, bicycle, van, tuk")


@router.post("/api/routes/calculate")
async def calculate_route_endpoint(body: RouteCalculationRequest):
    """Calculate road route distance, duration, and geometry between two points via GraphHopper Routing API."""
    import routing_service
    result = await routing_service.calculate_route(
        origin=body.origin,
        destination=body.destination,
        transport_mode=body.transport_mode or "car"
    )
    return JSONResponse(content=result)


@router.post("/api/routes/pickup-route")
async def calculate_pickup_route_endpoint(body: PickupRouteCalculationRequest):
    """Calculate complete two-leg pickup route (Volunteer -> Donation -> Organization) via GraphHopper Routing API."""
    import routing_service
    result = await routing_service.calculate_pickup_route(
        volunteer_location=body.volunteer,
        donation_location=body.donation,
        organization_location=body.organization,
        transport_mode=body.transport_mode or "motorbike"
    )
    return JSONResponse(content=result)


@router.get("/api/reports")
async def get_reports_endpoint():
    """Get aggregated impact analytics and reporting metrics."""
    stats = database.get_dashboard_stats()
    total_qty = float(stats.get("total_food_quantity", 0.0) or 0.0)
    all_vols = database.get_all_volunteers()
    all_orgs = database.get_all_organizations()
    all_dons = database.get_all_donations()

    # Regional distribution
    region_counts = {}
    for d in all_dons:
        loc = d.get("pickup_location", "Colombo").title()
        region_counts[loc] = region_counts.get(loc, 0) + 1

    # Volunteer rankings
    vol_leaders = []
    for v in all_vols:
        vol_leaders.append({
            "name": v.get("name"),
            "transport_mode": v.get("transport_mode", "Motorbike"),
            "completed_pickups": v.get("completed_pickups", 0),
            "status": v.get("current_status", "available")
        })
    vol_leaders.sort(key=lambda x: x["completed_pickups"], reverse=True)

    return JSONResponse(content={
        "status": "success",
        "summary": {
            "total_meals_rescued": int(total_qty),
            "total_food_kg": round(total_qty * 0.45, 1),
            "co2_emissions_prevented_kg": round(total_qty * 2.5, 1),
            "water_saved_litres": int(total_qty * 140),
            "financial_value_lkr": int(total_qty * 450),
            "active_partners": len(all_orgs),
            "active_couriers": len(all_vols)
        },
        "regional_distribution": region_counts,
        "volunteer_leaderboard": vol_leaders
    })


@router.get("/api/settings")
async def get_settings_endpoint():
    """Get system transport configuration and WhatsApp integration health."""
    transport_cfg = database.get_transport_settings()
    wa_status = {
        "phone_number": "+94 75 526 3482",
        "phone_number_id": "1285744151285887",
        "waba_id": "2279553849254105",
        "app_id": "1591721079088296",
        "webhook_url": "https://foodrescue-ai-ten.vercel.app/whatsapp/webhook",
        "verify_token_configured": bool(os.environ.get("WHATSAPP_VERIFY_TOKEN")),
        "access_token_configured": bool(os.environ.get("WHATSAPP_ACCESS_TOKEN")),
        "database_backend": os.environ.get("FOODRESCUE_DB_BACKEND", "sqlite"),
        "status": "ONLINE"
    }
    return JSONResponse(content={
        "status": "success",
        "transport_cost": transport_cfg,
        "whatsapp_integration": wa_status
    })


class SettingsUpdateRequest(BaseModel):
    base_fare: Optional[float] = Field(None, ge=0)
    cost_per_km: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = Field("LKR", max_length=10)
    rates_by_vehicle: Optional[Dict[str, float]] = Field(None)
    vehicle_multipliers: Optional[dict] = Field(None)


@router.post("/api/settings")
async def update_settings_endpoint(body: SettingsUpdateRequest):
    """Update dynamic transport reimbursement calculation rates."""
    current = database.get_transport_settings()
    if body.base_fare is not None:
        current["base_fare"] = body.base_fare
    if body.cost_per_km is not None:
        current["cost_per_km"] = body.cost_per_km
    if body.currency:
        current["currency"] = body.currency
    if body.rates_by_vehicle:
        current["rates_by_vehicle"] = body.rates_by_vehicle
    if body.vehicle_multipliers:
        current["vehicle_multipliers"] = body.vehicle_multipliers

    updated = database.update_transport_settings(current)
    return JSONResponse(content={
        "status": "success",
        "transport_cost": updated,
        "message": "Transport cost configuration updated successfully."
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
        database.reset_database_data(wipe_all=False)
        database.seed_test_data()
        return JSONResponse(content={
            "status": "success",
            "message": "Demo data reset successfully."
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Database reset operation failed.")


@router.post("/api/reset-all")
async def reset_all_data():
    """Completely wipe all data, donations, tasks, volunteers, orgs, users, messages, and audit logs to start fresh from 0."""
    try:
        database.reset_database_data(wipe_all=True)
        return JSONResponse(content={
            "status": "success",
            "message": "All data wiped successfully. Application is starting fresh from 0."
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Reset operation failed: {exc}")


def get_router() -> APIRouter:
    """Return the configured APIRouter for Agent Kernel RESTAPI registration."""
    return router

