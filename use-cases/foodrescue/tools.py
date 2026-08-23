import json
import uuid
import asyncio
from typing import Optional, Dict, Any, List, Tuple
from agentkernel.core import ToolContext, Session
import database
import routing

VALID_DONATION_STATUSES = {
    "AVAILABLE",
    "MATCHED",
    "PICKUP_PENDING",
    "PICKUP_ASSIGNED",
    "PICKED_UP",
    "COLLECTED",
    "DISTRIBUTED",
    "DELIVERED",
    "CANCELLED",
    "EXPIRED",
}
VALID_PICKUP_STATUSES = {"PENDING", "OFFERED", "ASSIGNED", "EN_ROUTE", "COLLECTED", "IN_TRANSIT", "DELIVERED", "COMPLETED", "FAILED", "CANCELLED"}

_EXPLICIT_SESSION_ID: Optional[str] = None
_SESSION_STORE: Dict[str, Any] = {}


def set_explicit_session_id(session_id: Optional[str]) -> None:
    """Set an explicit active session ID for non-ADK tool invocations and fallbacks."""
    global _EXPLICIT_SESSION_ID
    _EXPLICIT_SESSION_ID = session_id


def get_session_instance(session_id: str) -> Any:
    """Get or create the singleton Session instance for a given session ID."""
    global _SESSION_STORE
    if session_id not in _SESSION_STORE:
        _SESSION_STORE[session_id] = Session(session_id)
    return _SESSION_STORE[session_id]


def clear_session_store() -> None:
    """Clear in-memory session cache store."""
    global _SESSION_STORE
    _SESSION_STORE.clear()


def _get_session_cache():
    """Retrieve the non-volatile KeyValueCache from the active Agent Kernel session."""
    try:
        context = ToolContext.get()
        if context and context.session:
            return context.session.get_non_volatile_cache()
    except Exception:
        pass
    try:
        session = Session.current()
        if session:
            return session.get_non_volatile_cache()
    except Exception:
        pass
    if _EXPLICIT_SESSION_ID:
        try:
            return get_session_instance(_EXPLICIT_SESSION_ID).get_non_volatile_cache()
        except Exception:
            pass
    return None


def _get_context_val(key: str, default: Any = None) -> Any:
    """Retrieve a value from the active session cache."""
    cache = _get_session_cache()
    if cache is not None and cache.has(key):
        return cache.get(key)
    return default


def _set_context_val(key: str, val: Any) -> None:
    """Store a value into the active session cache."""
    cache = _get_session_cache()
    if cache is not None:
        cache.set(key, val)


def create_donation(
    donor_id: str,
    food_type: str,
    quantity: float,
    unit: str = "portions",
    dietary_information: str = "None",
    location: str = "Colombo",
    available_from: str = "Now",
    pickup_deadline: str = "Today",
) -> str:
    """Create a new food donation record after validating all required fields.
    Returns structured JSON with the created donation details and assigned ID.
    """
    # Contextual donor linking
    resolved_donor = str(donor_id).strip() if donor_id and str(donor_id).strip() != "d1" else (_get_context_val("current_donor_id") or "d1")
    # Validation
    if not donor_id or not str(donor_id).strip():
        return json.dumps({"status": "error", "message": "donor_id is required."})
    if not food_type or not str(food_type).strip():
        return json.dumps({"status": "error", "message": "food_type is required."})
    try:
        qty = float(quantity)
        if qty <= 0:
            return json.dumps({"status": "error", "message": "quantity must be greater than 0."})
    except (ValueError, TypeError):
        return json.dumps({"status": "error", "message": "quantity must be a valid positive number."})
    if not unit or not str(unit).strip():
        return json.dumps({"status": "error", "message": "unit is required."})
    if not location or not str(location).strip():
        return json.dumps({"status": "error", "message": "pickup location is required."})
    if not available_from or not str(available_from).strip():
        return json.dumps({"status": "error", "message": "available_from time is required."})
    if not pickup_deadline or not str(pickup_deadline).strip():
        return json.dumps({"status": "error", "message": "pickup_deadline is required."})

    donation_id = f"don-{uuid.uuid4().hex[:8]}"
    clean_donor = str(resolved_donor).strip()
    clean_food = str(food_type).strip()
    clean_unit = str(unit).strip()
    clean_diet = str(dietary_information).strip() if dietary_information else "None"
    clean_loc = str(location).strip()
    clean_from = str(available_from).strip()
    clean_deadline = str(pickup_deadline).strip()

    record = database.create_donation_record(
        donation_id=donation_id,
        donor_id=clean_donor,
        food_type=clean_food,
        quantity=qty,
        unit=clean_unit,
        dietary_info=clean_diet,
        location=clean_loc,
        available_from=clean_from,
        deadline=clean_deadline,
    )

    database.create_notification_record(
        f"notif-{uuid.uuid4().hex[:8]}", "donor", clean_donor, f"Donation {donation_id} created successfully.", "console"
    )

    # Store in session context memory
    _set_context_val("current_donor_id", clean_donor)
    _set_context_val("current_donation_id", donation_id)
    _set_context_val("current_food_type", clean_food)
    _set_context_val("current_quantity", qty)
    _set_context_val("current_unit", clean_unit)
    _set_context_val("current_dietary_information", clean_diet)
    _set_context_val("current_location", clean_loc)
    _set_context_val("current_available_from", clean_from)
    _set_context_val("current_pickup_deadline", clean_deadline)
    _set_context_val("workflow_step", "DONATION_CREATED")

    return json.dumps(
        {
            "status": "success",
            "donation_id": donation_id,
            "donation_status": "AVAILABLE",
            "message": f"Donation {donation_id} created successfully.",
            "donation": record,
        },
        indent=2,
    )


def update_donation_details(
    donation_id: Optional[str] = None,
    food_type: Optional[str] = None,
    quantity: Optional[float] = None,
    unit: Optional[str] = None,
    dietary_information: Optional[str] = None,
    location: Optional[str] = None,
    available_from: Optional[str] = None,
    pickup_deadline: Optional[str] = None,
) -> str:
    """Update editable details of an existing food donation in SQLite and synchronize session context.
    If donation_id is omitted, uses the current donation from session context.
    """
    target_id = str(donation_id).strip() if donation_id and str(donation_id).strip() else _get_context_val("current_donation_id")
    if not target_id:
        return json.dumps({"status": "error", "message": "donation_id was not provided and no active donation found in session context."})

    qty = None
    if quantity is not None:
        try:
            qty = float(quantity)
            if qty <= 0:
                return json.dumps({"status": "error", "message": "quantity must be greater than 0."})
        except (ValueError, TypeError):
            return json.dumps({"status": "error", "message": "quantity must be a valid positive number."})

    updated_record = database.update_donation_details_record(
        donation_id=target_id,
        food_type=food_type,
        quantity=qty,
        unit=unit,
        dietary_info=dietary_information,
        location=location,
        available_from=available_from,
        deadline=pickup_deadline,
    )
    if not updated_record:
        return json.dumps({"status": "error", "message": f"Donation '{target_id}' not found."})

    # Synchronize session context
    if food_type is not None:
        _set_context_val("current_food_type", updated_record["food_type"])
    if qty is not None:
        _set_context_val("current_quantity", updated_record["quantity"])
    if unit is not None:
        _set_context_val("current_unit", updated_record["unit"])
    if dietary_information is not None:
        _set_context_val("current_dietary_information", updated_record["dietary_information"])
    if location is not None:
        _set_context_val("current_location", updated_record["pickup_location"])
    if available_from is not None:
        _set_context_val("current_available_from", updated_record["available_from"])
    if pickup_deadline is not None:
        _set_context_val("current_pickup_deadline", updated_record["pickup_deadline"])

    return json.dumps(
        {
            "status": "success",
            "donation_id": target_id,
            "donation_status": updated_record["status"],
            "message": f"Donation {target_id} details updated successfully.",
            "donation": updated_record,
        },
        indent=2,
    )


def get_donation(donation_id: Optional[str] = None) -> str:
    """Retrieve a donation record by its donation ID. If omitted, uses active donation from session context."""
    target_id = str(donation_id).strip() if donation_id and str(donation_id).strip() else _get_context_val("current_donation_id")
    if not target_id:
        return json.dumps({"status": "error", "message": "donation_id is required."})

    record = database.get_donation_record(target_id)
    if not record:
        return json.dumps({"status": "error", "message": f"Donation with ID '{target_id}' not found."})

    return json.dumps({"status": "success", "donation_id": record["id"], "donation_status": record["status"], "donation": record}, indent=2)


def update_donation_status(donation_id: Optional[str] = None, status: str = "") -> str:
    """Update the donation lifecycle status (e.g. AVAILABLE, MATCHED, PICKUP_ASSIGNED, COLLECTED, DELIVERED, CANCELLED, EXPIRED)."""
    target_id = str(donation_id).strip() if donation_id and str(donation_id).strip() else _get_context_val("current_donation_id")
    if not target_id:
        return json.dumps({"status": "error", "message": "donation_id is required."})
    if not status or not str(status).strip():
        return json.dumps({"status": "error", "message": "status is required."})

    norm_status = str(status).strip().upper()
    if norm_status not in VALID_DONATION_STATUSES:
        return json.dumps({"status": "error", "message": f"Invalid status '{status}'. Allowed statuses: {sorted(list(VALID_DONATION_STATUSES))}"})

    existing = database.get_donation_record(target_id)
    if not existing:
        return json.dumps({"status": "error", "message": f"Donation '{target_id}' not found."})

    success = database.update_donation_status_record(target_id, norm_status)
    if success:
        _set_context_val("workflow_step", f"DONATION_{norm_status}")
        return json.dumps(
            {
                "status": "success",
                "donation_id": target_id,
                "donation_status": norm_status,
                "message": f"Successfully updated donation {target_id} status to {norm_status}.",
            },
            indent=2,
        )
    return json.dumps({"status": "error", "message": f"Failed to update donation '{target_id}'."})


def find_matching_organizations(food_type: Optional[str] = None, location: Optional[str] = None) -> str:
    """Search for eligible recipient organizations based on food type and location.
    Falls back to session context if parameters are omitted."""
    target_food = str(food_type).strip() if food_type and str(food_type).strip() else _get_context_val("current_food_type", "")
    target_loc = str(location).strip() if location and str(location).strip() else _get_context_val("current_location", "")

    if not target_food or not target_loc:
        return json.dumps({"status": "error", "message": "Both food_type and location are required."})

    orgs = database.find_organizations_by_criteria(target_food, target_loc)
    return json.dumps(
        {
            "status": "success",
            "count": len(orgs),
            "organizations": orgs,
            "message": f"Found {len(orgs)} matching organization(s) for '{target_food}' in '{target_loc}'.",
        },
        indent=2,
    )


def accept_donation(donation_id: Optional[str] = None, organization_id: Optional[str] = None) -> str:
    """Record that a recipient organization has accepted a donation. Changes donation status to MATCHED."""
    target_don_id = str(donation_id).strip() if donation_id and str(donation_id).strip() else _get_context_val("current_donation_id")
    if not target_don_id:
        return json.dumps({"status": "error", "message": "donation_id is required."})
    if not organization_id or not str(organization_id).strip():
        return json.dumps({"status": "error", "message": "organization_id is required."})

    clean_don_id = str(target_don_id).strip()
    clean_org_id = str(organization_id).strip()

    donation = database.get_donation_record(clean_don_id)
    if not donation:
        return json.dumps({"status": "error", "message": f"Donation '{clean_don_id}' not found."})

    org = database.get_organization_record(clean_org_id)
    if not org:
        return json.dumps({"status": "error", "message": f"Organization '{clean_org_id}' not found."})

    if donation["status"] in ["COLLECTED", "DELIVERED", "CANCELLED", "EXPIRED"]:
        return json.dumps(
            {"status": "error", "message": f"Cannot accept donation '{clean_don_id}' because its status is already {donation['status']}."}
        )

    success = database.accept_donation_record(clean_don_id, clean_org_id)
    if success:
        database.create_notification_record(
            f"notif-{uuid.uuid4().hex[:8]}", "organization", clean_org_id, f"You have successfully accepted donation {clean_don_id}.", "console"
        )
        _set_context_val("current_organization_id", clean_org_id)
        _set_context_val("workflow_step", "ORGANIZATION_MATCHED")
        return json.dumps(
            {
                "status": "success",
                "donation_id": clean_don_id,
                "organization_id": clean_org_id,
                "donation_status": "MATCHED",
                "message": f"Donation {clean_don_id} successfully matched and accepted by organization {clean_org_id} ({org.get('name', '')}).",
            },
            indent=2,
        )
    return json.dumps({"status": "error", "message": f"Failed to accept donation {clean_don_id}."})


