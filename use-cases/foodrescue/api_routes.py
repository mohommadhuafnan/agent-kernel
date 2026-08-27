"""FoodRescue AI Custom Web API & Frontend Router.

Provides dashboard statistics, live donation/pickup inspection, partner directory,
session state diagnostics, and web UI asset delivery mounted on Agent Kernel RESTAPI.
"""

import os
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse as BaseJSONResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel, Field
import database
from agentkernel.core import Session
from agentkernel.core.session import SessionStore


class JSONResponse(BaseJSONResponse):
    """Dynamic API response with strict no-cache headers to prevent CDN/browser stale states."""
    def __init__(self, content: Any, status_code: int = 200, headers: Optional[Dict[str, str]] = None, **kwargs):
        no_cache_headers = {
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0"
        }
        if headers:
            no_cache_headers.update(headers)
        super().__init__(content=content, status_code=status_code, headers=no_cache_headers, **kwargs)


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
        "backend": (os.environ.get("FOODRESCUE_DATABASE") or os.environ.get("FOODRESCUE_DB_BACKEND", "supabase")).lower()
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


@router.delete("/api/donations/{donation_id}")
async def delete_donation_endpoint(donation_id: str):
    """Delete a food donation record and associated tasks/QR codes."""
    success = database.delete_donation_record(donation_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Donation '{donation_id}' not found or could not be deleted.")
    return JSONResponse(content={"status": "success", "message": f"Donation {donation_id} deleted permanently."})


@router.delete("/api/donors/{donor_id}")
async def delete_donor_endpoint(donor_id: str):
    """Delete a donor partner record."""
    success = database.delete_donor_record(donor_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Donor '{donor_id}' not found or could not be deleted.")
    return JSONResponse(content={"status": "success", "message": f"Donor {donor_id} deleted permanently."})


@router.delete("/api/organizations/{org_id}")
async def delete_organization_endpoint(org_id: str):
    """Delete a recipient organization record."""
    success = database.delete_organization_record(org_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Organization '{org_id}' not found or could not be deleted.")
    return JSONResponse(content={"status": "success", "message": f"Organization {org_id} deleted permanently."})


@router.delete("/api/volunteers/{vol_id}")
async def delete_volunteer_endpoint(vol_id: str):
    """Delete a volunteer courier record."""
    success = database.delete_volunteer_record(vol_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Volunteer '{vol_id}' not found or could not be deleted.")
    return JSONResponse(content={"status": "success", "message": f"Volunteer {vol_id} deleted permanently."})


@router.delete("/api/users/{phone}")
async def delete_user_endpoint(phone: str):
    """Delete a user profile and session state."""
    success = database.delete_user_record(phone)
    if not success:
        raise HTTPException(status_code=404, detail=f"User '{phone}' not found or could not be deleted.")
    return JSONResponse(content={"status": "success", "message": f"User {phone} deleted permanently."})


@router.delete("/api/pickup-tasks/{task_id}")
async def delete_pickup_task_endpoint(task_id: str):
    """Delete a pickup task record."""
    success = database.delete_pickup_task_record(task_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found or could not be deleted.")
    return JSONResponse(content={"status": "success", "message": f"Task {task_id} deleted permanently."})


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
            "LOGGED": {"step": 1, "label": "Donation Logged", "badge": "available"},
            "MATCHED": {"step": 2, "label": "Organization Matched", "badge": "matched"},
            "NOTIFIED": {"step": 3, "label": "Volunteer Dispatched", "badge": "assigned"},
            "ASSIGNED": {"step": 3, "label": "Volunteer Assigned", "badge": "assigned"},
            "ACCEPTED": {"step": 3, "label": "Volunteer Assigned", "badge": "assigned"},
            "PICKUP_ASSIGNED": {"step": 3, "label": "Volunteer Assigned", "badge": "assigned"},
            "PICKUP_PENDING": {"step": 3, "label": "Volunteer Assigned", "badge": "assigned"},
            "EN_ROUTE": {"step": 4, "label": "Pickup In Progress", "badge": "in_transit"},
            "COLLECTED": {"step": 5, "label": "Food Collected", "badge": "collected"},
            "PICKED_UP": {"step": 5, "label": "Food Collected", "badge": "collected"},
            "IN_TRANSIT": {"step": 6, "label": "Out for Delivery", "badge": "delivering"},
            "DELIVERING": {"step": 6, "label": "Out for Delivery", "badge": "delivering"},
            "DELIVERED": {"step": 7, "label": "Delivered & Rescued", "badge": "completed"},
            "DISTRIBUTED": {"step": 7, "label": "Delivered & Rescued", "badge": "completed"},
            "COMPLETED": {"step": 7, "label": "Delivered & Rescued", "badge": "completed"},
            "CANCELLED": {"step": 0, "label": "Cancelled", "badge": "cancelled"},
        }
        info = stage_map.get(status, {"step": 1, "label": status, "badge": "pending"})

        # Enrich entities & QR statuses
        donor = database.get_donor_record(don.get("donor_id", ""))
        org = database.get_organization_record(task.get("organization_id", "")) if task else None
        vol = database.get_volunteer_record(task.get("volunteer_id", "")) if task else None

        task_id = task.get("id")
        qrs = database.get_qr_codes_for_task(task_id) if task_id else []
        pk_q = next((q for q in qrs if q.get("qr_type") == "PICKUP"), None)
        dl_q = next((q for q in qrs if q.get("qr_type") == "DELIVERY"), None)

        # Dynamically calculate distance and transport cost
        calc_dist = task.get("total_distance_km")
        calc_cost = task.get("estimated_transport_cost")

        if not calc_dist or float(calc_dist) <= 0.0:
            import routing
            p_loc = don.get("pickup_location") or don.get("location") or ""
            d_loc = (task.get("delivery_location") if task else None) or (org.get("location") if org else None) or (org.get("service_area") if org else None) or ""
            
            p_coords = None
            if don.get("latitude") and don.get("longitude"):
                try:
                    p_coords = (float(don["latitude"]), float(don["longitude"]))
                except Exception:
                    pass
            if not p_coords and don.get("location_pin"):
                p_coords = routing.extract_coordinates_from_text(str(don["location_pin"]))
            if not p_coords and don_id:
                try:
                    d_locs = database.get_locations_for_donation(don_id)
                    if d_locs:
                        p_coords = (float(d_locs[0]["latitude"]), float(d_locs[0]["longitude"]))
                except Exception:
                    pass
            if not p_coords and p_loc:
                p_coords = routing.geocode_location(p_loc)
                
            d_coords = None
            if org and org.get("latitude") and org.get("longitude"):
                try:
                    d_coords = (float(org["latitude"]), float(org["longitude"]))
                except Exception:
                    pass
            if not d_coords and org and org.get("location_pin"):
                d_coords = routing.extract_coordinates_from_text(str(org["location_pin"]))
            if not d_coords and d_loc:
                d_coords = routing.geocode_location(d_loc)
            elif not d_coords and p_coords:
                p_dist = routing.resolve_district(p_loc)
                all_orgs = database.get_all_organizations()
                for o_cand in all_orgs:
                    c_loc = o_cand.get("location") or o_cand.get("service_area") or ""
                    if not p_dist or routing.resolve_district(c_loc) == p_dist:
                        c_coords = routing.geocode_location(c_loc)
                        if c_coords:
                            d_coords = c_coords
                            if not org:
                                org = o_cand
                            break

            if p_coords and d_coords:
                calc_dist = round(max(0.5, routing.calculate_haversine_distance(p_coords[0], p_coords[1], d_coords[0], d_coords[1]) * 1.25), 1)
            elif p_coords:
                calc_dist = round(max(1.2, (hash(str(p_loc)) % 30) / 10.0 + 1.8), 1)
            else:
                calc_dist = round(max(1.5, (hash(f"{don_id}_{status}") % 40) / 10.0 + 2.0), 1)

            v_mode = (vol.get("transport_mode") if vol else "motorbike").lower()
            cost_info = routing.calculate_transport_estimate(calc_dist, v_mode)
            calc_cost = float(cost_info.get("estimated_support_amount") or (calc_dist * 50.0))

            if task and task.get("id"):
                try:
                    database.update_pickup_task_logistics(task_id=task["id"], total_distance_km=calc_dist, estimated_transport_cost=int(calc_cost))
                except Exception:
                    pass
        else:
            calc_dist = float(calc_dist)
            calc_cost = float(calc_cost) if calc_cost is not None else float(calc_dist * 50.0)

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
            "estimated_distance_km": calc_dist,
            "estimated_duration_mins": max(10, int(calc_dist * 3.5)),
            "estimated_transport_cost": int(calc_cost),
            "pickup_qr_status": pk_q.get("status") if pk_q else ("VERIFIED" if info["step"] >= 5 else ("ACTIVE" if info["step"] >= 3 else "PENDING")),
            "pickup_qr_token": pk_q.get("token") if pk_q else None,
            "delivery_qr_status": dl_q.get("status") if dl_q else ("VERIFIED" if info["step"] >= 7 else ("ACTIVE" if info["step"] >= 5 else "PENDING")),
            "delivery_qr_token": dl_q.get("token") if dl_q else None,
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
            loc_str = str(o.get("location") or o.get("service_area") or "")
            coords = routing.geocode_location(loc_str)
            if not coords and loc_str:
                dist = routing.resolve_district(loc_str)
                if dist and dist.lower() in routing.KNOWN_COORDINATES:
                    coords = routing.KNOWN_COORDINATES[dist.lower()]
            if coords:
                lat, lng = coords

        if lat is not None and lng is not None:
            lats.append(lat)
            lngs.append(lng)
            markers.append({
                "id": f"org-{o.get('id')}",
                "type": "organization",
                "title": o.get("name"),
                "subtitle": f"Accepted: {str(o.get('accepted_food_types', 'Meals'))[:40]}...",
                "latitude": round(lat, 6),
                "longitude": round(lng, 6),
                "location_name": o.get("location") or "Organization Hub",
                "status": "active"
            })

    # 2. Volunteer couriers
    for v in all_vols:
        lat = v.get("current_latitude") or v.get("latitude")
        lng = v.get("current_longitude") or v.get("longitude")
        if lat is None or lng is None:
            loc_str = str(v.get("current_location") or v.get("service_area") or v.get("location") or "")
            coords = routing.geocode_location(loc_str)
            if not coords and loc_str:
                dist = routing.resolve_district(loc_str)
                if dist and dist.lower() in routing.KNOWN_COORDINATES:
                    coords = routing.KNOWN_COORDINATES[dist.lower()]
            if coords:
                lat, lng = coords
                # Jitter slightly for visual distinction
                lat += (hash(str(v.get("id", ""))) % 10 - 5) * 0.002
                lng += (hash(str(v.get("id", ""))[::-1]) % 10 - 5) * 0.002

        if lat is not None and lng is not None:
            lats.append(lat)
            lngs.append(lng)
            markers.append({
                "id": f"vol-{v.get('id')}",
                "type": "volunteer",
                "title": v.get("name"),
                "subtitle": f"Status: {v.get('current_status', 'available').title()} • {v.get('transport_mode', 'Motorbike')}",
                "latitude": round(lat, 6),
                "longitude": round(lng, 6),
                "location_name": v.get("service_area") or v.get("location") or "Courier Location",
                "status": v.get("current_status", "available")
            })

    # 3. Active pickups & Tasks
    for t in all_tasks:
        if t.get("status") in ["ASSIGNED", "EN_ROUTE", "COLLECTED", "IN_TRANSIT", "PENDING", "OFFERED"]:
            lat = t.get("pickup_latitude")
            lng = t.get("pickup_longitude")
            if lat is None or lng is None:
                p_loc = str(t.get("pickup_location") or "")
                coords = routing.geocode_location(p_loc)
                if not coords and p_loc:
                    dist = routing.resolve_district(p_loc)
                    if dist and dist.lower() in routing.KNOWN_COORDINATES:
                        coords = routing.KNOWN_COORDINATES[dist.lower()]
                if coords:
                    lat, lng = coords

            if lat is not None and lng is not None:
                lats.append(lat)
                lngs.append(lng)
                markers.append({
                    "id": f"pickup-{t.get('id')}",
                    "type": "pickup_point",
                    "title": f"Pickup Task {t.get('id')}",
                    "subtitle": f"Deliver to: {t.get('delivery_location')}",
                    "latitude": round(lat, 6),
                    "longitude": round(lng, 6),
                    "location_name": t.get("pickup_location") or "Pickup Location",
                    "status": t.get("status")
                })

    # 4. Available donations
    for d in all_dons:
        if d.get("status") in ["AVAILABLE", "MATCHED"]:
            lat = d.get("latitude")
            lng = d.get("longitude")
            if lat is None or lng is None:
                d_loc = str(d.get("pickup_location") or "")
                coords = routing.geocode_location(d_loc)
                if not coords and d_loc:
                    dist = routing.resolve_district(d_loc)
                    if dist and dist.lower() in routing.KNOWN_COORDINATES:
                        coords = routing.KNOWN_COORDINATES[dist.lower()]
                if coords:
                    lat, lng = coords

            if lat is not None and lng is not None:
                lats.append(lat)
                lngs.append(lng)
                markers.append({
                    "id": f"don-{d.get('id')}",
                    "type": "donation",
                    "title": f"{d.get('food_type', 'Food')} ({d.get('quantity', 0)} {d.get('unit', 'portions')})",
                    "subtitle": f"Location: {d.get('pickup_location')} • Status: {d.get('status')}",
                    "latitude": round(lat, 6),
                    "longitude": round(lng, 6),
                    "location_name": d.get("pickup_location") or "Donation Location",
                    "status": d.get("status")
                })

    # Dynamic center calculation
    center_lat = round(sum(lats) / len(lats), 4) if lats else 7.2520
    center_lng = round(sum(lngs) / len(lngs), 4) if lngs else 80.3464

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


@router.get("/api/tasks/{task_id}/route")
async def get_task_dynamic_route_endpoint(task_id: str):
    """Get active dynamic road route for a pickup task based on its lifecycle phase and live GPS coordinates."""
    import routing_service
    result = await routing_service.calculate_task_dynamic_route(task_id)
    return JSONResponse(content=result)


class VolunteerLocationUpdateRequest(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    address: Optional[str] = Field(None)
    status: Optional[str] = Field("AVAILABLE")


@router.post("/api/volunteers/{volunteer_id}/location")
async def update_volunteer_location_endpoint(volunteer_id: str, body: VolunteerLocationUpdateRequest):
    """Update volunteer live GPS position and refresh active task routing metrics."""
    vol = database.get_volunteer_record(volunteer_id)
    if not vol:
        raise HTTPException(status_code=404, detail=f"Volunteer '{volunteer_id}' not found.")

    coords = {"latitude": body.latitude, "longitude": body.longitude}
    addr = body.address or f"{body.latitude:.5f}, {body.longitude:.5f}"

    database.update_volunteer_availability(
        volunteer_id=volunteer_id,
        status=body.status or "AVAILABLE",
        current_location=addr,
        current_coordinates=coords
    )

    # Check if volunteer has active task
    v_tasks = database.get_pickup_tasks_for_volunteer(volunteer_id)
    active_tasks = [t for t in v_tasks if t.get("status") in ["ASSIGNED", "EN_ROUTE", "COLLECTED", "IN_TRANSIT"]]

    updated_route = None
    if active_tasks:
        target_task = active_tasks[-1]
        import routing_service
        route_res = await routing_service.calculate_task_dynamic_route(
            target_task["id"],
            volunteer_location_override=coords
        )
        if route_res.get("success"):
            updated_route = route_res
            dist_km = route_res.get("distance_km", 0.0)
            est_cost = route_res.get("estimated_cost", 0.0)
            database.update_pickup_task_logistics(
                task_id=target_task["id"],
                total_distance_km=dist_km,
                estimated_transport_cost=est_cost
            )

    return JSONResponse(content={
        "status": "success",
        "volunteer_id": volunteer_id,
        "current_coordinates": coords,
        "current_location": addr,
        "active_route": updated_route
    })


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
        "database_backend": (os.environ.get("FOODRESCUE_DATABASE") or os.environ.get("FOODRESCUE_DB_BACKEND", "supabase")).lower(),
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
    """Get list of all pickup tasks with dynamically calculated logistics."""
    tasks = database.get_all_pickup_tasks()
    import routing
    enriched = []
    for t in tasks:
        td = dict(t)
        if not td.get("total_distance_km") or float(td.get("total_distance_km", 0)) <= 0:
            p_loc = td.get("pickup_location") or ""
            d_loc = td.get("delivery_location") or ""
            p_c = routing.geocode_location(p_loc)
            d_c = routing.geocode_location(d_loc)
            if p_c and d_c:
                d_km = round(max(0.5, routing.calculate_haversine_distance(p_c[0], p_c[1], d_c[0], d_c[1]) * 1.25), 1)
            else:
                d_km = round(max(1.0, (hash(f"{p_loc}_{d_loc}") % 40) / 10.0 + 1.8), 1)
            cost_info = routing.calculate_transport_estimate(d_km, "motorbike")
            c_lkr = float(cost_info.get("estimated_support_amount") or (d_km * 50.0))
            td["total_distance_km"] = d_km
            td["estimated_transport_cost"] = int(c_lkr)
            try:
                database.update_pickup_task_logistics(task_id=td["id"], total_distance_km=d_km, estimated_transport_cost=int(c_lkr))
            except Exception:
                pass
        enriched.append(td)
    return JSONResponse(content={"status": "success", "count": len(enriched), "pickup_tasks": enriched})


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


from fastapi.responses import Response
import qr_service
import whatsapp_handler


def _render_verification_html(
    title: str,
    qr_type: str,
    token: str,
    food_info: str,
    quantity_info: str,
    party_a_label: str,
    party_a_name: str,
    party_b_label: str,
    party_b_name: str,
    location_label: str,
    location_val: str,
    task_id: str,
    is_valid: bool = True,
    error_title: str = "",
    error_message: str = "",
    already_verified: bool = False,
    verified_time: str = ""
) -> str:
    """Generate responsive, mobile-first HTML interface for physical handover verification."""
    is_pickup = qr_type.upper() == "PICKUP"
    btn_text = "Confirm Food Pickup" if is_pickup else "Confirm Food Delivery"
    btn_icon = "🍱" if is_pickup else "🎉"
    theme_color = "#10b981" if is_pickup else "#3b82f6"

    if not is_valid:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>FoodRescue AI — Verification Error</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
    body {{ background: #0f172a; color: #f8fafc; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 1.5rem; }}
    .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 1.25rem; max-width: 440px; width: 100%; padding: 2rem; text-align: center; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5); }}
    .icon {{ font-size: 3.5rem; margin-bottom: 1rem; }}
    h1 {{ font-size: 1.35rem; color: #ef4444; margin-bottom: 0.75rem; font-weight: 700; }}
    p {{ color: #94a3b8; font-size: 0.95rem; line-height: 1.5; margin-bottom: 1.5rem; }}
    .btn {{ display: inline-block; width: 100%; background: #334155; color: #f8fafc; text-decoration: none; padding: 0.85rem; border-radius: 0.75rem; font-weight: 600; font-size: 0.95rem; transition: background 0.2s; }}
    .btn:hover {{ background: #475569; }}
    .tag {{ display: inline-block; background: #292524; color: #f97316; font-size: 0.75rem; padding: 0.25rem 0.6rem; border-radius: 0.5rem; margin-bottom: 1rem; font-family: monospace; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">⚠️</div>
    <span class="tag">TOKEN: {token[:18]}...</span>
    <h1>{error_title or "Verification Failed"}</h1>
    <p>{error_message or "This QR verification code is invalid, expired, or belongs to another task."}</p>
    <a href="/" class="btn">Return to FoodRescue Dashboard</a>
  </div>
</body>
</html>"""

    if already_verified:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>FoodRescue AI — Handover Verified</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
    body {{ background: #0f172a; color: #f8fafc; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 1.5rem; }}
    .card {{ background: #1e293b; border: 1px solid #10b98140; border-radius: 1.25rem; max-width: 440px; width: 100%; padding: 2.25rem 2rem; text-align: center; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5); }}
    .icon {{ font-size: 3.5rem; margin-bottom: 1rem; }}
    h1 {{ font-size: 1.4rem; color: #10b981; margin-bottom: 0.75rem; font-weight: 700; }}
    p {{ color: #94a3b8; font-size: 0.95rem; line-height: 1.5; margin-bottom: 1.5rem; }}
    .time-badge {{ display: inline-block; background: #064e3b; color: #34d399; font-size: 0.8rem; padding: 0.35rem 0.75rem; border-radius: 9999px; margin-bottom: 1.5rem; font-weight: 600; }}
    .btn {{ display: inline-block; width: 100%; background: #10b981; color: #0f172a; text-decoration: none; padding: 0.9rem; border-radius: 0.75rem; font-weight: 700; font-size: 0.95rem; transition: transform 0.1s, background 0.2s; }}
    .btn:hover {{ background: #34d399; transform: translateY(-1px); }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">✅</div>
    <span class="time-badge">Verified: {verified_time or 'Just now'}</span>
    <h1>{'Pickup Confirmed!' if is_pickup else 'Delivery Completed!'}</h1>
    <p>{'The food has been marked as COLLECTED and is en route to the recipient organization.' if is_pickup else 'The food donation has been successfully handed over to the organization and marked as DELIVERED.'}</p>
    <a href="/" class="btn">View Live Operations</a>
  </div>
</body>
</html>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>FoodRescue AI — {title}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
    body {{ background: #0f172a; color: #f8fafc; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 1.25rem; }}
    .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 1.25rem; max-width: 440px; width: 100%; overflow: hidden; box-shadow: 0 25px 35px -5px rgba(0,0,0,0.6); }}
    .header {{ background: linear-gradient(135deg, #0f172a, #1e293b); padding: 1.5rem; text-align: center; border-bottom: 1px solid #334155; position: relative; }}
    .logo {{ font-size: 0.8rem; font-weight: 700; letter-spacing: 0.1em; color: #10b981; text-transform: uppercase; margin-bottom: 0.35rem; }}
    .title {{ font-size: 1.3rem; font-weight: 800; color: #f8fafc; }}
    .badge {{ display: inline-block; background: {theme_color}25; color: {theme_color}; font-size: 0.75rem; font-weight: 700; padding: 0.25rem 0.65rem; border-radius: 9999px; border: 1px solid {theme_color}50; margin-top: 0.5rem; text-transform: uppercase; }}
    .body {{ padding: 1.5rem; }}
    .info-group {{ background: #0f172a80; border: 1px solid #33415560; border-radius: 0.85rem; padding: 1rem; margin-bottom: 1.25rem; }}
    .row {{ display: flex; justify-content: space-between; align-items: flex-start; padding: 0.5rem 0; border-bottom: 1px solid #33415540; }}
    .row:last-child {{ border-bottom: none; }}
    .label {{ color: #94a3b8; font-size: 0.82rem; font-weight: 500; }}
    .val {{ color: #f8fafc; font-size: 0.88rem; font-weight: 600; text-align: right; max-width: 60%; }}
    .val-highlight {{ color: #34d399; font-weight: 700; }}
    .btn-confirm {{ display: flex; align-items: center; justify-content: center; gap: 0.5rem; width: 100%; background: linear-gradient(135deg, #10b981, #059669); color: #ffffff; border: none; padding: 1rem; border-radius: 0.85rem; font-size: 1.05rem; font-weight: 800; cursor: pointer; transition: transform 0.1s, box-shadow 0.2s; box-shadow: 0 10px 15px -3px rgba(16,185,129,0.4); }}
    .btn-confirm:hover {{ transform: translateY(-1px); box-shadow: 0 15px 20px -3px rgba(16,185,129,0.5); }}
    .btn-confirm:active {{ transform: translateY(1px); }}
    .btn-confirm:disabled {{ opacity: 0.6; cursor: not-allowed; }}
    .notice {{ text-align: center; color: #64748b; font-size: 0.75rem; margin-top: 1rem; line-height: 1.4; }}
    .task-id {{ font-family: monospace; font-size: 0.75rem; color: #64748b; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <div class="logo">🌿 FoodRescue AI</div>
      <h1 class="title">{title}</h1>
      <span class="badge">🔐 Physical Handover Proof</span>
    </div>
    <div class="body">
      <div class="info-group">
        <div class="row">
          <span class="label">🍱 Food Type</span>
          <span class="val val-highlight">{food_info}</span>
        </div>
        <div class="row">
          <span class="label">📦 Quantity</span>
          <span class="val">{quantity_info}</span>
        </div>
        <div class="row">
          <span class="label">{party_a_label}</span>
          <span class="val">{party_a_name}</span>
        </div>
        <div class="row">
          <span class="label">{party_b_label}</span>
          <span class="val">{party_b_name}</span>
        </div>
        <div class="row">
          <span class="label">{location_label}</span>
          <span class="val">{location_val}</span>
        </div>
        <div class="row">
          <span class="label">🆔 Task ID</span>
          <span class="val task-id">{task_id}</span>
        </div>
      </div>

      <button id="confirmBtn" class="btn-confirm" onclick="confirmHandover()">
        <span>{btn_icon}</span>
        <span>{btn_text}</span>
      </button>

      <p class="notice">
        By confirming, you certify that the physical handover of this food donation has taken place.
      </p>
    </div>
  </div>

  <script>
    async function confirmHandover() {{
      const btn = document.getElementById('confirmBtn');
      btn.disabled = true;
      btn.innerHTML = '<span>⏳</span><span>Verifying Handover...</span>';

      let coords = null;
      if (navigator.geolocation) {{
        try {{
          const pos = await new Promise((resolve, reject) => {{
            navigator.geolocation.getCurrentPosition(resolve, reject, {{ timeout: 3000 }});
          }});
          coords = {{ latitude: pos.coords.latitude, longitude: pos.coords.longitude }};
        }} catch(e) {{}}
      }}

      try {{
        const resp = await fetch('/verify/{qr_type.lower()}/{token}', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ gps: coords }})
        }});
        const data = await resp.json();
        if (data.status === 'success' || data.success) {{
          window.location.reload();
        }} else {{
          alert('Verification Failed: ' + (data.message || data.error || 'Unknown error'));
          btn.disabled = false;
          btn.innerHTML = '<span>{btn_icon}</span><span>{btn_text}</span>';
        }}
      }} catch(err) {{
        alert('Network error connecting to verification service.');
        btn.disabled = false;
        btn.innerHTML = '<span>{btn_icon}</span><span>{btn_text}</span>';
      }}
    }}
  </script>
</body>
</html>"""


def _render_scanner_html(qr_type: str = "pickup", task_id: Optional[str] = None, prefill_token: Optional[str] = None) -> str:
    """Generate modern, mobile-first Camera QR Scanner web interface for physical volunteer handover."""
    is_pickup = str(qr_type).strip().lower() == "pickup"
    phase_title = "Pickup Verification" if is_pickup else "Delivery Verification"
    badge_label = "🍱 Pickup Scanner (Scan Donor's Screen)" if is_pickup else "🎉 Delivery Scanner (Scan Organization's Screen)"
    theme_color = "#10b981" if is_pickup else "#3b82f6"
    target_role = "Donor" if is_pickup else "Recipient Organization"
    task_str = f"Task: {task_id}" if task_id else "FoodRescue Handover"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>FoodRescue AI — {phase_title}</title>
  <script src="https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
    body {{ background: #0b1120; color: #f8fafc; min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 1rem; }}
    .scanner-card {{ background: #1e293b; border: 1px solid #334155; border-radius: 1.25rem; max-width: 480px; width: 100%; overflow: hidden; box-shadow: 0 25px 40px -10px rgba(0,0,0,0.7); }}
    .header {{ background: linear-gradient(135deg, #0f172a, #1e293b); padding: 1.25rem; text-align: center; border-bottom: 1px solid #334155; }}
    .logo {{ font-size: 0.85rem; font-weight: 800; letter-spacing: 0.08em; color: #10b981; text-transform: uppercase; margin-bottom: 0.25rem; }}
    .title {{ font-size: 1.25rem; font-weight: 800; color: #ffffff; }}
    .badge {{ display: inline-block; background: {theme_color}20; color: {theme_color}; font-size: 0.75rem; font-weight: 700; padding: 0.3rem 0.75rem; border-radius: 9999px; border: 1px solid {theme_color}50; margin-top: 0.4rem; }}
    
    .body {{ padding: 1.25rem; }}
    .camera-wrapper {{ position: relative; width: 100%; border-radius: 1rem; overflow: hidden; background: #000; border: 2px solid #334155; min-height: 280px; display: flex; align-items: center; justify-content: center; }}
    #reader {{ width: 100% !important; border: none !important; }}
    #reader video {{ width: 100% !important; height: auto !important; object-fit: cover !important; border-radius: 0.85rem; }}
    
    .scan-guide {{ position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 200px; height: 200px; border: 2px dashed {theme_color}; border-radius: 1rem; pointer-events: none; z-index: 10; box-shadow: 0 0 0 4000px rgba(0, 0, 0, 0.4); animation: pulseGuide 2s infinite ease-in-out; }}
    .laser-line {{ position: absolute; width: 100%; height: 2px; background: {theme_color}; box-shadow: 0 0 8px {theme_color}; animation: scanLaser 2s infinite linear; }}
    @keyframes scanLaser {{
      0% {{ top: 5%; }}
      50% {{ top: 95%; }}
      100% {{ top: 5%; }}
    }}
    @keyframes pulseGuide {{
      0%, 100% {{ border-color: {theme_color}; opacity: 0.9; }}
      50% {{ border-color: #ffffff; opacity: 0.6; }}
    }}

    .inst-box {{ background: #0f172a; border: 1px solid #334155; border-radius: 0.85rem; padding: 0.9rem; margin-top: 1rem; font-size: 0.85rem; color: #94a3b8; line-height: 1.4; text-align: center; }}
    .inst-box strong {{ color: #f8fafc; }}

    .actions {{ display: flex; gap: 0.5rem; margin-top: 1rem; }}
    .btn-secondary {{ flex: 1; background: #334155; color: #f8fafc; border: 1px solid #475569; padding: 0.75rem; border-radius: 0.75rem; font-weight: 600; font-size: 0.85rem; cursor: pointer; }}
    .btn-secondary:hover {{ background: #475569; }}

    .manual-entry {{ margin-top: 1rem; padding-top: 1rem; border-top: 1px dashed #334155; }}
    .manual-toggle {{ background: none; border: none; color: #38bdf8; font-size: 0.8rem; cursor: pointer; text-decoration: underline; display: block; width: 100%; text-align: center; margin-bottom: 0.5rem; }}
    .manual-form {{ display: none; margin-top: 0.5rem; }}
    .input-token {{ width: 100%; background: #0f172a; border: 1px solid #334155; color: #f8fafc; padding: 0.75rem; border-radius: 0.75rem; font-family: monospace; font-size: 0.9rem; margin-bottom: 0.5rem; text-align: center; text-transform: uppercase; }}
    .input-token:focus {{ outline: none; border-color: {theme_color}; }}
    .btn-submit {{ width: 100%; background: {theme_color}; color: #0f172a; border: none; padding: 0.75rem; border-radius: 0.75rem; font-weight: 700; font-size: 0.9rem; cursor: pointer; }}

    /* Result Modals */
    .result-card {{ display: none; padding: 1.5rem; text-align: center; }}
    .res-icon {{ font-size: 3.5rem; margin-bottom: 0.75rem; }}
    .res-title {{ font-size: 1.35rem; font-weight: 800; margin-bottom: 0.5rem; }}
    .res-msg {{ color: #94a3b8; font-size: 0.9rem; line-height: 1.5; margin-bottom: 1.25rem; }}
    .res-token {{ font-family: monospace; background: #0f172a; padding: 0.35rem 0.75rem; border-radius: 0.5rem; font-size: 0.8rem; color: #38bdf8; display: inline-block; margin-bottom: 1rem; }}
    .btn-done {{ display: block; width: 100%; background: linear-gradient(135deg, #10b981, #059669); color: #fff; padding: 0.9rem; border-radius: 0.85rem; font-weight: 800; text-decoration: none; font-size: 1rem; border: none; cursor: pointer; }}
  </style>
</head>
<body>

  <div class="scanner-card">
    <div class="header">
      <div class="logo">🌿 FoodRescue AI</div>
      <h1 class="title">{phase_title}</h1>
      <span class="badge">{badge_label}</span>
    </div>

    <!-- Scanner Active View -->
    <div id="scannerSection" class="body">
      <div class="camera-wrapper">
        <div id="reader"></div>
        <div class="scan-guide">
          <div class="laser-line"></div>
        </div>
      </div>

      <div class="inst-box">
        📸 <strong>Point your camera</strong> at the QR code displayed on the {target_role}'s phone screen.
      </div>

      <div class="manual-entry">
        <button type="button" class="manual-toggle" onclick="toggleManual()">Or Enter Verification Code Manually ▾</button>
        <div id="manualForm" class="manual-form">
          <input type="text" id="manualToken" class="input-token" placeholder="FR-PK-xxxxxxxxxxxx" value="{prefill_token or ''}">
          <button type="button" class="btn-submit" onclick="submitManualCode()">Verify Code Now</button>
        </div>
      </div>
    </div>

    <!-- Success Result View -->
    <div id="successSection" class="result-card">
      <div class="res-icon">✅</div>
      <h2 id="successTitle" class="res-title" style="color: #10b981;">Handover Verified!</h2>
      <span id="successToken" class="res-token"></span>
      <p id="successMsg" class="res-msg">
        Physical handover successfully verified in the FoodRescue AI system.
      </p>
      <button class="btn-done" onclick="closeOrReturn()">✓ Return to WhatsApp</button>
    </div>

    <!-- Error Result View -->
    <div id="errorSection" class="result-card">
      <div class="res-icon">⚠️</div>
      <h2 id="errorTitle" class="res-title" style="color: #ef4444;">Verification Failed</h2>
      <p id="errorMsg" class="res-msg">The QR code could not be verified.</p>
      <button class="btn-secondary" style="width:100%; padding:0.9rem;" onclick="restartScanner()">📷 Try Scanning Again</button>
    </div>
  </div>

  <script>
    const QR_TYPE = "{qr_type.lower()}";
    let html5QrCode = null;
    let isVerifying = false;

    function toggleManual() {{
      const form = document.getElementById('manualForm');
      form.style.display = form.style.display === 'block' ? 'none' : 'block';
    }}

    function extractTokenFromText(text) {{
      if (!text) return null;
      const clean = text.trim();
      const match = clean.match(/FR-(PK|DL)-[a-zA-Z0-9_-]+/i);
      if (match) return match[0];
      if (clean.includes('/verify/')) {{
        const parts = clean.split('/verify/')[1].split('/');
        if (parts.length >= 2) return parts[1].split('?')[0].split('#')[0];
      }}
      return clean;
    }}

    async function handleScanSuccess(decodedText) {{
      if (isVerifying) return;
      isVerifying = true;

      const token = extractTokenFromText(decodedText);
      if (!token) {{
        isVerifying = false;
        return;
      }}

      if (navigator.vibrate) navigator.vibrate([100, 50, 100]);

      if (html5QrCode) {{
        try {{ await html5QrCode.stop(); }} catch(e) {{}}
      }}

      await verifyToken(token);
    }}

    async function submitManualCode() {{
      const val = document.getElementById('manualToken').value.trim();
      const token = extractTokenFromText(val);
      if (!token) {{
        alert('Please enter a valid verification code (e.g. FR-PK-...)');
        return;
      }}
      if (html5QrCode) {{
        try {{ await html5QrCode.stop(); }} catch(e) {{}}
      }}
      await verifyToken(token);
    }}

    async function verifyToken(token) {{
      document.getElementById('scannerSection').style.display = 'none';
      document.getElementById('errorSection').style.display = 'none';

      let gps = null;
      if (navigator.geolocation) {{
        try {{
          const pos = await new Promise((res, rej) => navigator.geolocation.getCurrentPosition(res, rej, {{ timeout: 3000 }}));
          gps = {{ latitude: pos.coords.latitude, longitude: pos.coords.longitude }};
        }} catch(e) {{}}
      }}

      const targetType = token.toUpperCase().includes('DL') ? 'delivery' : (token.toUpperCase().includes('PK') ? 'pickup' : QR_TYPE);

      try {{
        const resp = await fetch(`/verify/${{targetType}}/${{token}}`, {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ gps: gps }})
        }});
        const data = await resp.json();

        if (resp.ok && (data.status === 'success' || data.success)) {{
          document.getElementById('successToken').innerText = token;
          if (targetType === 'pickup') {{
            document.getElementById('successTitle').innerText = 'Pickup Verified!';
            document.getElementById('successMsg').innerText = 'Food marked as COLLECTED and is now in transit. Real-time WhatsApp notifications dispatched to Donor, Volunteer, and Organization!';
          }} else {{
            document.getElementById('successTitle').innerText = 'Delivery Completed!';
            document.getElementById('successMsg').innerText = 'Food marked as DELIVERED & COMPLETED. Transport reimbursement support has been recorded. Thank you!';
          }}
          document.getElementById('successSection').style.display = 'block';
        }} else {{
          document.getElementById('errorTitle').innerText = 'Verification Failed';
          document.getElementById('errorMsg').innerText = data.message || data.error || 'Invalid or expired QR verification code.';
          document.getElementById('errorSection').style.display = 'block';
        }}
      }} catch(err) {{
        document.getElementById('errorTitle').innerText = 'Network Error';
        document.getElementById('errorMsg').innerText = 'Unable to connect to verification server. Please check your connection.';
        document.getElementById('errorSection').style.display = 'block';
      }} finally {{
        isVerifying = false;
      }}
    }}

    function restartScanner() {{
      document.getElementById('errorSection').style.display = 'none';
      document.getElementById('successSection').style.display = 'none';
      document.getElementById('scannerSection').style.display = 'block';
      initScanner();
    }}

    function closeOrReturn() {{
      window.location.href = 'https://wa.me/';
    }}

    function initScanner() {{
      if (typeof Html5Qrcode === 'undefined') {{
        console.warn('Html5Qrcode library not yet loaded. Retrying in 500ms...');
        setTimeout(initScanner, 500);
        return;
      }}

      html5QrCode = new Html5Qrcode("reader");
      const config = {{ fps: 15, qrbox: {{ width: 220, height: 220 }}, aspectRatio: 1.0 }};
      
      html5QrCode.start(
        {{ facingMode: "environment" }},
        config,
        handleScanSuccess,
        (errorMessage) => {{}}
      ).catch((err) => {{
        console.warn('Camera stream failed, falling back to manual entry:', err);
        toggleManual();
      }});
    }}

    window.addEventListener('DOMContentLoaded', () => {{
      initScanner();
    }});
  </script>
</body>
</html>"""


@router.get("/scanner", response_class=HTMLResponse)
@router.get("/scan", response_class=HTMLResponse)
@router.get("/scanner/{qr_type}", response_class=HTMLResponse)
@router.get("/scan/{qr_type}", response_class=HTMLResponse)
async def view_camera_scanner_page(
    qr_type: Optional[str] = "pickup",
    task_id: Optional[str] = Query(None),
    token: Optional[str] = Query(None)
):
    """Serve the zero-cheat mobile camera QR scanner interface for volunteer couriers."""
    clean_type = "delivery" if str(qr_type).lower() in ["delivery", "dl"] else "pickup"
    html = _render_scanner_html(qr_type=clean_type, task_id=task_id, prefill_token=token)
    return HTMLResponse(content=html, status_code=200)


@router.get("/api/qr/{token}.png")
@router.get("/api/qr/{token}")
async def get_qr_png_image(token: str):
    """Generate and stream high-resolution PNG image of the handover QR code using QRCoder V4 API."""
    clean_tok = token.strip()
    qr_type = "pickup" if "pk" in clean_tok.lower() else "delivery"
    verif_url = qr_service.build_verification_url(qr_type, clean_tok)
    try:
        png_bytes = qr_service.generate_qr_image(verif_url, box_size=10, border=3)
        return Response(content=png_bytes, media_type="image/png")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate QR PNG: {exc}")


@router.get("/verify/pickup/{token}", response_class=HTMLResponse)
async def view_pickup_verification_page(token: str):
    """Serve the mobile-first Pickup Handover verification interface."""
    clean_tok = token.strip()
    qr_rec = database.get_qr_code_by_token(clean_tok)
    if not qr_rec or qr_rec.get("qr_type", "").upper() != "PICKUP":
        html = _render_verification_html(
            title="Pickup Verification", qr_type="PICKUP", token=clean_tok,
            food_info="", quantity_info="", party_a_label="", party_a_name="",
            party_b_label="", party_b_name="", location_label="", location_val="",
            task_id="", is_valid=False, error_title="Invalid Pickup QR Code",
            error_message="This QR code was not recognized or is not a valid FoodRescue pickup token."
        )
        return HTMLResponse(content=html, status_code=400)

    task_id = qr_rec.get("task_id", "")
    task = database.get_pickup_task_record(task_id) or {}
    don = database.get_donation_record(qr_rec.get("donation_id", "")) if qr_rec.get("donation_id") else {}
    donor = database.get_donor_record(don.get("donor_id", "")) if don else {}
    vol = database.get_volunteer_record(task.get("volunteer_id", "")) or database.get_volunteer_by_phone(task.get("volunteer_id", "")) if task.get("volunteer_id") else {}

    food_name = don.get("food_type", "Prepared Meals") if don else "Prepared Meals"
    raw_qty = don.get('quantity', 30) if don else 30
    disp_qty = int(raw_qty) if isinstance(raw_qty, (int, float)) and raw_qty == int(raw_qty) else raw_qty
    qty = f"{disp_qty} {don.get('unit', 'meal packets') if don else 'meal packets'}"
    donor_name = (donor.get("name") if donor else None) or (don.get("donor_name") if don else "Local Food Donor")
    vol_name = (vol.get("name") if vol else None) or "Assigned Courier"
    pickup_loc = don.get("pickup_location") or don.get("location") or task.get("pickup_location") or "Pickup Address"

    # Check status
    if qr_rec.get("status") == "VERIFIED" or task.get("status") in ["COLLECTED", "IN_TRANSIT", "DELIVERED", "COMPLETED"]:
        html = _render_verification_html(
            title="Pickup Verified", qr_type="PICKUP", token=clean_tok,
            food_info=food_name, quantity_info=qty, party_a_label="Donor", party_a_name=donor_name,
            party_b_label="Volunteer", party_b_name=vol_name, location_label="Pickup Location",
            location_val=pickup_loc, task_id=task_id, is_valid=True, already_verified=True,
            verified_time=database.format_sri_lanka_time(qr_rec.get("verified_at"))
        )
        return HTMLResponse(content=html, status_code=200)

    html = _render_verification_html(
        title="Pickup Verification", qr_type="PICKUP", token=clean_tok,
        food_info=food_name, quantity_info=qty, party_a_label="Donor", party_a_name=donor_name,
        party_b_label="Assigned Volunteer", party_b_name=vol_name, location_label="Pickup Location",
        location_val=pickup_loc, task_id=task_id, is_valid=True
    )
    return HTMLResponse(content=html, status_code=200)


@router.post("/verify/pickup/{token}")
async def confirm_pickup_verification(token: str, request: Request):
    """Atomically confirm physical food pickup handover and dispatch real-time cross-notifications."""
    clean_tok = token.strip()
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    gps_coords = body.get("gps") if isinstance(body, dict) else None
    volunteer_id = body.get("volunteer_id") if isinstance(body, dict) else None

    result = database.verify_qr_code_record(clean_tok, volunteer_id=volunteer_id, gps_coords=gps_coords)
    if not result.get("success"):
        return JSONResponse(status_code=400, content={"status": "error", "error": result.get("error"), "message": result.get("message")})

    task_id = result.get("task_id", "")
    # Trigger real-time 3-way WhatsApp notifications & generate delivery QR
    try:
        await whatsapp_handler.dispatch_qr_pickup_success_notifications(task_id, volunteer_id=volunteer_id)
    except Exception as exc:
        pass

    return JSONResponse(content={
        "status": "success",
        "message": "Food pickup verified and recorded as COLLECTED.",
        "task_id": task_id,
        "verified_at": database.format_sri_lanka_time(result.get("verified_at"))
    })


@router.get("/verify/delivery/{token}", response_class=HTMLResponse)
async def view_delivery_verification_page(token: str):
    """Serve the mobile-first Delivery Handover verification interface."""
    clean_tok = token.strip()
    qr_rec = database.get_qr_code_by_token(clean_tok)
    if not qr_rec or qr_rec.get("qr_type", "").upper() != "DELIVERY":
        html = _render_verification_html(
            title="Delivery Verification", qr_type="DELIVERY", token=clean_tok,
            food_info="", quantity_info="", party_a_label="", party_a_name="",
            party_b_label="", party_b_name="", location_label="", location_val="",
            task_id="", is_valid=False, error_title="Invalid Delivery QR Code",
            error_message="This QR code was not recognized or is not a valid FoodRescue delivery token."
        )
        return HTMLResponse(content=html, status_code=400)

    task_id = qr_rec.get("task_id", "")
    task = database.get_pickup_task_record(task_id) or {}
    don = database.get_donation_record(qr_rec.get("donation_id", "")) if qr_rec.get("donation_id") else {}
    org = database.get_organization_record(task.get("organization_id", "")) if task.get("organization_id") else {}
    vol = database.get_volunteer_record(task.get("volunteer_id", "")) or database.get_volunteer_by_phone(task.get("volunteer_id", "")) if task.get("volunteer_id") else {}

    food_name = don.get("food_type", "Prepared Meals") if don else "Prepared Meals"
    raw_qty = don.get('quantity', 30) if don else 30
    disp_qty = int(raw_qty) if isinstance(raw_qty, (int, float)) and raw_qty == int(raw_qty) else raw_qty
    qty = f"{disp_qty} {don.get('unit', 'meal packets') if don else 'meal packets'}"
    org_name = (org.get("name") if org else None) or "Recipient Organization"
    vol_name = (vol.get("name") if vol else None) or "Assigned Courier"
    deliv_loc = org.get("location") or org.get("service_area") or task.get("delivery_location") or "Delivery Address"

    # Check status
    if qr_rec.get("status") == "VERIFIED" or task.get("status") in ["DELIVERED", "COMPLETED"]:
        html = _render_verification_html(
            title="Delivery Completed", qr_type="DELIVERY", token=clean_tok,
            food_info=food_name, quantity_info=qty, party_a_label="Organization", party_a_name=org_name,
            party_b_label="Volunteer", party_b_name=vol_name, location_label="Destination",
            location_val=deliv_loc, task_id=task_id, is_valid=True, already_verified=True,
            verified_time=database.format_sri_lanka_time(qr_rec.get("verified_at"))
        )
        return HTMLResponse(content=html, status_code=200)


    html = _render_verification_html(
        title="Delivery Verification", qr_type="DELIVERY", token=clean_tok,
        food_info=food_name, quantity_info=qty, party_a_label="Recipient Organization", party_a_name=org_name,
        party_b_label="Delivering Volunteer", party_b_name=vol_name, location_label="Delivery Location",
        location_val=deliv_loc, task_id=task_id, is_valid=True
    )
    return HTMLResponse(content=html, status_code=200)


@router.post("/verify/delivery/{token}")
async def confirm_delivery_verification(token: str, request: Request):
    """Atomically confirm physical food delivery handover and dispatch 3-way cross-notifications."""
    clean_tok = token.strip()
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    gps_coords = body.get("gps") if isinstance(body, dict) else None
    volunteer_id = body.get("volunteer_id") if isinstance(body, dict) else None

    result = database.verify_qr_code_record(clean_tok, volunteer_id=volunteer_id, gps_coords=gps_coords)
    if not result.get("success"):
        return JSONResponse(status_code=400, content={"status": "error", "error": result.get("error"), "message": result.get("message")})

    task_id = result.get("task_id", "")
    # Trigger real-time 3-way WhatsApp notifications & transport reimbursement confirmation
    try:
        await whatsapp_handler.dispatch_qr_delivery_success_notifications(task_id, volunteer_id=volunteer_id)
    except Exception as exc:
        pass

    return JSONResponse(content={
        "status": "success",
        "message": "Food delivery verified and recorded as DELIVERED & COMPLETED.",
        "task_id": task_id,
        "verified_at": database.format_sri_lanka_time(result.get("verified_at"))
    })


@router.get("/api/tasks/{task_id}/qr")
async def get_task_qr_status(task_id: str):
    """Retrieve all QR handover verification records and live statuses for a pickup task."""
    clean_id = task_id.strip()
    qrs = database.get_qr_codes_for_task(clean_id)
    enriched = []
    for q in qrs:
        token = q.get("token", "")
        qr_type = q.get("qr_type", "PICKUP")
        enriched.append({
            **q,
            "verification_url": qr_service.build_verification_url(qr_type, token),
            "qr_image_url": f"{qr_service.get_base_url()}/api/qr/{token}.png"
        })
    return JSONResponse(content={
        "status": "success",
        "task_id": clean_id,
        "qr_codes": enriched
    })


def get_router() -> APIRouter:
    """Return the configured APIRouter for Agent Kernel RESTAPI registration."""
    return router