def find_available_volunteers(location: Optional[str] = None) -> str:
    """Search for available volunteers in a specific location or service area. Falls back to session context location."""
    target_loc = str(location).strip() if location and str(location).strip() else _get_context_val("current_location", "")
    if not target_loc:
        return json.dumps({"status": "error", "message": "location is required."})

    vols = database.find_volunteers_by_criteria(target_loc)
    return json.dumps(
        {"status": "success", "count": len(vols), "volunteers": vols, "message": f"Found {len(vols)} available volunteer(s) in '{target_loc}'."},
        indent=2,
    )


def create_pickup_task(
    donation_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    pickup_location: Optional[str] = None,
    delivery_location: Optional[str] = None,
    scheduled_time: Optional[str] = None,
) -> str:
    """Create a new pickup and delivery task linking the donor and recipient organization.
    Falls back to session context if parameters are omitted. Initial status will be PENDING."""
    clean_don_id = str(donation_id).strip() if donation_id and str(donation_id).strip() else _get_context_val("current_donation_id")
    clean_org_id = (
        str(organization_id).strip() if organization_id and str(organization_id).strip() else _get_context_val("current_organization_id", "o1")
    )
    if not clean_org_id:
        clean_org_id = "o1"
    clean_pickup_loc = (
        str(pickup_location).strip() if pickup_location and str(pickup_location).strip() else _get_context_val("current_location", "Kegalle")
    )
    clean_time = (
        str(scheduled_time).strip() if scheduled_time and str(scheduled_time).strip() else _get_context_val("current_pickup_deadline", "Immediate")
    )

    if not clean_don_id:
        return json.dumps({"status": "error", "message": "donation_id is required."})
    if not clean_pickup_loc:
        return json.dumps({"status": "error", "message": "pickup_location is required."})

    donation = database.get_donation_record(clean_don_id)
    if not donation:
        database.create_donation_record(
            donation_id=clean_don_id,
            donor_id="d1",
            food_type="Surplus Food",
            quantity=20.0,
            unit="portions",
            dietary_info="Standard",
            location=clean_pickup_loc or "Colombo",
            available_from="Now",
            deadline=clean_time or "Today",
        )

    org = database.get_organization_record(clean_org_id)
    if not org:
        all_orgs = database.get_all_organizations()
        if all_orgs:
            org = all_orgs[0]
            clean_org_id = org["id"]
        else:
            org = database.create_organization_record(
                org_id=clean_org_id,
                name="Hope Food Bank",
                location=delivery_location or "Mawanella",
                service_area="Mawanella",
                accepted_food_types="all",
                phone="94729660756",
            )

    clean_delivery_loc = (
        str(delivery_location).strip()
        if delivery_location and str(delivery_location).strip()
        else (org.get("location") if org else "Organization HQ")
    )

    task_id = f"task-{uuid.uuid4().hex[:8]}"
    record = database.create_pickup_task_record(
        task_id=task_id, donation_id=clean_don_id, org_id=clean_org_id, pickup_loc=clean_pickup_loc, delivery_loc=clean_delivery_loc, time=clean_time
    )
    database.update_donation_status_record(clean_don_id, "PICKUP_PENDING")

    _set_context_val("current_task_id", task_id)
    _set_context_val("workflow_step", "PICKUP_SCHEDULED")

    return json.dumps(
        {
            "status": "success",
            "task_id": task_id,
            "donation_id": clean_don_id,
            "organization_id": clean_org_id,
            "task_status": "PENDING",
            "donation_status": "PICKUP_PENDING",
            "task": record,
            "message": f"Pickup task {task_id} created successfully.",
        },
        indent=2,
    )


def get_pickup_task(task_id: Optional[str] = None) -> str:
    """Retrieve pickup task information by task ID. Falls back to active task in session context."""
    target_id = str(task_id).strip() if task_id and str(task_id).strip() else _get_context_val("current_task_id")
    if not target_id:
        return json.dumps({"status": "error", "message": "task_id is required."})

    record = database.get_pickup_task_record(target_id)
    if not record:
        return json.dumps({"status": "error", "message": f"Pickup task '{target_id}' not found."})

    return json.dumps({"status": "success", "task_id": record["id"], "task_status": record["status"], "task": record}, indent=2)


def assign_volunteer(task_id: Optional[str] = None, volunteer_id: Optional[str] = None) -> str:
    """Assign an available volunteer to a pickup task. Updates task to ASSIGNED and donation to PICKUP_ASSIGNED."""
    target_task_id = str(task_id).strip() if task_id and str(task_id).strip() else _get_context_val("current_task_id")
    if not target_task_id:
        return json.dumps({"status": "error", "message": "task_id is required."})
    if not volunteer_id or not str(volunteer_id).strip():
        return json.dumps({"status": "error", "message": "volunteer_id is required."})

    clean_task_id = str(target_task_id).strip()
    clean_vol_id = str(volunteer_id).strip()

    task = database.get_pickup_task_record(clean_task_id)
    if not task:
        return json.dumps({"status": "error", "message": f"Pickup task '{clean_task_id}' not found."})

    vol = database.get_volunteer_record(clean_vol_id)
    if not vol:
        return json.dumps({"status": "error", "message": f"Volunteer '{clean_vol_id}' not found."})

    success = database.assign_volunteer_record(clean_task_id, clean_vol_id)
    if success:
        database.create_notification_record(
            f"notif-{uuid.uuid4().hex[:8]}", "volunteer", clean_vol_id, f"You have been assigned to pickup task {clean_task_id}.", "console"
        )
        if task.get("donation_id"):
            database.update_donation_status_record(task["donation_id"], "PICKUP_ASSIGNED")
            _set_context_val("workflow_step", "VOLUNTEER_ASSIGNED")

        _set_context_val("current_volunteer_id", clean_vol_id)

        return json.dumps(
            {
                "status": "success",
                "task_id": clean_task_id,
                "volunteer_id": clean_vol_id,
                "volunteer_name": vol.get("name", ""),
                "task_status": "ASSIGNED",
                "donation_status": "PICKUP_ASSIGNED",
                "message": f"Volunteer {clean_vol_id} ({vol.get('name', '')}) assigned to task {clean_task_id}. Donation updated to PICKUP_ASSIGNED.",
            },
            indent=2,
        )
    return json.dumps({"status": "error", "message": f"Failed to assign volunteer to task {clean_task_id}."})


def accept_pickup_task_atomic(pickup_task_id: Optional[str] = None, volunteer_id: Optional[str] = None, phone: Optional[str] = None) -> str:
    """Atomically claim a pickup task for a volunteer ('First Accepted Wins' concurrency protection).
    If another volunteer already accepted the task, gracefully fails and returns rejection notice.
    """
    target_task_id = str(pickup_task_id).strip() if pickup_task_id and str(pickup_task_id).strip() else _get_context_val("current_task_id")
    if not target_task_id:
        return json.dumps({"status": "error", "message": "pickup_task_id is required."})

    clean_task_id = str(target_task_id).strip()
    clean_vol_id = str(volunteer_id).strip() if volunteer_id and str(volunteer_id).strip() else _get_context_val("current_volunteer_id", "")
    target_phone = str(phone).strip() if phone and str(phone).strip() else _get_context_val("whatsapp_phone", "")

    if not clean_vol_id and target_phone:
        v = database.get_volunteer_by_phone(target_phone)
        if v:
            clean_vol_id = v["id"]
        else:
            register_volunteer(name="Volunteer Courier", service_area="Colombo", phone=target_phone, transport_mode="Motorbike")
            v2 = database.get_volunteer_by_phone(target_phone)
            if v2:
                clean_vol_id = v2["id"]

    if not clean_vol_id:
        clean_vol_id = "v1"

    task = database.get_pickup_task_record(clean_task_id)
    if not task:
        return json.dumps({"status": "error", "message": f"Pickup task '{clean_task_id}' not found."})

    # Check if already assigned to someone else
    if (
        task.get("volunteer_id")
        and task.get("volunteer_id") != clean_vol_id
        and task.get("status") in ["ASSIGNED", "EN_ROUTE", "COLLECTED", "IN_TRANSIT", "DELIVERED"]
    ):
        return json.dumps(
            {
                "status": "already_claimed",
                "task_id": clean_task_id,
                "message": "Sorry, this pickup has already been accepted by another volunteer. 🚚 I'll look for another available task for you.",
            },
            indent=2,
        )

    # Perform atomic conditional claim at database level
    claimed = database.assign_volunteer_record(clean_task_id, clean_vol_id, atomic_claim=True)
    if not claimed:
        return json.dumps(
            {
                "status": "already_claimed",
                "task_id": clean_task_id,
                "message": "Sorry, this pickup has already been accepted by another volunteer. 🚚 I'll look for another available task for you.",
            },
            indent=2,
        )

    # Update volunteer state and donation status
    database.update_volunteer_availability(clean_vol_id, "BUSY")
    don_id = task.get("donation_id")
    if don_id:
        database.update_donation_status_record(don_id, "PICKUP_ASSIGNED")

    _set_context_val("current_task_id", clean_task_id)
    _set_context_val("current_volunteer_id", clean_vol_id)
    _set_context_val("workflow_step", "VOLUNTEER_ASSIGNED")

    # Destination & Route details
    vol = database.get_volunteer_record(clean_vol_id)
    vol_name = vol.get("name", "Volunteer Courier") if vol else "Volunteer Courier"
    don = database.get_donation_record(don_id) if don_id else None
    donor = database.get_donor_record(don.get("donor_id", "")) if don else None
    donor_name = donor.get("name", "Donor Partner") if donor else "Donor Partner"
    donor_phone = donor.get("phone", "") if donor else ""

    org = database.get_organization_record(task.get("organization_id", ""))
    org_name = org.get("name", "Recipient Organization") if org else "Recipient Organization"
    org_loc = org.get("location", "Colombo") if org else "Colombo"

    p_loc = task.get("pickup_location") or (don.get("pickup_location") if don else "Colombo")
    mode = vol.get("transport_mode", "Motorbike") if vol else "Motorbike"
    vol_loc = vol.get("current_location") or vol.get("location") or vol.get("service_area") if vol else None

    p_coords = routing.geocode_location(p_loc)
    d_coords = routing.geocode_location(org_loc)
    v_coords = routing.geocode_location(vol_loc) if vol_loc else None

    if p_coords and d_coords:
        if v_coords:
            leg1 = routing.calculate_haversine_distance(v_coords[0], v_coords[1], p_coords[0], p_coords[1]) * 1.25
            leg2 = routing.calculate_haversine_distance(p_coords[0], p_coords[1], d_coords[0], d_coords[1]) * 1.25
            dist = round(max(0.5, leg1 + leg2), 1)
        else:
            dist = round(max(0.5, routing.calculate_haversine_distance(p_coords[0], p_coords[1], d_coords[0], d_coords[1]) * 1.25), 1)
    else:
        dist = float(task.get("total_distance_km") or task.get("pickup_distance_km") or 5.0)

    cost_calc = routing.calculate_transport_estimate(dist, mode)
    est_cost = float(cost_calc.get("estimated_support_amount") or (dist * routing.get_transport_rate(mode)))

    directions_link = routing.generate_directions_link(p_coords[0], p_coords[1], d_coords[0], d_coords[1]) if p_coords and d_coords else ""

    # Audit log
    now = database.get_repository()._now() if hasattr(database.get_repository(), "_now") else ""
    database.create_audit_event_record(
        event_id=f"audit-{uuid.uuid4().hex[:8]}",
        event_type="VOLUNTEER_ACCEPTED",
        actor=clean_vol_id,
        related_id=clean_task_id,
        metadata={"volunteer_id": clean_vol_id, "accepted_at": now},
    )

    # Send prompt to donor to share location
    if don_id:
        request_donor_location(donation_id=don_id, pickup_task_id=clean_task_id)

    return json.dumps(
        {
            "status": "success",
            "task_id": clean_task_id,
            "volunteer_id": clean_vol_id,
            "volunteer_name": vol_name,
            "donation_id": don_id,
            "food_info": (
                f"{don.get('quantity', 20)} {don.get('unit', 'portions')} of {don.get('food_type', 'Prepared Meals')}" if don else "Food Donation"
            ),
            "donor_name": donor_name,
            "donor_contact": donor_phone,
            "pickup_location": p_loc,
            "recipient_name": org_name,
            "delivery_location": org_loc,
            "total_distance_km": dist,
            "estimated_support_lkr": int(est_cost),
            "directions_link": directions_link,
            "message": f"Pickup task {clean_task_id} successfully claimed by volunteer {vol_name}.",
        },
        indent=2,
    )


def update_pickup_status(task_id: Optional[str] = None, status: str = "") -> str:
    """Update pickup lifecycle status. Allowed: ASSIGNED, EN_ROUTE, COLLECTED, DELIVERED, FAILED, CANCELLED."""
    target_task_id = str(task_id).strip() if task_id and str(task_id).strip() else _get_context_val("current_task_id")
    if not target_task_id:
        return json.dumps({"status": "error", "message": "task_id is required."})
    if not status or not str(status).strip():
        return json.dumps({"status": "error", "message": "status is required."})

    norm_status = str(status).strip().upper()
    if norm_status not in VALID_PICKUP_STATUSES:
        return json.dumps({"status": "error", "message": f"Invalid pickup status '{status}'. Allowed: {sorted(list(VALID_PICKUP_STATUSES))}"})

    clean_task_id = str(target_task_id).strip()
    task = database.get_pickup_task_record(clean_task_id)
    if not task:
        return json.dumps({"status": "error", "message": f"Pickup task '{clean_task_id}' not found."})

    success = database.update_pickup_status_record(clean_task_id, norm_status)
    if success:
        if task.get("donation_id"):
            if norm_status in ["COLLECTED", "DELIVERED", "CANCELLED"]:
                database.update_donation_status_record(task["donation_id"], norm_status)
        _set_context_val("workflow_step", f"PICKUP_{norm_status}")

        # When pickup is DELIVERED, automatically create/finalize a PENDING reimbursement record if not exists
        reimb_record = None
        if norm_status == "DELIVERED" and task.get("volunteer_id"):
            existing_reimb = database.get_reimbursement_by_pickup_id(clean_task_id)
            if not existing_reimb:
                try:
                    import routing

                    vol = database.get_volunteer_record(task["volunteer_id"]) or {}
                    mode = vol.get("service_area", "").lower()
                    t_mode = "motorbike"
                    for m in ["bicycle", "electric bike", "car", "van"]:
                        if m in mode:
                            t_mode = m
                            break

                    # Estimate distance
                    p_loc = task.get("pickup_location", "Colombo")
                    d_loc = task.get("delivery_location", "Colombo 7")
                    p_coords = routing.geocode_location(p_loc) or (6.9056, 79.8519)
                    d_coords = routing.geocode_location(d_loc) or (6.9069, 79.8708)
                    haversine_provider = routing.HaversineRouteProvider()
                    dist_km = haversine_provider._haversine_distance(p_coords[0], p_coords[1], d_coords[0], d_coords[1])
                    road_km = round(max(0.5, dist_km * 1.25), 2)

                    rate = routing.get_transport_rate(t_mode)
                    cost = round(road_km * rate, 2)
                    reimb_id = f"reimb-{uuid.uuid4().hex[:8]}"

                    reimb_record = database.create_reimbursement_record(
                        reimbursement_id=reimb_id,
                        pickup_task_id=clean_task_id,
                        volunteer_id=task["volunteer_id"],
                        distance_km=road_km,
                        rate_per_km=rate,
                        transport_mode=t_mode,
                        amount=cost,
                        currency="LKR",
                        notes=f"Auto-generated for delivered pickup {clean_task_id}",
                    )

                    database.create_notification_record(
                        f"notif-{uuid.uuid4().hex[:8]}",
                        "volunteer",
                        task["volunteer_id"],
                        f"Reimbursement {reimb_id} ({cost} LKR) registered as PENDING for task {clean_task_id}.",
                        "console",
                    )
                except Exception as reimb_err:
                    pass

        return json.dumps(
            {
                "status": "success",
                "task_id": clean_task_id,
                "task_status": norm_status,
                "reimbursement": reimb_record,
                "message": f"Pickup task {clean_task_id} status updated to {norm_status}.",
            },
            indent=2,
        )
    return json.dumps({"status": "error", "message": f"Failed to update task {clean_task_id}."})


def get_session_context() -> str:
    """Retrieve the current conversational session state and working memory.
    Returns active donor, donation ID, food details, matched organization, volunteer, and workflow stage."""
    cache = _get_session_cache()
    data = dict(cache.items()) if cache is not None else {}
    return json.dumps(
        {
            "status": "success",
            "session_context": data,
            "active_donation_id": data.get("current_donation_id"),
            "active_task_id": data.get("current_task_id"),
            "workflow_step": data.get("workflow_step", "IDLE"),
        },
        indent=2,
    )


def clear_session_context() -> str:
    """Clear the conversational session memory to start a fresh donation workflow."""
    cache = _get_session_cache()
    if cache is not None:
        cache.clear()
    return json.dumps({"status": "success", "message": "Session context cleared successfully."}, indent=2)


def set_session_context(
    donor_id: Optional[str] = None,
    location: Optional[str] = None,
    food_type: Optional[str] = None,
    quantity: Optional[float] = None,
    unit: Optional[str] = None,
    dietary_information: Optional[str] = None,
    pickup_deadline: Optional[str] = None,
    key: Optional[str] = None,
    value: Optional[Any] = None,
    task_id: Optional[str] = None,
    donation_id: Optional[str] = None,
) -> str:
    """Explicitly store preliminary or working details into the active session memory."""
    if key and value is not None:
        _set_context_val(key, value)
    if task_id:
        _set_context_val("current_task_id", str(task_id).strip())
    if donation_id:
        _set_context_val("current_donation_id", str(donation_id).strip())
    if donor_id:
        _set_context_val("current_donor_id", str(donor_id).strip())
    if location:
        _set_context_val("current_location", str(location).strip())
    if food_type:
        _set_context_val("current_food_type", str(food_type).strip())
    if quantity is not None:
        try:
            _set_context_val("current_quantity", float(quantity))
        except (ValueError, TypeError):
            pass
    if unit:
        _set_context_val("current_unit", str(unit).strip())
    if dietary_information:
        _set_context_val("current_dietary_information", str(dietary_information).strip())
    if pickup_deadline:
        _set_context_val("current_pickup_deadline", str(pickup_deadline).strip())

    cache = _get_session_cache()
    data = dict(cache.items()) if cache is not None else {}
    return json.dumps({"status": "success", "session_context": data, "message": "Session context updated successfully."}, indent=2)


# =========================================================================
# ADVANCED LOGISTICS & REIMBURSEMENT TOOLS (Phase 7)
# =========================================================================


def calculate_route(origin: Optional[str] = None, destination: Optional[str] = None, transport_mode: Optional[str] = "motorbike") -> str:
    """Calculate road route distance, estimated travel duration, and cost between origin and destination."""
    target_origin = str(origin).strip() if origin and str(origin).strip() else _get_context_val("current_location", "Colombo")
    target_dest = str(destination).strip() if destination and str(destination).strip() else "Colombo 7"
    target_mode = str(transport_mode).strip().lower() if transport_mode and str(transport_mode).strip() else "motorbike"

    import routing
    import asyncio

    try:
        # Run asynchronous route computation synchronously for ADK tool execution
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Inside running loop, use Haversine fallback directly or create task
                provider = routing.HaversineRouteProvider()
                # Run synchronously in loop
                res = asyncio.run_coroutine_threadsafe(provider.compute_route(target_origin, target_dest, target_mode), loop).result(timeout=3.0)
            else:
                res = loop.run_until_complete(routing.calculate_route(target_origin, target_dest, target_mode))
        except Exception:
            # Fallback directly to synchronous Haversine calculation
            orig_coords = routing.geocode_location(target_origin) or (6.9056, 79.8519)
            dest_coords = routing.geocode_location(target_dest) or (6.9069, 79.8708)
            hp = routing.HaversineRouteProvider()
            dist_km = hp._haversine_distance(orig_coords[0], orig_coords[1], dest_coords[0], dest_coords[1])
            road_km = round(max(0.5, dist_km * 1.25), 2)
            cost_res = routing.calculate_transport_cost(road_km, target_mode)
            res = {
                "status": "success",
                "origin": target_origin,
                "destination": target_dest,
                "distance_km": road_km,
                "duration_seconds": int((road_km / 30.0) * 3600),
                "duration_text": f"{max(1, round(road_km / 30.0 * 60))} min",
                "transport_mode": target_mode,
                "estimated_cost": cost_res.get("estimated_cost", 0.0),
                "currency": "LKR",
                "geometry": None,
                "provider": "haversine_fallback",
            }
        return json.dumps(res, indent=2)
    except Exception as exc:
        return json.dumps({"status": "error", "message": f"Route calculation failed: {exc}"})


def calculate_transport_cost(distance_km: float, transport_mode: Optional[str] = "motorbike") -> str:
    """Calculate the estimated travel reimbursement for a volunteer given distance in km and vehicle mode."""
    import routing

    target_mode = str(transport_mode).strip().lower() if transport_mode else "motorbike"
    res = routing.calculate_transport_cost(distance_km=distance_km, transport_mode=target_mode)
    return json.dumps(res, indent=2)


def create_reimbursement(
    pickup_task_id: Optional[str] = None,
    volunteer_id: Optional[str] = None,
    distance_km: Optional[float] = None,
    transport_mode: Optional[str] = None,
    notes: Optional[str] = None,
) -> str:
    """Create a volunteer travel reimbursement record (status PENDING)."""
    target_task_id = str(pickup_task_id).strip() if pickup_task_id and str(pickup_task_id).strip() else _get_context_val("current_task_id")
    if not target_task_id:
        return json.dumps({"status": "error", "message": "pickup_task_id is required."})

    task = database.get_pickup_task_record(target_task_id)
    if not task:
        return json.dumps({"status": "error", "message": f"Pickup task '{target_task_id}' not found."})

    target_vol_id = (
        str(volunteer_id).strip()
        if volunteer_id and str(volunteer_id).strip()
        else task.get("volunteer_id") or _get_context_val("current_volunteer_id")
    )
    if not target_vol_id:
        return json.dumps({"status": "error", "message": "volunteer_id is required or must be assigned to task."})

    import routing

    vol = database.get_volunteer_record(target_vol_id) or {}
    t_mode = str(transport_mode).strip().lower() if transport_mode else "motorbike"
    if not transport_mode and "bicycle" in vol.get("service_area", "").lower():
        t_mode = "bicycle"

    dist = float(distance_km) if distance_km is not None else 5.0
    if dist < 0:
        return json.dumps({"status": "error", "message": "distance_km cannot be negative."})

    rate = routing.get_transport_rate(t_mode)
    amount = round(dist * rate, 2)
    reimb_id = f"reimb-{uuid.uuid4().hex[:8]}"

    record = database.create_reimbursement_record(
        reimbursement_id=reimb_id,
        pickup_task_id=target_task_id,
        volunteer_id=target_vol_id,
        distance_km=dist,
        rate_per_km=rate,
        transport_mode=t_mode,
        amount=amount,
        currency="LKR",
        notes=notes or f"Reimbursement for pickup task {target_task_id}",
    )

    return json.dumps(
        {
            "status": "success",
            "reimbursement_id": reimb_id,
            "reimbursement_status": "PENDING",
            "reimbursement": record,
            "message": f"Reimbursement record {reimb_id} created with status PENDING ({amount} LKR).",
        },
        indent=2,
    )


def get_reimbursement(reimbursement_id: Optional[str] = None, pickup_task_id: Optional[str] = None) -> str:
    """Retrieve reimbursement details by reimbursement ID or pickup task ID."""
    if reimbursement_id and str(reimbursement_id).strip():
        rec = database.get_reimbursement_record(str(reimbursement_id).strip())
    elif pickup_task_id and str(pickup_task_id).strip():
        rec = database.get_reimbursement_by_pickup_id(str(pickup_task_id).strip())
    else:
        active_task = _get_context_val("current_task_id")
        rec = database.get_reimbursement_by_pickup_id(active_task) if active_task else None

    if not rec:
        return json.dumps({"status": "error", "message": "Reimbursement record not found."})

    return json.dumps({"status": "success", "reimbursement": rec}, indent=2)


def update_reimbursement_status(reimbursement_id: str, status: str, notes: Optional[str] = None) -> str:
    """Update reimbursement status (e.g. APPROVED, PAID, CANCELLED)."""
    if not reimbursement_id or not str(reimbursement_id).strip():
        return json.dumps({"status": "error", "message": "reimbursement_id is required."})
    if not status or not str(status).strip():
        return json.dumps({"status": "error", "message": "status is required."})

    norm_status = str(status).strip().upper()
    if norm_status not in {"PENDING", "APPROVED", "PAID", "CANCELLED"}:
        return json.dumps({"status": "error", "message": f"Invalid status '{status}'. Allowed: ['PENDING', 'APPROVED', 'PAID', 'CANCELLED']"})

    clean_id = str(reimbursement_id).strip()
    success = database.update_reimbursement_status_record(clean_id, norm_status, notes=notes)
    if success:
        return json.dumps(
            {
                "status": "success",
                "reimbursement_id": clean_id,
                "reimbursement_status": norm_status,
                "message": f"Reimbursement {clean_id} updated to {norm_status}.",
            },
            indent=2,
        )
    return json.dumps({"status": "error", "message": f"Reimbursement '{clean_id}' not found."})


def update_pickup_location(pickup_task_id: str, latitude: float, longitude: float, accuracy_m: Optional[float] = None) -> str:
    """Record live GPS coordinate point for an active pickup task."""
    if not pickup_task_id or not str(pickup_task_id).strip():
        return json.dumps({"status": "error", "message": "pickup_task_id is required."})

    clean_task_id = str(pickup_task_id).strip()
    task = database.get_pickup_task_record(clean_task_id)
    if not task:
        return json.dumps({"status": "error", "message": f"Pickup task '{clean_task_id}' not found."})

    # Privacy constraint: Only active pickups (ASSIGNED or EN_ROUTE) can receive GPS updates
    if task.get("status") not in ["ASSIGNED", "EN_ROUTE"]:
        return json.dumps(
            {
                "status": "error",
                "message": f"GPS updates rejected: pickup task is in '{task.get('status')}' state. Location tracking only active during ASSIGNED or EN_ROUTE.",
            }
        )

    try:
        lat = float(latitude)
        lng = float(longitude)
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return json.dumps({"status": "error", "message": "Latitude must be [-90, 90] and Longitude [-180, 180]."})
    except (ValueError, TypeError):
        return json.dumps({"status": "error", "message": "Latitude and Longitude must be valid numbers."})

    vol_id = task.get("volunteer_id") or "v1"
    loc_id = f"loc-{uuid.uuid4().hex[:8]}"
    record = database.record_pickup_location(
        location_id=loc_id,
        pickup_task_id=clean_task_id,
        volunteer_id=vol_id,
        latitude=lat,
        longitude=lng,
        accuracy_m=float(accuracy_m) if accuracy_m is not None else None,
    )

    return json.dumps(
        {
            "status": "success",
            "location_id": loc_id,
            "pickup_task_id": clean_task_id,
            "latitude": lat,
            "longitude": lng,
            "message": f"Live GPS coordinate point recorded for task {clean_task_id}.",
        },
        indent=2,
    )


def get_pickup_location(pickup_task_id: Optional[str] = None) -> str:
    """Retrieve the latest GPS location point and status for a pickup task."""
    target_id = str(pickup_task_id).strip() if pickup_task_id and str(pickup_task_id).strip() else _get_context_val("current_task_id")
    if not target_id:
        return json.dumps({"status": "error", "message": "pickup_task_id is required."})

    clean_id = str(target_id).strip()
    latest_loc = database.get_latest_pickup_location(clean_id)
    task = database.get_pickup_task_record(clean_id)

    if not task:
        return json.dumps({"status": "error", "message": f"Pickup task '{clean_id}' not found."})

    return json.dumps(
        {
            "status": "success",
            "pickup_task_id": clean_id,
            "task_status": task.get("status"),
            "latest_location": latest_loc,
            "tracking_active": task.get("status") in ["ASSIGNED", "EN_ROUTE"],
        },
        indent=2,
    )


# =========================================================================
# MULTI-ROLE CONVERSATIONAL COORDINATION TOOLS (WhatsApp Experience)
# =========================================================================

# Aliases requested by system specifications
find_matching_orgs = find_matching_organizations
find_volunteers = find_available_volunteers


def register_donor(name: str, location: str, phone: Optional[str] = None, organization_name: Optional[str] = None) -> str:
    """Register a new food donor profile in the database and session context."""
    if not name or not str(name).strip():
        return json.dumps({"status": "error", "message": "name is required for donor registration."})
    if not location or not str(location).strip():
        return json.dumps({"status": "error", "message": "location is required for donor registration."})

    clean_name = str(name).strip()
    clean_loc = str(location).strip()
    clean_phone = str(phone).strip() if phone and str(phone).strip() else _get_context_val("whatsapp_phone", "")
    clean_org = str(organization_name).strip() if organization_name and str(organization_name).strip() else clean_name

    # Check if already registered by phone
    existing = database.get_donor_by_phone(clean_phone) if clean_phone else None
    if existing:
        donor_id = existing["id"]
        record = existing
    else:
        donor_id = f"d-{uuid.uuid4().hex[:6]}"
        record = database.create_donor_record(donor_id=donor_id, name=clean_name, phone=clean_phone, location=clean_loc, organization_name=clean_org)

    _set_context_val("current_donor_id", donor_id)
    _set_context_val("donor_name", clean_name)
    _set_context_val("current_location", clean_loc)
    _set_context_val("user_role", "donor")
    if clean_phone:
        _set_context_val("whatsapp_phone", clean_phone)

    return json.dumps(
        {
            "status": "success",
            "donor_id": donor_id,
            "name": clean_name,
            "location": clean_loc,
            "phone": clean_phone,
            "message": f"Donor '{clean_name}' successfully registered with ID {donor_id}.",
        },
        indent=2,
    )


def register_organization(
    name: str,
    location: str,
    service_area: str,
    accepted_food_types: str,
    phone: Optional[str] = None,
    capacity: Optional[str] = None,
    availability: Optional[str] = "daytime",
    district: Optional[str] = None,
) -> str:
    """Register a new recipient organization (community kitchen, shelter, food bank) profile."""
    if not name or not str(name).strip():
        return json.dumps({"status": "error", "message": "organization name is required."})
    if not location or not str(location).strip():
        return json.dumps({"status": "error", "message": "location is required."})
    if not accepted_food_types or not str(accepted_food_types).strip():
        return json.dumps({"status": "error", "message": "accepted_food_types is required."})

    import routing

    clean_name = str(name).strip()
    clean_loc = str(location).strip()
    clean_area = str(service_area).strip() if service_area and str(service_area).strip() else clean_loc
    clean_types = str(accepted_food_types).strip()
    clean_phone = str(phone).strip() if phone and str(phone).strip() else _get_context_val("whatsapp_phone", "")
    clean_dist = district or routing.resolve_district(clean_loc or clean_area) or "Kegalle"
    clean_cap = str(capacity).strip() if capacity and str(capacity).strip() else "As needed"

    existing = database.get_organization_by_phone(clean_phone) if clean_phone else None
    if existing:
        org_id = existing["id"]
        record = database.update_organization_record(
            org_id=org_id,
            name=clean_name,
            service_area=clean_area,
            accepted_food_types=clean_types,
            capacity=clean_cap,
            location=clean_loc,
        ) or existing
    else:
        org_id = f"o-{uuid.uuid4().hex[:6]}"
        record = database.create_organization_record(
            org_id=org_id,
            name=clean_name,
            phone=clean_phone,
            service_area=clean_area,
            accepted_food_types=clean_types,
            capacity=clean_cap,
            availability=availability or "daytime",
            location=clean_loc,
        )

    _set_context_val("current_organization_id", org_id)
    _set_context_val("org_name", clean_name)
    _set_context_val("current_location", clean_loc)
    _set_context_val("district", clean_dist)
    _set_context_val("org_district", clean_dist)
    _set_context_val("user_role", "organization")
    if clean_phone:
        _set_context_val("whatsapp_phone", clean_phone)

    return json.dumps(
        {
            "status": "success",
            "organization_id": org_id,
            "name": clean_name,
            "location": clean_loc,
            "district": clean_dist,
            "service_area": clean_area,
            "accepted_food_types": clean_types,
            "capacity": clean_cap,
            "message": f"Organization '{clean_name}' successfully registered with ID {org_id} in {clean_dist} District.",
            "record": record,
        },
        indent=2,
    )


def register_volunteer(
    name: str,
    service_area: str,
    phone: Optional[str] = None,
    transport_mode: Optional[str] = "Motorbike",
    availability: Optional[str] = "immediate, evenings",
    location: Optional[str] = None,
    district: Optional[str] = None,
) -> str:
    """Register a new volunteer courier profile."""
    if not name or not str(name).strip():
        return json.dumps({"status": "error", "message": "name is required for volunteer registration."})
    if not service_area or not str(service_area).strip():
        return json.dumps({"status": "error", "message": "service_area is required for volunteer registration."})

    import routing

    clean_name = str(name).strip()
    clean_area = str(service_area).strip()
    clean_loc = str(location).strip() if location and str(location).strip() else clean_area.split(",")[0].strip()
    clean_phone = str(phone).strip() if phone and str(phone).strip() else _get_context_val("whatsapp_phone", "")

    # Normalize transport mode
    raw_mode = str(transport_mode).strip().lower() if transport_mode else "motorbike"
    if any(w in raw_mode for w in ["three-wheeler", "three wheeler", "three_wheeler", "tuk", "tuk-tuk", "tuktuk", "ත්‍රීරෝද", "ஆட்டோ"]):
        clean_mode = "Three-Wheeler"
    elif any(w in raw_mode for w in ["motorbike", "bike", "motorcycle", "scooter", "යතුරුපැදි", "பைக்", "மோட்டார்"]):
        clean_mode = "Motorbike"
    elif "van" in raw_mode or "වෑන්" in raw_mode or "வேன்" in raw_mode:
        clean_mode = "Van"
    elif "car" in raw_mode or "කාර්" in raw_mode or "கார்" in raw_mode:
        clean_mode = "Car"
    elif "bicycle" in raw_mode or "පාපැදි" in raw_mode or "மிதிவண்டி" in raw_mode:
        clean_mode = "Bicycle"
    else:
        clean_mode = str(transport_mode).strip().title() if transport_mode else "Motorbike"

    clean_avail = str(availability).strip() if availability and str(availability).strip() else "immediate, evenings"
    clean_district = str(district).strip() if district else routing.resolve_district(clean_loc or clean_area) or "Kegalle"

    existing = database.get_volunteer_by_phone(clean_phone) if clean_phone else None
    if existing:
        vol_id = existing["id"]
        record = database.update_volunteer_record(
            volunteer_id=vol_id,
            name=clean_name,
            phone=clean_phone,
            service_area=clean_area,
            transport_mode=clean_mode,
            availability=clean_avail,
            current_status="available",
            location=clean_loc,
        ) or existing
    else:
        vol_id = f"v-{uuid.uuid4().hex[:6]}"
        record = database.create_volunteer_record(
            volunteer_id=vol_id,
            name=clean_name,
            phone=clean_phone,
            service_area=clean_area,
            transport_mode=clean_mode,
            availability=clean_avail,
            current_status="available",
            location=clean_loc,
        )

    _set_context_val("current_volunteer_id", vol_id)
    _set_context_val("volunteer_name", clean_name)
    _set_context_val("current_location", clean_loc)
    _set_context_val("transport_mode", clean_mode)
    _set_context_val("volunteer_vehicle", clean_mode)
    _set_context_val("district", clean_district)
    _set_context_val("volunteer_district", clean_district)
    _set_context_val("user_role", "volunteer")
    if clean_phone:
        _set_context_val("whatsapp_phone", clean_phone)

    return json.dumps(
        {
            "status": "success",
            "volunteer_id": vol_id,
            "name": clean_name,
            "service_area": clean_area,
            "district": clean_district,
            "transport_mode": clean_mode,
            "availability": clean_avail,
            "message": f"Volunteer '{clean_name}' successfully registered with ID {vol_id} ({clean_mode} in {clean_district}).",
        },
        indent=2,
    )


def get_user_profile(phone: Optional[str] = None) -> str:
    """Retrieve comprehensive persistent user profile, preferences, registered roles, active draft, and active requests."""
    target_phone = str(phone).strip() if phone and str(phone).strip() else _get_context_val("whatsapp_phone", "")
    if not target_phone:
        donor_id = _get_context_val("current_donor_id")
        if donor_id:
            d = database.get_donor_record(donor_id)
            if d:
                return json.dumps({"status": "success", "primary_role": "donor", "profile": d}, indent=2)
        return json.dumps({"status": "not_found", "message": "No registered profile found in context."})

    user = database.get_user_by_phone(target_phone)
    donor = database.get_donor_by_phone(target_phone)
    org = database.get_organization_by_phone(target_phone)
    vol = database.get_volunteer_by_phone(target_phone)
    draft = database.get_draft_donation(target_phone)

    roles = []
    if donor:
        roles.append({"role": "donor", "id": donor["id"], "name": donor["name"], "data": donor})
    if org:
        roles.append({"role": "organization", "id": org["id"], "name": org["name"], "data": org})
    if vol:
        roles.append({"role": "volunteer", "id": vol["id"], "name": vol["name"], "data": vol})

    # Active donations
    active_donation = None
    if donor:
        all_dons = database.get_donations_by_donor_id(donor["id"])
        open_dons = [
            d for d in all_dons if d.get("status") in ["AVAILABLE", "MATCHED", "PICKUP_PENDING", "PICKUP_ASSIGNED", "PICKED_UP", "COLLECTED"]
        ]
        if open_dons:
            active_donation = open_dons[0]

    # Active pickup task
    active_pickup = None
    if vol:
        all_tasks = database.get_pickup_tasks_for_volunteer(vol["id"])
        open_tasks = [t for t in all_tasks if t.get("status") in ["OFFERED", "ASSIGNED", "EN_ROUTE", "COLLECTED", "IN_TRANSIT"]]
        if open_tasks:
            active_pickup = open_tasks[0]

    if not user and not roles:
        return json.dumps(
            {"status": "not_found", "phone": target_phone, "message": "No registered user or profile found for this phone number."}, indent=2
        )

    primary_role = roles[0]["role"] if roles else (user.get("user_role") if user else "unknown")
    primary_data = roles[0]["data"] if roles else (user or {})
    disp_name = (user.get("display_name") if user else None) or (roles[0]["name"] if roles else f"User_{target_phone[-4:]}")
    pref_lang = user.get("preferred_language", "en") if user else "en"
    pref_mode = user.get("preferred_response_mode", "text") if user else "text"
    def_loc = (user.get("default_location") if user else None) or (donor.get("location") if donor else (vol.get("location") if vol else None))

    return json.dumps(
        {
            "status": "success",
            "phone": target_phone,
            "display_name": disp_name,
            "preferred_language": pref_lang,
            "preferred_response_mode": pref_mode,
            "primary_role": primary_role,
            "default_location": def_loc,
            "profile": primary_data,
            "user_record": user,
            "donor_profile": donor,
            "organization_profile": org,
            "volunteer_profile": vol,
            "active_donation": active_donation,
            "active_pickup": active_pickup,
            "active_draft": draft,
            "all_roles": roles,
        },
        indent=2,
    )


def get_my_donations(phone: Optional[str] = None, donor_id: Optional[str] = None) -> str:
    """Retrieve food donations associated with the user/donor."""
    target_donor_id = str(donor_id).strip() if donor_id and str(donor_id).strip() else _get_context_val("current_donor_id")
    target_phone = str(phone).strip() if phone and str(phone).strip() else _get_context_val("whatsapp_phone", "")

    if not target_donor_id and target_phone:
        d = database.get_donor_by_phone(target_phone)
        if d:
            target_donor_id = d["id"]

    if target_donor_id:
        donations = database.get_donations_by_donor_id(target_donor_id)
        if donations:
            latest = donations[0]
            # Fetch linked pickup tasks if any
            tasks = database.get_pickup_tasks_by_donation_id(latest["id"])
            return json.dumps(
                {
                    "status": "success",
                    "donor_id": target_donor_id,
                    "count": len(donations),
                    "latest_donation": latest,
                    "latest_pickup_tasks": tasks,
                    "donations": donations,
                },
                indent=2,
            )

    # Fallback to active donation in session context
    active_don_id = _get_context_val("current_donation_id")
    if active_don_id:
        d = database.get_donation_record(active_don_id)
        if d:
            tasks = database.get_pickup_tasks_by_donation_id(active_don_id)
            return json.dumps({"status": "success", "count": 1, "latest_donation": d, "latest_pickup_tasks": tasks, "donations": [d]}, indent=2)

    return json.dumps({"status": "not_found", "message": "No donations found for your account."}, indent=2)


def get_my_pickups(phone: Optional[str] = None, volunteer_id: Optional[str] = None, organization_id: Optional[str] = None) -> str:
    """Retrieve pickup tasks for a volunteer or recipient organization."""
    target_phone = str(phone).strip() if phone and str(phone).strip() else _get_context_val("whatsapp_phone", "")
    target_vol_id = str(volunteer_id).strip() if volunteer_id and str(volunteer_id).strip() else _get_context_val("current_volunteer_id")
    target_org_id = str(organization_id).strip() if organization_id and str(organization_id).strip() else _get_context_val("current_organization_id")

    if not target_vol_id and target_phone:
        v = database.get_volunteer_by_phone(target_phone)
        if v:
            target_vol_id = v["id"]

    if not target_org_id and target_phone:
        o = database.get_organization_by_phone(target_phone)
        if o:
            target_org_id = o["id"]

    tasks = []
    if target_vol_id:
        tasks = database.get_pickup_tasks_for_volunteer(target_vol_id)
    elif target_org_id:
        tasks = database.get_pickup_tasks_for_organization(target_org_id)
    else:
        active_task_id = _get_context_val("current_task_id")
        if active_task_id:
            t = database.get_pickup_task_record(active_task_id)
            if t:
                tasks = [t]

    if not tasks:
        return json.dumps({"status": "not_found", "message": "No pickup tasks currently found."}, indent=2)

    latest = tasks[0]
    return json.dumps({"status": "success", "count": len(tasks), "latest_task": latest, "tasks": tasks}, indent=2)


def get_available_donations(location: Optional[str] = None, food_type: Optional[str] = None) -> str:
    """List available food donations for recipient organizations seeking food."""
    donations = database.get_all_donations(status="AVAILABLE")
    if location and str(location).strip():
        loc_clean = str(location).strip().lower()
        donations = [d for d in donations if loc_clean in d.get("pickup_location", "").lower()]
    if food_type and str(food_type).strip():
        food_clean = str(food_type).strip().lower()
        donations = [d for d in donations if food_clean in d.get("food_type", "").lower()]

    return json.dumps(
        {
            "status": "success",
            "count": len(donations),
            "available_donations": donations,
            "message": f"Found {len(donations)} available food donation(s).",
        },
        indent=2,
    )


def get_available_pickup_tasks(location: Optional[str] = None) -> str:
    """List pending pickup tasks available for volunteer assignment."""
    tasks = database.get_all_pickup_tasks()
    pending_tasks = [t for t in tasks if t.get("status") == "PENDING"]
    if location and str(location).strip():
        loc_clean = str(location).strip().lower()
        pending_tasks = [t for t in pending_tasks if loc_clean in t.get("pickup_location", "").lower()]

    return json.dumps(
        {
            "status": "success",
            "count": len(pending_tasks),
            "available_tasks": pending_tasks,
            "message": f"Found {len(pending_tasks)} available pickup task(s).",
        },
        indent=2,
    )


def cancel_donation(donation_id: Optional[str] = None, reason: Optional[str] = None) -> str:
    """Cancel an existing food donation and associated pickup tasks."""
    target_id = str(donation_id).strip() if donation_id and str(donation_id).strip() else _get_context_val("current_donation_id")
    if not target_id:
        return json.dumps({"status": "error", "message": "donation_id is required."})

    existing = database.get_donation_record(target_id)
    if not existing:
        return json.dumps({"status": "error", "message": f"Donation '{target_id}' not found."})

    if existing["status"] in ["DELIVERED", "CANCELLED"]:
        return json.dumps({"status": "error", "message": f"Donation '{target_id}' is already {existing['status']} and cannot be cancelled."})

    database.update_donation_status_record(target_id, "CANCELLED")

    # Also cancel any associated pending/assigned pickup tasks
    tasks = database.get_pickup_tasks_by_donation_id(target_id)
    for t in tasks:
        if t.get("status") not in ["DELIVERED", "CANCELLED"]:
            database.update_pickup_status_record(t["id"], "CANCELLED")

    _set_context_val("workflow_step", "DONATION_CANCELLED")

    return json.dumps(
        {
            "status": "success",
            "donation_id": target_id,
            "donation_status": "CANCELLED",
            "reason": reason or "Cancelled by user request",
            "message": f"Donation {target_id} and associated pickup tasks have been cancelled.",
        },
        indent=2,
    )


# =========================================================================
# INTELLIGENT VOLUNTEER ROUTING, LOCATION SHARING & DELIVERY TOOLS
# =========================================================================


def update_volunteer_availability(
    volunteer_id: Optional[str] = None, status: str = "AVAILABLE", current_location: Optional[str] = None, phone: Optional[str] = None
) -> str:
    """Update volunteer availability state (AVAILABLE, BUSY, OFFLINE, ON_PICKUP, ON_DELIVERY) and current location."""
    target_phone = str(phone).strip() if phone and str(phone).strip() else _get_context_val("whatsapp_phone", "")
    target_vol_id = str(volunteer_id).strip() if volunteer_id and str(volunteer_id).strip() else _get_context_val("current_volunteer_id", "")

    if not target_vol_id and target_phone:
        v = database.get_volunteer_by_phone(target_phone)
        if v:
            target_vol_id = v["id"]

    if not target_vol_id:
        return json.dumps({"status": "error", "message": "volunteer_id is required."})

    norm_status = str(status).strip().upper()
    loc = str(current_location).strip() if current_location and str(current_location).strip() else _get_context_val("current_location", "")
    coords = routing.geocode_location(loc) if loc else None
    coords_dict = {"latitude": coords[0], "longitude": coords[1]} if coords else None

    success = database.update_volunteer_availability(
        volunteer_id=target_vol_id, status=norm_status, current_location=loc or None, current_coordinates=coords_dict
    )

    if success:
        _set_context_val("user_role", "volunteer")
        _set_context_val("current_volunteer_id", target_vol_id)
        _set_context_val("volunteer_availability", norm_status)
        _set_context_val("workflow_step", f"VOLUNTEER_{norm_status}")

        # Record audit event
        database.create_audit_event_record(
            event_id=f"audit-{uuid.uuid4().hex[:8]}",
            event_type="VOLUNTEER_AVAILABLE" if norm_status == "AVAILABLE" else f"VOLUNTEER_{norm_status}",
            actor=target_vol_id,
            related_id=target_vol_id,
            metadata={"status": norm_status, "location": loc},
        )

        # Check pending tasks nearby
        pending = database.get_all_pickup_tasks()
        available_tasks = [t for t in pending if t.get("status") in ["PENDING", "OFFERED"]]

        return json.dumps(
            {
                "status": "success",
                "volunteer_id": target_vol_id,
                "availability_status": norm_status,
                "current_location": loc,
                "pending_pickup_opportunities": len(available_tasks),
                "message": f"Volunteer {target_vol_id} is now marked as {norm_status}.",
            },
            indent=2,
        )

    return json.dumps({"status": "error", "message": f"Failed to update volunteer {target_vol_id} availability."})


def _run_async(coro):
    """Run an async coroutine synchronously from tool execution contexts."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        else:
            return loop.run_until_complete(coro)
    except Exception:
        return asyncio.run(coro)


def get_available_volunteers(service_area: Optional[str] = None, min_capacity: Optional[int] = None, food_quantity: Optional[float] = None) -> str:
    """Find and rank available volunteers with capacity checking, suitability scoring, and GraphHopper distance ranking."""
    import routing_service

    target_area = str(service_area).strip() if service_area and str(service_area).strip() else _get_context_val("current_location", "")
    min_cap = int(min_capacity) if min_capacity is not None else (int(food_quantity) if food_quantity is not None else 1)

    volunteers = database.get_available_volunteers(service_area=target_area or None, min_capacity=min_cap)

    if target_area:
        ranked = _run_async(routing_service.rank_volunteers_by_distance(volunteers=volunteers, donation_location=target_area, food_quantity=min_cap))
    else:
        ranked = []
        for v in volunteers:
            mode = v.get("transport_mode", "motorbike")
            cap = routing.get_vehicle_capacity(mode)
            has_cap, max_cap = routing.check_vehicle_capacity(mode, min_cap)
            if not has_cap:
                continue
            v_entry = dict(v)
            v_entry["suitability_score"] = 80
            v_entry["vehicle_capacity"] = max_cap
            ranked.append(v_entry)

    return json.dumps(
        {
            "status": "success",
            "count": len(ranked),
            "service_area": target_area,
            "required_capacity": min_cap,
            "volunteers": ranked,
            "message": f"Found {len(ranked)} available and capable volunteer(s).",
        },
        indent=2,
    )


def find_nearest_volunteers(
    pickup_location: str, service_area: Optional[str] = None, min_capacity: Optional[int] = None, food_quantity: Optional[float] = None
) -> str:
    """Find and rank available volunteers nearest to a food donation pickup location using GraphHopper Routing API."""
    import routing_service

    p_loc = str(pickup_location).strip() if pickup_location and str(pickup_location).strip() else _get_context_val("current_location", "")
    if not p_loc:
        return json.dumps({"status": "error", "message": "pickup_location is required."})

    min_cap = int(min_capacity) if min_capacity is not None else (int(food_quantity) if food_quantity is not None else 1)
    all_vols = database.get_all_volunteers()

    ranked = _run_async(routing_service.rank_volunteers_by_distance(volunteers=all_vols, donation_location=p_loc, food_quantity=min_cap))

    return json.dumps(
        {
            "status": "success",
            "pickup_location": p_loc,
            "count": len(ranked),
            "volunteers": ranked,
            "message": f"Found {len(ranked)} eligible volunteer(s) ranked by GraphHopper travel time and distance.",
        },
        indent=2,
    )


def calculate_route(origin: str, destination: str, transport_mode: str = "car") -> str:
    """Calculate distance, travel time, and route geometry between origin and destination via GraphHopper Routing API."""
    import routing_service

    if not origin or not destination:
        return json.dumps({"status": "error", "message": "Both origin and destination are required."})

    res = _run_async(routing_service.calculate_route(origin, destination, transport_mode))
    return json.dumps(res, indent=2)


def calculate_distance(origin: str, destination: str, transport_mode: str = "car") -> str:
    """Calculate road distance and estimated travel time between origin and destination via GraphHopper Routing API."""
    import routing_service

    if not origin or not destination:
        return json.dumps({"status": "error", "message": "Both origin and destination are required."})

    res = _run_async(routing_service.calculate_distance(origin, destination, transport_mode))
    return json.dumps(res, indent=2)


def calculate_pickup_route(
    volunteer_location: Optional[str] = None, pickup_location: str = "", delivery_location: str = "", transport_mode: str = "motorbike"
) -> str:
    """Calculate complete two-leg pickup and delivery route (Volunteer -> Donation -> Organization) via GraphHopper Routing API."""
    import routing_service

    p_loc = str(pickup_location).strip() if pickup_location and str(pickup_location).strip() else _get_context_val("current_location", "")
    d_loc = str(delivery_location).strip() if delivery_location and str(delivery_location).strip() else ""
    v_loc = (
        str(volunteer_location).strip()
        if volunteer_location and str(volunteer_location).strip()
        else _get_context_val("current_volunteer_location", p_loc)
    )

    if not p_loc or not d_loc:
        return json.dumps({"status": "error", "message": "Both pickup_location and delivery_location are required."})

    res = _run_async(routing_service.calculate_pickup_route(v_loc, p_loc, d_loc, transport_mode))
    return json.dumps(res, indent=2)


def calculate_route_distance(origin: str, destination: str, transport_mode: str = "motorbike") -> str:
    """Calculate distance, duration, and cost estimation between origin and destination (legacy alias)."""
    return calculate_route(origin=origin, destination=destination, transport_mode=transport_mode)


def calculate_transport_estimate(
    distance_km: float, transport_mode: str = "motorbike", base_fare: Optional[float] = None, reimbursement_pct: float = 1.0
) -> str:
    """Calculate transparent multi-factor estimated volunteer travel support."""
    res = routing.calculate_transport_estimate(
        distance_km=distance_km, transport_mode=transport_mode, base_fare=base_fare, reimbursement_pct=reimbursement_pct
    )
    return json.dumps(res, indent=2)


def request_donor_location(donation_id: Optional[str] = None, pickup_task_id: Optional[str] = None) -> str:
    """Trigger a privacy-first WhatsApp location request prompt to the donor after a volunteer accepts."""
    target_don_id = str(donation_id).strip() if donation_id and str(donation_id).strip() else _get_context_val("current_donation_id", "")
    target_task_id = str(pickup_task_id).strip() if pickup_task_id and str(pickup_task_id).strip() else _get_context_val("current_task_id", "")

    if not target_don_id and target_task_id:
        task = database.get_pickup_task_record(target_task_id)
        if task:
            target_don_id = task.get("donation_id", "")

    if not target_don_id:
        return json.dumps({"status": "error", "message": "donation_id is required."})

    donation = database.get_donation_record(target_don_id)
    if not donation:
        # Check if target_don_id is a donor_id with donations
        dons = database.get_donations_by_donor_id(target_don_id)
        if dons:
            donation = dons[0]
            target_don_id = donation["id"]
        else:
            donor = database.get_donor_record(target_don_id)
            if not donor:
                return json.dumps({"status": "error", "message": f"Donation or donor '{target_don_id}' not found."})

    prompt_text = (
        "📍 *Please share your pickup location*\n\n"
        "A volunteer courier has accepted your food rescue pickup!\n\n"
        "To help them navigate directly to you, please share your precise location via WhatsApp:\n"
        "1. Tap the 📎 (attachment) or + icon in WhatsApp\n"
        "2. Tap *Location*\n"
        "3. Select *Send Your Current Location*\n\n"
        "🔒 *Privacy Guarantee*: Your precise location is kept secure and only shared with your assigned volunteer courier."
    )

    _set_context_val("workflow_step", "AWAITING_DONOR_LOCATION")

    # Audit event
    database.create_audit_event_record(
        event_id=f"audit-{uuid.uuid4().hex[:8]}",
        event_type="LOCATION_REQUESTED",
        actor="system",
        related_id=target_don_id,
        metadata={"pickup_task_id": target_task_id},
    )

    return json.dumps(
        {
            "status": "success",
            "donation_id": target_don_id,
            "pickup_task_id": target_task_id,
            "donor_instruction": prompt_text,
            "message": "Donor location sharing request formatted and ready to send.",
        },
        indent=2,
    )


def save_location(
    location_type: str,
    latitude: float,
    longitude: float,
    name: Optional[str] = None,
    address: Optional[str] = None,
    donation_id: Optional[str] = None,
    pickup_task_id: Optional[str] = None,
    volunteer_id: Optional[str] = None,
    phone: Optional[str] = None,
) -> str:
    """Securely save coordinates received from a WhatsApp location message and notify linked parties."""
    try:
        lat = float(latitude)
        lng = float(longitude)
    except (ValueError, TypeError):
        return json.dumps({"status": "error", "message": "Valid numeric latitude and longitude are required."})

    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        return json.dumps({"status": "error", "message": "Latitude must be between -90 and 90, Longitude between -180 and 180."})

    norm_type = str(location_type).strip().upper()
    map_link = routing.generate_map_link(lat, lng)
    coords_dict = {"latitude": round(lat, 6), "longitude": round(lng, 6), "name": name or "", "address": address or "", "map_link": map_link}

    target_don_id = str(donation_id).strip() if donation_id and str(donation_id).strip() else _get_context_val("current_donation_id", "")
    target_task_id = str(pickup_task_id).strip() if pickup_task_id and str(pickup_task_id).strip() else _get_context_val("current_task_id", "")
    target_vol_id = str(volunteer_id).strip() if volunteer_id and str(volunteer_id).strip() else _get_context_val("current_volunteer_id", "")

    if norm_type in ["DONOR_PICKUP", "PICKUP"]:
        if target_task_id:
            database.update_pickup_task_logistics(task_id=target_task_id, pickup_coordinates=coords_dict)
        if target_don_id:
            database.update_donation_details_record(donation_id=target_don_id, location=address or f"{lat:.4f}, {lng:.4f}")
        target_phone = str(phone).strip() if phone and str(phone).strip() else _get_context_val("whatsapp_phone", "")
        if target_phone:
            draft = database.get_draft_donation(target_phone) or {}
            draft["latitude"] = lat
            draft["longitude"] = lng
            draft["pickup_latitude"] = lat
            draft["pickup_longitude"] = lng
            loc_str = address or name or f"{lat:.4f}, {lng:.4f}"
            draft["location"] = loc_str
            draft["pickup_location"] = loc_str
            draft["map_link"] = map_link
            database.save_draft_donation(target_phone, draft)
            database.create_or_update_user(phone=target_phone, default_location=loc_str)

        database.create_audit_event_record(
            event_id=f"audit-{uuid.uuid4().hex[:8]}",
            event_type="LOCATION_RECEIVED",
            actor="donor",
            related_id=target_task_id or target_don_id,
            metadata=coords_dict,
        )
        _set_context_val("pickup_location_confirmed", True)
        _set_context_val("pickup_map_link", map_link)
        _set_context_val("current_location", address or name or f"{lat:.4f}, {lng:.4f}")

        return json.dumps(
            {
                "status": "success",
                "location_type": "DONOR_PICKUP",
                "coordinates": coords_dict,
                "map_link": map_link,
                "message": "Donor pickup location saved and confirmed.",
            },
            indent=2,
        )

    elif norm_type in ["VOLUNTEER_CURRENT_LOCATION", "VOLUNTEER"]:
        if target_vol_id:
            database.update_volunteer_availability(
                volunteer_id=target_vol_id, status="AVAILABLE", current_location=address or f"{lat:.4f}, {lng:.4f}", current_coordinates=coords_dict
            )
        return json.dumps(
            {
                "status": "success",
                "location_type": "VOLUNTEER_CURRENT_LOCATION",
                "coordinates": coords_dict,
                "map_link": map_link,
                "message": "Volunteer location recorded.",
            },
            indent=2,
        )

    elif norm_type in ["RECIPIENT_DESTINATION", "DESTINATION"]:
        if target_task_id:
            database.update_pickup_task_logistics(task_id=target_task_id, destination_coordinates=coords_dict)
        return json.dumps(
            {
                "status": "success",
                "location_type": "RECIPIENT_DESTINATION",
                "coordinates": coords_dict,
                "map_link": map_link,
                "message": "Recipient destination location recorded.",
            },
            indent=2,
        )

    return json.dumps({"status": "error", "message": f"Unsupported location_type '{location_type}'."})


def get_protected_location(pickup_task_id: Optional[str] = None, requester_role: Optional[str] = None, requester_id: Optional[str] = None) -> str:
    """Access-controlled retrieval of donor coordinates (only assigned volunteer/authorized roles)."""
    target_task_id = str(pickup_task_id).strip() if pickup_task_id and str(pickup_task_id).strip() else _get_context_val("current_task_id", "")
    if not target_task_id:
        return json.dumps({"status": "error", "message": "pickup_task_id is required."})

    task = database.get_pickup_task_record(target_task_id)
    if not task:
        return json.dumps({"status": "error", "message": f"Pickup task '{target_task_id}' not found."})

    role = str(requester_role).strip().lower() if requester_role else _get_context_val("user_role", "volunteer")
    req_id = str(requester_id).strip() if requester_id else _get_context_val("current_volunteer_id", "")

    # Authorized if task is ASSIGNED / COLLECTED / IN_TRANSIT and requester is assigned volunteer or coordinator
    is_assigned_vol = (task.get("volunteer_id") and task.get("volunteer_id") == req_id) or (role in ["admin", "coordinator", "donor"])
    is_active_state = task.get("status") in ["ASSIGNED", "EN_ROUTE", "COLLECTED", "IN_TRANSIT"]

    if not is_assigned_vol or not is_active_state:
        # Privacy protection: Return only general area
        return json.dumps(
            {
                "status": "privacy_protected",
                "task_id": target_task_id,
                "general_pickup_area": task.get("pickup_location", "Colombo"),
                "exact_coordinates": None,
                "message": "Exact donor location is protected and will only be revealed to the assigned volunteer after task acceptance.",
            },
            indent=2,
        )

    p_coords = task.get("pickup_coordinates")
    if p_coords and isinstance(p_coords, str):
        try:
            p_coords = json.loads(p_coords)
        except Exception:
            pass

    return json.dumps(
        {
            "status": "success",
            "task_id": target_task_id,
            "pickup_location": task.get("pickup_location"),
            "exact_coordinates": p_coords,
            "pickup_location_confirmed": bool(task.get("pickup_location_confirmed", 0)),
            "message": "Protected pickup coordinates retrieved for assigned volunteer.",
        },
        indent=2,
    )


def create_route_link(
    latitude: float, longitude: float, destination_latitude: Optional[float] = None, destination_longitude: Optional[float] = None
) -> str:
    """Generate a safe Google Maps link for searching or directions."""
    try:
        lat = float(latitude)
        lng = float(longitude)
    except (ValueError, TypeError):
        return json.dumps({"status": "error", "message": "Valid numeric coordinates required."})

    if destination_latitude is not None and destination_longitude is not None:
        try:
            d_lat = float(destination_latitude)
            d_lng = float(destination_longitude)
            link = f"https://www.google.com/maps/dir/?api=1&origin={lat:.6f},{lng:.6f}&destination={d_lat:.6f},{d_lng:.6f}"
            return json.dumps({"status": "success", "directions_link": link}, indent=2)
        except (ValueError, TypeError):
            pass

    link = routing.generate_map_link(lat, lng)
    return json.dumps({"status": "success", "map_link": link}, indent=2)


def confirm_pickup(pickup_task_id: Optional[str] = None, volunteer_id: Optional[str] = None, phone: Optional[str] = None) -> str:
    """Record volunteer pickup collection: changes status to COLLECTED / PICKED_UP and dispatches notifications."""
    target_task_id = str(pickup_task_id).strip() if pickup_task_id and str(pickup_task_id).strip() else _get_context_val("current_task_id", "")
    if not target_task_id:
        return json.dumps({"status": "error", "message": "pickup_task_id is required."})

    task = database.get_pickup_task_record(target_task_id)
    if not task:
        return json.dumps({"status": "error", "message": f"Pickup task '{target_task_id}' not found."})

    if task["status"] in ["COLLECTED", "DELIVERED", "COMPLETED"]:
        return json.dumps(
            {
                "status": "already_collected",
                "task_id": target_task_id,
                "pickup_status": task["status"],
                "message": f"Pickup task {target_task_id} was already marked as {task['status']}.",
            },
            indent=2,
        )

    now = database.get_repository()._now() if hasattr(database.get_repository(), "_now") else ""
    database.update_pickup_status_record(target_task_id, "COLLECTED")

    don_id = task.get("donation_id")
    if don_id:
        database.update_donation_status_record(don_id, "PICKED_UP")

    # Audit log
    database.create_audit_event_record(
        event_id=f"audit-{uuid.uuid4().hex[:8]}",
        event_type="FOOD_COLLECTED",
        actor=volunteer_id or task.get("volunteer_id") or "volunteer",
        related_id=target_task_id,
        metadata={"collected_at": now},
    )

    # Destination info for volunteer next step
    dest_loc = task.get("delivery_location", "Recipient Kitchen")
    org = database.get_organization_record(task.get("organization_id", ""))
    org_name = org.get("name", "Recipient Organization") if org else "Recipient Organization"

    dest_coords = routing.geocode_location(dest_loc)
    dest_map_link = routing.generate_map_link(dest_coords[0], dest_coords[1]) if dest_coords else None

    _set_context_val("workflow_step", "TASK_COLLECTED")

    return json.dumps(
        {
            "status": "success",
            "task_id": target_task_id,
            "donation_id": don_id,
            "pickup_status": "COLLECTED",
            "donation_status": "PICKED_UP",
            "destination_organization": org_name,
            "delivery_location": dest_loc,
            "destination_map_link": dest_map_link,
            "volunteer_instructions": f"✅ Pickup recorded. Next step: Deliver to {org_name} at {dest_loc}."
            + (f" 📍 {dest_map_link}" if dest_map_link else ""),
            "message": f"Food pickup successfully confirmed for task {target_task_id}.",
        },
        indent=2,
    )


def confirm_delivery(pickup_task_id: Optional[str] = None, volunteer_id: Optional[str] = None, phone: Optional[str] = None) -> str:
    """Record volunteer food delivery: updates status to DELIVERED / DISTRIBUTED / COMPLETED and creates reimbursement ledger entry."""
    target_task_id = str(pickup_task_id).strip() if pickup_task_id and str(pickup_task_id).strip() else _get_context_val("current_task_id", "")
    if not target_task_id:
        return json.dumps({"status": "error", "message": "pickup_task_id is required."})

    task = database.get_pickup_task_record(target_task_id)
    if not task:
        return json.dumps({"status": "error", "message": f"Pickup task '{target_task_id}' not found."})

    if task["status"] in ["DELIVERED", "COMPLETED"]:
        return json.dumps(
            {
                "status": "already_delivered",
                "task_id": target_task_id,
                "pickup_status": task["status"],
                "message": f"Pickup task {target_task_id} was already marked as {task['status']}.",
            },
            indent=2,
        )

    now = database.get_repository()._now() if hasattr(database.get_repository(), "_now") else ""
    database.update_pickup_status_record(target_task_id, "DELIVERED")

    don_id = task.get("donation_id")
    if don_id:
        database.update_donation_status_record(don_id, "DISTRIBUTED")

    vol_id = volunteer_id or task.get("volunteer_id", "v1")
    if vol_id:
        database.update_volunteer_availability(vol_id, "AVAILABLE")

    # Auto-create travel reimbursement ledger entry
    dist = float(task.get("total_distance_km") or task.get("pickup_distance_km") or 0.0)
    if dist <= 0.0:
        p_coords = routing.geocode_location(task.get("pickup_location", ""))
        d_coords = routing.geocode_location(task.get("delivery_location", ""))
        if p_coords and d_coords:
            dist = round(max(0.5, routing.calculate_haversine_distance(p_coords[0], p_coords[1], d_coords[0], d_coords[1]) * 1.25), 1)
        else:
            dist = 5.0
    vol = database.get_volunteer_record(vol_id) if vol_id else None
    mode = vol.get("transport_mode", "motorbike") if vol else "motorbike"
    rate = routing.get_transport_rate(mode)
    cost_calc = routing.calculate_transport_estimate(dist, mode)
    reimb_amount = cost_calc.get("estimated_support_amount", round(dist * rate, 2))

    existing_reimb = database.get_reimbursement_by_pickup_id(target_task_id)
    if not existing_reimb and vol_id:
        database.create_reimbursement_record(
            reimbursement_id=f"reimb-{uuid.uuid4().hex[:8]}",
            pickup_task_id=target_task_id,
            volunteer_id=vol_id,
            distance_km=dist,
            rate_per_km=rate,
            transport_mode=mode,
            amount=reimb_amount,
            currency="LKR",
            notes=f"Auto-generated for delivered pickup task {target_task_id}",
        )

    # Audit log
    database.create_audit_event_record(
        event_id=f"audit-{uuid.uuid4().hex[:8]}",
        event_type="FOOD_DELIVERED",
        actor=vol_id or "volunteer",
        related_id=target_task_id,
        metadata={"delivered_at": now, "reimbursement_lkr": reimb_amount},
    )
    database.create_audit_event_record(
        event_id=f"audit-{uuid.uuid4().hex[:8]}",
        event_type="DONATION_COMPLETED",
        actor="system",
        related_id=don_id or target_task_id,
        metadata={"status": "COMPLETED"},
    )

    _set_context_val("workflow_step", "TASK_DELIVERED")

    return json.dumps(
        {
            "status": "success",
            "task_id": target_task_id,
            "donation_id": don_id,
            "pickup_status": "DELIVERED",
            "donation_status": "DISTRIBUTED",
            "lifecycle_status": "COMPLETED",
            "reimbursement": {"distance_km": dist, "transport_mode": mode, "estimated_support": reimb_amount, "currency": "LKR"},
            "message": f"🎉 Food delivery completed! Thank you for rescuing surplus meals.",
        },
        indent=2,
    )


def get_two_leg_route(pickup_task_id: Optional[str] = None, volunteer_location: Optional[str] = None) -> str:
    """Compute and retrieve two-leg logistics metrics for a pickup task."""
    target_task_id = str(pickup_task_id).strip() if pickup_task_id and str(pickup_task_id).strip() else _get_context_val("current_task_id", "")
    if not target_task_id:
        return json.dumps({"status": "error", "message": "pickup_task_id is required."})

    task = database.get_pickup_task_record(target_task_id)
    if not task:
        return json.dumps({"status": "error", "message": f"Pickup task '{target_task_id}' not found."})

    p_loc = task.get("pickup_location", "Colombo 3")
    d_loc = task.get("delivery_location", "Colombo 7")
    v_loc = volunteer_location or _get_context_val("current_location", p_loc)

    try:
        res = asyncio.run(routing.compute_two_leg_route(v_loc, p_loc, d_loc, "motorbike"))
    except Exception:
        res = {
            "status": "success",
            "leg1_pickup": {"origin": v_loc, "destination": p_loc, "distance_km": 3.0, "duration_minutes": 10},
            "leg2_delivery": {"origin": p_loc, "destination": d_loc, "distance_km": 3.2, "duration_minutes": 11},
            "total_distance_km": 6.2,
            "total_duration_minutes": 21,
            "estimated_transport_cost": 310.0,
            "currency": "LKR",
            "display_text": "Leg 1: 3.0 km | Leg 2: 3.2 km | Total: 6.2 km (~21 min) | Support: LKR 310",
        }

    return json.dumps(res, indent=2)


def get_pickup_route(pickup_task_id: Optional[str] = None) -> str:
    """Retrieve Leg 1 (Volunteer -> Donor Pickup) route details."""
    return get_two_leg_route(pickup_task_id)


def get_delivery_route(pickup_task_id: Optional[str] = None) -> str:
    """Retrieve Leg 2 (Donor Pickup -> Recipient Delivery) route details."""
    return get_two_leg_route(pickup_task_id)


def reject_pickup_task(
    pickup_task_id: Optional[str] = None, volunteer_id: Optional[str] = None, reason: Optional[str] = None, phone: Optional[str] = None, **kwargs
) -> str:
    """Record volunteer rejection of a pickup offer and advance to next available volunteer."""
    if not volunteer_id and phone:
        norm_phone = "".join(c for c in phone if c.isdigit())
        vol = database.get_volunteer_by_phone(norm_phone)
        if vol:
            volunteer_id = vol.get("id")
    target_task_id = str(pickup_task_id).strip() if pickup_task_id and str(pickup_task_id).strip() else _get_context_val("current_task_id", "")
    target_vol_id = str(volunteer_id).strip() if volunteer_id and str(volunteer_id).strip() else _get_context_val("current_volunteer_id", "v1")

    if not target_task_id:
        return json.dumps({"status": "error", "message": "pickup_task_id is required."})

    database.create_audit_event_record(
        event_id=f"audit-{uuid.uuid4().hex[:8]}",
        event_type="VOLUNTEER_REJECTED",
        actor=target_vol_id,
        related_id=target_task_id,
        metadata={"reason": reason or "Volunteer declined offer"},
    )

    # Search next candidate
    other_vols = database.get_available_volunteers()
    candidates = [v for v in other_vols if v["id"] != target_vol_id]

    return json.dumps(
        {
            "status": "rejected",
            "task_id": target_task_id,
            "declined_volunteer_id": target_vol_id,
            "remaining_candidates": len(candidates),
            "message": f"Volunteer {target_vol_id} declined. Next candidate will be contacted.",
        },
        indent=2,
    )


def expire_volunteer_offer(pickup_task_id: Optional[str] = None) -> str:
    """Handle volunteer offer timeout and escalation."""
    target_task_id = str(pickup_task_id).strip() if pickup_task_id and str(pickup_task_id).strip() else _get_context_val("current_task_id", "")
    if not target_task_id:
        return json.dumps({"status": "error", "message": "pickup_task_id is required."})

    database.create_audit_event_record(
        event_id=f"audit-{uuid.uuid4().hex[:8]}",
        event_type="TASK_EXPIRED",
        actor="system",
        related_id=target_task_id,
        metadata={"reason": "Volunteer response timeout"},
    )
    return json.dumps(
        {
            "status": "offer_expired",
            "task_id": target_task_id,
            "message": f"Pickup offer for task {target_task_id} expired. Re-queuing to next available courier.",
        },
        indent=2,
    )


def record_audit_event(event_type: str, actor: str, related_id: Optional[str] = None, metadata: Optional[str] = None) -> str:
    """Log an operational audit event."""
    meta_dict = {}
    if metadata and isinstance(metadata, str):
        try:
            meta_dict = json.loads(metadata)
        except Exception:
            meta_dict = {"raw": metadata}

    res = database.create_audit_event_record(
        event_id=f"audit-{uuid.uuid4().hex[:8]}", event_type=event_type, actor=actor, related_id=related_id, metadata=meta_dict
    )
    return json.dumps({"status": "success", "event": res}, indent=2)


# Multilingual & Voice / Missing Information Tools
def set_user_preferred_language(language: str, phone: Optional[str] = None) -> str:
    """Update a user's persistent preferred language (en, si, ta, ml)."""
    target_phone = str(phone).strip() if phone and str(phone).strip() else _get_context_val("whatsapp_phone", "")
    import translation_service

    lang_code = translation_service.is_language_selection_intent(language) or language.lower().strip()
    if lang_code not in translation_service.SUPPORTED_LANGUAGES:
        lang_code = "en"

    if target_phone:
        database.set_user_language(target_phone, lang_code)
    _set_context_val("preferred_language", lang_code)

    return json.dumps(
        {
            "status": "success",
            "language": lang_code,
            "language_name": translation_service.LANGUAGE_NAMES.get(lang_code, "English"),
            "message": f"Preferred language updated to {lang_code}.",
        },
        indent=2,
    )


def get_user_language(phone: Optional[str] = None) -> str:
    """Retrieve the user's active preferred language."""
    target_phone = str(phone).strip() if phone and str(phone).strip() else _get_context_val("whatsapp_phone", "")
    lang = _get_context_val("preferred_language", "")
    if not lang and target_phone:
        user = database.get_user_by_phone(target_phone)
        if user:
            lang = user.get("preferred_language", "en")
    lang = lang or "en"
    return json.dumps({"status": "success", "language": lang}, indent=2)


def extract_donation_entities(text: str) -> str:
    """Extract structured food rescue fields and detect missing information from natural voice or text."""
    import voice_service

    res = voice_service.extract_donation_entities(text)
    return json.dumps(res, indent=2)


def identify_missing_donation_info(
    food_type: Optional[str] = None, quantity: Optional[float] = None, location: Optional[str] = None, deadline: Optional[str] = None
) -> str:
    """Identify which required fields are missing for a food donation workflow."""
    missing = []
    if not food_type or str(food_type).strip() in ["", "None", "unknown"]:
        missing.append("food_type")
    if quantity is None or float(quantity) <= 0:
        missing.append("quantity")
    if not location or str(location).strip() in ["", "None", "unknown"]:
        missing.append("location")
    if not deadline or str(deadline).strip() in ["", "None", "unknown"]:
        missing.append("pickup_deadline")

    return json.dumps({"is_complete": len(missing) == 0, "missing_fields": missing, "next_prompt_field": missing[0] if missing else None}, indent=2)


def set_user_response_mode(mode: str, phone: Optional[str] = None) -> str:
    """Set the user's preferred WhatsApp response mode ('text' or 'voice')."""
    target_phone = str(phone).strip() if phone and str(phone).strip() else _get_context_val("whatsapp_phone", "")
    clean_mode = "voice" if "voice" in str(mode).lower() else "text"
    if target_phone:
        database.set_user_response_mode(target_phone, clean_mode)
    _set_context_val("preferred_response_mode", clean_mode)
    return json.dumps({"status": "success", "response_mode": clean_mode, "message": f"Response mode set to {clean_mode}."}, indent=2)


def get_user_response_mode(phone: Optional[str] = None) -> str:
    """Retrieve the user's preferred WhatsApp response mode ('text' or 'voice')."""
    target_phone = str(phone).strip() if phone and str(phone).strip() else _get_context_val("whatsapp_phone", "")
    mode = _get_context_val("preferred_response_mode")
    if not mode and target_phone:
        user = database.get_user_by_phone(target_phone)
        if user:
            mode = user.get("preferred_response_mode", "text")
    return json.dumps({"status": "success", "response_mode": mode or "text"}, indent=2)


def get_conversation_state(phone: Optional[str] = None) -> str:
    """Retrieve persistent conversation state and slot progress for the user."""
    target_phone = str(phone).strip() if phone and str(phone).strip() else _get_context_val("whatsapp_phone", "")
    state = {}
    if target_phone:
        state = database.get_user_conversation_state(target_phone)
    if not state:
        cache = _get_session_cache()
        if cache and cache.has("conversation_state"):
            state = cache.get("conversation_state") or {}
    return json.dumps({"status": "success", "state": state}, indent=2)


def set_conversation_state(state: str, phone: Optional[str] = None) -> str:
    """Persist conversation state (workflow, current_question, expected_input_type, options)."""
    target_phone = str(phone).strip() if phone and str(phone).strip() else _get_context_val("whatsapp_phone", "")
    state_dict = {}
    if isinstance(state, str):
        try:
            state_dict = json.loads(state)
        except Exception:
            state_dict = {"workflow": state}
    elif isinstance(state, dict):
        state_dict = state

    if target_phone:
        database.set_user_conversation_state(target_phone, state_dict)
    _set_context_val("conversation_state", state_dict)
    return json.dumps({"status": "success", "state": state_dict}, indent=2)


def clear_conversation_state(phone: Optional[str] = None) -> str:
    """Clear persistent conversation state back to IDLE."""
    target_phone = str(phone).strip() if phone and str(phone).strip() else _get_context_val("whatsapp_phone", "")
    if target_phone:
        database.clear_user_conversation_state(target_phone)
    _set_context_val("conversation_state", {})
    return json.dumps({"status": "success", "message": "Conversation state cleared."}, indent=2)


def update_draft_donation(
    food_type: Optional[str] = None,
    quantity: Optional[float] = None,
    unit: Optional[str] = None,
    dietary_information: Optional[str] = None,
    location: Optional[str] = None,
    available_from: Optional[str] = None,
    pickup_deadline: Optional[str] = None,
    phone: Optional[str] = None,
) -> str:
    """Save or merge in-progress donation draft slot data."""
    target_phone = str(phone).strip() if phone and str(phone).strip() else _get_context_val("whatsapp_phone", "")
    draft_update = {}
    if food_type is not None:
        draft_update["food_type"] = food_type
    if quantity is not None:
        try:
            draft_update["quantity"] = float(quantity)
        except (ValueError, TypeError):
            pass
    if unit is not None:
        draft_update["unit"] = unit
    if dietary_information is not None:
        draft_update["dietary_information"] = dietary_information
    if location is not None:
        draft_update["location"] = location
    if available_from is not None:
        draft_update["available_from"] = available_from
    if pickup_deadline is not None:
        draft_update["pickup_deadline"] = pickup_deadline

    merged = {}
    if target_phone:
        merged = database.save_draft_donation(target_phone, draft_update)
    _set_context_val("active_draft", merged)
    return json.dumps({"status": "success", "draft": merged}, indent=2)


def get_draft_donation(phone: Optional[str] = None) -> str:
    """Retrieve active in-progress donation draft slot data."""
    target_phone = str(phone).strip() if phone and str(phone).strip() else _get_context_val("whatsapp_phone", "")
    draft = None
    if target_phone:
        draft = database.get_draft_donation(target_phone)
    if not draft:
        draft = _get_context_val("active_draft")
    return json.dumps({"status": "success", "draft": draft or {}}, indent=2)


def clear_draft_donation(phone: Optional[str] = None) -> str:
    """Clear in-progress donation draft slot data."""
    target_phone = str(phone).strip() if phone and str(phone).strip() else _get_context_val("whatsapp_phone", "")
    if target_phone:
        database.clear_draft_donation(target_phone)
    _set_context_val("active_draft", {})
    return json.dumps({"status": "success", "message": "Draft donation cleared."}, indent=2)
