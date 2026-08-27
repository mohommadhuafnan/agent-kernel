"""FoodRescue AI MongoDB Repository Implementation.

Encapsulates all MongoDB storage operations, collection setups, indexing,
CRUD operations, and proximity/dietary ranking algorithms.
"""

import os
import datetime
import uuid
from typing import List, Dict, Any, Optional
import pymongo
from pymongo.collection import Collection
from pymongo.database import Database
from db_base import BaseRepository

DEFAULT_MONGO_DB = "foodrescue"


class MongoRepository(BaseRepository):
    """MongoDB implementation of the FoodRescue persistence repository."""

    def __init__(
        self,
        uri: Optional[str] = None,
        db_name: Optional[str] = None,
        db_instance: Optional[Database] = None
    ):
        self._uri = uri or os.environ.get("MONGODB_URI", "")
        self._db_name = db_name or os.environ.get("MONGODB_DATABASE", DEFAULT_MONGO_DB)
        self._client: Optional[pymongo.MongoClient] = None
        self._db: Optional[Database] = db_instance

    def _get_db(self) -> Database:
        """Retrieve active MongoDB Database instance, connecting lazily if needed."""
        if self._db is not None:
            return self._db

        if not self._uri:
            raise ValueError(
                "MONGODB_URI environment variable is not configured. "
                "Set MONGODB_URI to connect to MongoDB, or use FOODRESCUE_DB_BACKEND=sqlite."
            )

        if self._client is None:
            # Set server selection timeout to fail fast on unreachable servers
            self._client = pymongo.MongoClient(
                self._uri,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000
            )

        self._db = self._client[self._db_name]
        return self._db

    def _now(self) -> str:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    def _clean_doc(self, doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Normalize document for callers by ensuring `id` exists and stripping internal `_id`."""
        if not doc:
            return None
        res = dict(doc)
        if "_id" in res:
            if "id" not in res:
                res["id"] = str(res["_id"])
            del res["_id"]
        return res

    def _clean_docs(self, docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize a list of documents."""
        return [d for d in (self._clean_doc(doc) for doc in docs) if d is not None]

    # Collections
    @property
    def donors_col(self) -> Collection:
        return self._get_db()["donors"]

    @property
    def organizations_col(self) -> Collection:
        return self._get_db()["organizations"]

    @property
    def volunteers_col(self) -> Collection:
        return self._get_db()["volunteers"]

    @property
    def donations_col(self) -> Collection:
        return self._get_db()["donations"]

    @property
    def pickup_tasks_col(self) -> Collection:
        return self._get_db()["pickup_tasks"]

    @property
    def notifications_col(self) -> Collection:
        return self._get_db()["notifications"]

    @property
    def reimbursements_col(self) -> Collection:
        return self._get_db()["reimbursements"]

    @property
    def pickup_location_history_col(self) -> Collection:
        return self._get_db()["pickup_location_history"]

    @property
    def audit_events_col(self) -> Collection:
        return self._get_db()["audit_events"]

    @property
    def users_col(self) -> Collection:
        return self._get_db()["users"]

    @property
    def messages_col(self) -> Collection:
        return self._get_db()["messages"]

    @property
    def system_settings_col(self) -> Collection:
        return self._get_db()["system_settings"]

    @property
    def qr_codes_col(self) -> Collection:
        return self._get_db()["qr_codes"]

    def setup_database(self) -> None:
        """Create necessary indexes on all collections."""
        try:
            # Donors indexes
            self.donors_col.create_index([("id", pymongo.ASCENDING)], unique=True)
            self.donors_col.create_index([("phone", pymongo.ASCENDING)])

            # QR codes indexes
            self.qr_codes_col.create_index([("token", pymongo.ASCENDING)], unique=True)
            self.qr_codes_col.create_index([("task_id", pymongo.ASCENDING)])
            self.qr_codes_col.create_index([("id", pymongo.ASCENDING)], unique=True)
            self.audit_events_col.create_index([("id", pymongo.ASCENDING)], unique=True)
            self.audit_events_col.create_index([("related_id", pymongo.ASCENDING)])
            self.users_col.create_index([("phone_number", pymongo.ASCENDING)], unique=True)

            # Organizations indexes
            self.organizations_col.create_index([("id", pymongo.ASCENDING)], unique=True)
            self.organizations_col.create_index([("service_area", pymongo.ASCENDING)])
            self.organizations_col.create_index([("location", pymongo.ASCENDING)])

            # Volunteers indexes
            self.volunteers_col.create_index([("id", pymongo.ASCENDING)], unique=True)
            self.volunteers_col.create_index([("current_status", pymongo.ASCENDING)])
            self.volunteers_col.create_index([("service_area", pymongo.ASCENDING)])
            self.volunteers_col.create_index([("location", pymongo.ASCENDING)])

            # Donations indexes
            self.donations_col.create_index([("id", pymongo.ASCENDING)], unique=True)
            self.donations_col.create_index([("status", pymongo.ASCENDING)])
            self.donations_col.create_index([("pickup_location", pymongo.ASCENDING)])
            self.donations_col.create_index([("created_at", pymongo.DESCENDING)])

            # Pickup tasks indexes
            self.pickup_tasks_col.create_index([("id", pymongo.ASCENDING)], unique=True)
            self.pickup_tasks_col.create_index([("donation_id", pymongo.ASCENDING)])
            self.pickup_tasks_col.create_index([("organization_id", pymongo.ASCENDING)])
            self.pickup_tasks_col.create_index([("volunteer_id", pymongo.ASCENDING)])
            self.pickup_tasks_col.create_index([("status", pymongo.ASCENDING)])
            self.pickup_tasks_col.create_index([("created_at", pymongo.DESCENDING)])

            # Notifications indexes
            self.notifications_col.create_index([("id", pymongo.ASCENDING)], unique=True)
            self.notifications_col.create_index([("recipient_id", pymongo.ASCENDING)])
            self.notifications_col.create_index([("created_at", pymongo.DESCENDING)])

            # Reimbursements indexes
            self.reimbursements_col.create_index([("id", pymongo.ASCENDING)], unique=True)
            self.reimbursements_col.create_index([("pickup_task_id", pymongo.ASCENDING)])
            self.reimbursements_col.create_index([("volunteer_id", pymongo.ASCENDING)])
            self.reimbursements_col.create_index([("status", pymongo.ASCENDING)])
            self.reimbursements_col.create_index([("created_at", pymongo.DESCENDING)])

            # Pickup location history indexes
            self.pickup_location_history_col.create_index([("id", pymongo.ASCENDING)], unique=True)
            self.pickup_location_history_col.create_index([("pickup_task_id", pymongo.ASCENDING)])
            self.pickup_location_history_col.create_index([("volunteer_id", pymongo.ASCENDING)])
            self.pickup_location_history_col.create_index([("timestamp", pymongo.DESCENDING)])

            # Seed default system settings if not present
            if self.system_settings_col.count_documents({"setting_key": "transport_cost"}) == 0:
                self.system_settings_col.insert_one({
                    "setting_key": "transport_cost",
                    "setting_value": {
                        "base_fare": 100.0,
                        "cost_per_km": 80.0,
                        "currency": "LKR",
                        "rates_by_vehicle": {
                            "Motorbike": 50.0,
                            "Three-Wheeler": 90.0,
                            "Car": 80.0,
                            "Van": 120.0,
                            "Bicycle": 25.0,
                            "Electric Bike": 25.0
                        },
                        "vehicle_multipliers": {
                            "Motorbike": 1.0,
                            "Bicycle": 0.6,
                            "Car": 1.5,
                            "Van": 2.0,
                            "Three-Wheeler": 1.2
                        }
                    },
                    "updated_at": self._now()
                })
        except Exception:
            pass

    def seed_test_data(self) -> None:
        """Seed master data if collections are empty."""
        now = self._now()
        if self.donors_col.count_documents({}) == 0:
            self.donors_col.insert_many([
                {
                    "id": "d1",
                    "name": "Grand Hotel",
                    "phone": "+94112345678",
                    "organization_name": "Grand Hotel Colombo",
                    "location": "Colombo",
                    "created_at": now
                },
                {
                    "id": "d2",
                    "name": "City Bakery",
                    "phone": "+94112345679",
                    "organization_name": "City Bakery Colombo",
                    "location": "Colombo 4",
                    "created_at": now
                }
            ])

        if self.organizations_col.count_documents({}) == 0:
            self.organizations_col.insert_many([
                {
                    "id": "o1",
                    "name": "Community Kitchen Colombo",
                    "phone": "+94119876543",
                    "service_area": "Colombo, Dehiwala",
                    "accepted_food_types": "vegetarian, non-vegetarian, lunch packets, cooked meals, bakery items",
                    "capacity": "200 meals",
                    "availability": "always",
                    "location": "Colombo 7",
                    "created_at": now
                },
                {
                    "id": "o2",
                    "name": "Hope Food Bank",
                    "phone": "+94119876544",
                    "service_area": "Colombo 3, Colombo 4, Wellawatte",
                    "accepted_food_types": "dry rations, bakery items, vegetarian",
                    "capacity": "100 meals",
                    "availability": "daytime",
                    "location": "Colombo 4",
                    "created_at": now
                }
            ])

        if self.volunteers_col.count_documents({}) == 0:
            now = self._now()
            self.volunteers_col.insert_many([
                {
                    "id": "v1",
                    "name": "Amara Silva",
                    "phone": "+94771234567",
                    "service_area": "Colombo, Colombo 3, Colombo 4, Colombo 7",
                    "availability": "immediate, evenings",
                    "current_status": "available",
                    "location": "Colombo 3",
                    "created_at": now
                },
                {
                    "id": "v2",
                    "name": "Kamal Perera",
                    "phone": "+94771234568",
                    "service_area": "Colombo, Dehiwala, Mount Lavinia",
                    "availability": "weekends, evenings",
                    "current_status": "available",
                    "location": "Colombo 5",
                    "created_at": now
                }
            ])

    def _normalize_phone(self, phone: str) -> str:
        if not phone:
            return ""
        return "".join(ch for ch in str(phone) if ch.isdigit())

    def get_donor_record(self, donor_id: str) -> Optional[Dict[str, Any]]:
        doc = self.donors_col.find_one({"id": donor_id})
        return self._clean_doc(doc)

    def get_donor_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        if not phone:
            return None
        norm_digits = self._normalize_phone(phone)
        docs = self._clean_docs(list(self.donors_col.find({})))
        for d in docs:
            d_digits = self._normalize_phone(d.get("phone", ""))
            if d_digits and norm_digits and (d_digits == norm_digits or d_digits.endswith(norm_digits) or norm_digits.endswith(d_digits)):
                return d
        return None

    def create_donor_record(
        self,
        donor_id: str,
        name: str,
        phone: str,
        location: str,
        organization_name: Optional[str] = None
    ) -> Dict[str, Any]:
        now = self._now()
        doc = {
            "id": donor_id,
            "name": name,
            "phone": phone,
            "organization_name": organization_name or name,
            "location": location,
            "created_at": now
        }
        self.donors_col.insert_one(doc)
        return self._clean_doc(doc) or {}

    def get_organization_record(self, org_id: str) -> Optional[Dict[str, Any]]:
        doc = self.organizations_col.find_one({"id": org_id})
        return self._clean_doc(doc)

    def get_organization_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        if not phone:
            return None
        norm_digits = self._normalize_phone(phone)
        docs = self._clean_docs(list(self.organizations_col.find({})))
        for o in docs:
            o_digits = self._normalize_phone(o.get("phone", ""))
            if o_digits and norm_digits and (o_digits == norm_digits or o_digits.endswith(norm_digits) or norm_digits.endswith(o_digits)):
                return o
        return None

    def create_organization_record(
        self,
        org_id: str,
        name: str,
        phone: str,
        service_area: str,
        accepted_food_types: str,
        capacity: Optional[str] = None,
        availability: Optional[str] = "daytime",
        location: Optional[str] = None
    ) -> Dict[str, Any]:
        now = self._now()
        loc = location or service_area.split(",")[0].strip()
        doc = {
            "id": org_id,
            "name": name,
            "phone": phone,
            "service_area": service_area,
            "accepted_food_types": accepted_food_types,
            "capacity": capacity if (capacity and str(capacity).strip()) else "As needed",
            "availability": availability or "daytime",
            "location": loc,
            "created_at": now
        }
        self.organizations_col.insert_one(doc)
        return self._clean_doc(doc) or {}

    def update_organization_record(
        self,
        org_id: str,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        service_area: Optional[str] = None,
        accepted_food_types: Optional[str] = None,
        capacity: Optional[str] = None,
        availability: Optional[str] = None,
        location: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        update_fields = {}
        if name is not None:
            update_fields["name"] = name
        if phone is not None:
            update_fields["phone"] = phone
        if service_area is not None:
            update_fields["service_area"] = service_area
        if accepted_food_types is not None:
            update_fields["accepted_food_types"] = accepted_food_types
        if capacity is not None:
            update_fields["capacity"] = capacity
        if availability is not None:
            update_fields["availability"] = availability
        if location is not None:
            update_fields["location"] = location

        if update_fields:
            self.organizations_col.update_one({"id": org_id}, {"$set": update_fields})
        return self.get_organization_record(org_id)

    def get_volunteer_record(self, volunteer_id: str) -> Optional[Dict[str, Any]]:
        doc = self.volunteers_col.find_one({"id": volunteer_id})
        return self._clean_doc(doc)

    def get_volunteer_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        if not phone:
            return None
        norm_digits = self._normalize_phone(phone)
        docs = self._clean_docs(list(self.volunteers_col.find({})))
        for v in docs:
            v_digits = self._normalize_phone(v.get("phone", ""))
            if v_digits and norm_digits and (v_digits == norm_digits or v_digits.endswith(norm_digits) or norm_digits.endswith(v_digits)):
                return v
        return None

    def create_volunteer_record(
        self,
        volunteer_id: str,
        name: str,
        phone: str,
        service_area: str,
        transport_mode: str = "Motorbike",
        availability: str = "immediate, evenings",
        current_status: str = "available",
        location: Optional[str] = None
    ) -> Dict[str, Any]:
        now = self._now()
        loc = location or service_area.split(",")[0].strip()
        doc = {
            "id": volunteer_id,
            "name": name,
            "phone": phone,
            "service_area": service_area,
            "transport_mode": transport_mode,
            "availability": availability,
            "current_status": current_status,
            "location": loc,
            "created_at": now
        }
        self.volunteers_col.update_one({"id": volunteer_id}, {"$set": doc}, upsert=True)
        saved = self.volunteers_col.find_one({"id": volunteer_id})
        return self._clean_doc(saved) or {}

    def update_volunteer_record(
        self,
        volunteer_id: str,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        service_area: Optional[str] = None,
        transport_mode: Optional[str] = None,
        availability: Optional[str] = None,
        current_status: Optional[str] = None,
        location: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        update_fields: Dict[str, Any] = {}
        if name is not None:
            update_fields["name"] = name
        if phone is not None:
            update_fields["phone"] = self._normalize_phone(phone)
        if service_area is not None:
            update_fields["service_area"] = service_area
        if transport_mode is not None:
            update_fields["transport_mode"] = transport_mode
        if availability is not None:
            update_fields["availability"] = availability
        if current_status is not None:
            update_fields["current_status"] = current_status
        if location is not None:
            update_fields["location"] = location

        if not update_fields:
            return self.get_volunteer_record(volunteer_id)

        self.volunteers_col.update_one({"id": volunteer_id}, {"$set": update_fields})
        doc = self.volunteers_col.find_one({"id": volunteer_id})
        return self._clean_doc(doc)


    def create_donation_record(
        self,
        donation_id: str,
        donor_id: str,
        food_type: str,
        quantity: float,
        unit: str,
        dietary_info: str,
        location: str,
        available_from: str,
        deadline: str
    ) -> Dict[str, Any]:
        qty = float(quantity)
        if qty <= 0:
            raise ValueError("Quantity must be greater than 0")

        now = self._now()
        doc = {
            "id": donation_id,
            "donor_id": donor_id,
            "food_type": food_type,
            "quantity": qty,
            "unit": unit,
            "dietary_information": dietary_info,
            "pickup_location": location,
            "available_from": available_from,
            "pickup_deadline": deadline,
            "status": "AVAILABLE",
            "created_at": now,
            "updated_at": now
        }
        self.donations_col.insert_one(doc)
        return self._clean_doc(doc) or {}

    def get_donation_record(self, donation_id: str) -> Optional[Dict[str, Any]]:
        doc = self.donations_col.find_one({"id": donation_id})
        return self._clean_doc(doc)

    def update_donation_status_record(self, donation_id: str, status: str) -> bool:
        now = self._now()
        res = self.donations_col.update_one(
            {"id": donation_id},
            {"$set": {"status": status, "updated_at": now}}
        )
        return res.matched_count > 0

    def update_donation_details_record(
        self,
        donation_id: str,
        food_type: Optional[str] = None,
        quantity: Optional[float] = None,
        unit: Optional[str] = None,
        dietary_info: Optional[str] = None,
        location: Optional[str] = None,
        available_from: Optional[str] = None,
        deadline: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        now = self._now()
        updates: Dict[str, Any] = {}

        if food_type is not None and str(food_type).strip():
            updates["food_type"] = str(food_type).strip()
        if quantity is not None:
            updates["quantity"] = float(quantity)
        if unit is not None and str(unit).strip():
            updates["unit"] = str(unit).strip()
        if dietary_info is not None:
            updates["dietary_information"] = str(dietary_info).strip()
        if location is not None and str(location).strip():
            updates["pickup_location"] = str(location).strip()
        if available_from is not None and str(available_from).strip():
            updates["available_from"] = str(available_from).strip()
        if deadline is not None and str(deadline).strip():
            updates["pickup_deadline"] = str(deadline).strip()

        if not updates:
            return self.get_donation_record(donation_id)

        updates["updated_at"] = now
        res = self.donations_col.update_one(
            {"id": donation_id},
            {"$set": updates}
        )
        if res.matched_count > 0:
            return self.get_donation_record(donation_id)
        return None

    def find_organizations_by_criteria(self, food_type: str, location: str) -> List[Dict[str, Any]]:
        loc_clean = location.strip().lower()
        food_clean = food_type.strip().lower()
        all_orgs = self._clean_docs(list(self.organizations_col.find({})))

        import routing
        target_district = (routing.resolve_district(location) or "").lower()

        ranked_orgs = []
        for org in all_orgs:
            score = 0
            service_area = org.get("service_area", "").lower()
            org_location = org.get("location", "").lower()
            org_district = (routing.resolve_district(org.get("service_area") or org.get("location")) or "").lower()
            accepted_types = org.get("accepted_food_types", "").lower()

            if target_district and org_district and target_district == org_district:
                score += 30

            if loc_clean in service_area or loc_clean in org_location:
                score += 15
            elif any(part.strip() in service_area for part in loc_clean.split() if len(part.strip()) > 2):
                score += 5

            if food_clean in accepted_types:
                score += 10
            elif any(part.strip() in accepted_types for part in food_clean.split() if len(part.strip()) > 3):
                score += 5

            if score > 0:
                org["match_score"] = score
                ranked_orgs.append(org)

        ranked_orgs.sort(key=lambda x: x.get("match_score", 0), reverse=True)
        return ranked_orgs if ranked_orgs else all_orgs

    def accept_donation_record(self, donation_id: str, organization_id: str) -> bool:
        don = self.get_donation_record(donation_id)
        if not don:
            return False

        now = self._now()
        res = self.donations_col.update_one(
            {"id": donation_id},
            {"$set": {"status": "MATCHED", "updated_at": now}}
        )
        return res.matched_count > 0

    def find_volunteers_by_criteria(self, location: str) -> List[Dict[str, Any]]:
        loc_clean = location.strip().lower()
        all_vols = self._clean_docs(list(self.volunteers_col.find({"current_status": "available"})))

        import routing
        target_district = (routing.resolve_district(location) or "").lower()

        matched_vols = []
        for vol in all_vols:
            score = 0
            service_area = vol.get("service_area", "").lower()
            vol_loc = vol.get("location", "").lower()
            vol_district = (routing.resolve_district(vol.get("service_area") or vol.get("location") or vol.get("current_location")) or "").lower()

            if target_district and vol_district and target_district == vol_district:
                score += 30

            if loc_clean in service_area or loc_clean in vol_loc:
                score += 15
            elif any(part.strip() in service_area for part in loc_clean.split() if len(part.strip()) > 2):
                score += 5

            if score > 0:
                vol["match_score"] = score
                matched_vols.append(vol)

        matched_vols.sort(key=lambda x: x.get("match_score", 0), reverse=True)
        return matched_vols if matched_vols else all_vols

    def create_pickup_task_record(
        self,
        task_id: str,
        donation_id: str,
        org_id: str,
        pickup_loc: str,
        delivery_loc: str,
        time: str
    ) -> Dict[str, Any]:
        now = self._now()
        doc = {
            "id": task_id,
            "donation_id": donation_id,
            "organization_id": org_id,
            "volunteer_id": None,
            "pickup_location": pickup_loc,
            "delivery_location": delivery_loc,
            "scheduled_time": time,
            "status": "PENDING",
            "created_at": now,
            "updated_at": now
        }
        self.pickup_tasks_col.insert_one(doc)
        return self._clean_doc(doc) or {}

    def get_pickup_task_record(self, task_id: str) -> Optional[Dict[str, Any]]:
        doc = self.pickup_tasks_col.find_one({"id": task_id})
        return self._clean_doc(doc)

    def get_pickup_tasks_by_donation_id(self, donation_id: str) -> List[Dict[str, Any]]:
        docs = list(self.pickup_tasks_col.find({"donation_id": donation_id}).sort("created_at", pymongo.DESCENDING))
        return self._clean_docs(docs)

    def get_donations_by_donor_id(self, donor_id: str) -> List[Dict[str, Any]]:
        docs = list(self.donations_col.find({"donor_id": donor_id}).sort("created_at", pymongo.DESCENDING))
        return self._clean_docs(docs)

    def get_pickup_tasks_for_volunteer(self, volunteer_id: str) -> List[Dict[str, Any]]:
        docs = list(self.pickup_tasks_col.find({"volunteer_id": volunteer_id}).sort("created_at", pymongo.DESCENDING))
        return self._clean_docs(docs)

    def get_pickup_tasks_for_organization(self, org_id: str) -> List[Dict[str, Any]]:
        docs = list(self.pickup_tasks_col.find({"organization_id": org_id}).sort("created_at", pymongo.DESCENDING))
        return self._clean_docs(docs)

    def assign_volunteer_record(self, task_id: str, volunteer_id: str, atomic_claim: bool = False) -> bool:
        now = self._now()
        filter_q = {"id": task_id}
        if atomic_claim:
            filter_q["$or"] = [
                {"status": {"$in": ["PENDING", "OFFERED", "OPEN"]}},
                {"volunteer_id": {"$in": [None, ""]}}
            ]
        res = self.pickup_tasks_col.update_one(
            filter_q,
            {"$set": {"volunteer_id": volunteer_id, "status": "ASSIGNED", "updated_at": now}}
        )
        return res.modified_count > 0 or (not atomic_claim and res.matched_count > 0)

    def update_pickup_status_record(self, task_id: str, status: str) -> bool:
        now = self._now()
        res = self.pickup_tasks_col.update_one(
            {"id": task_id},
            {"$set": {"status": status, "updated_at": now}}
        )
        return res.matched_count > 0

    def create_notification_record(
        self,
        notif_id: str,
        recipient_type: str,
        recipient_id: str,
        message: str,
        channel: str
    ) -> None:
        now = self._now()
        doc = {
            "id": notif_id,
            "recipient_type": recipient_type,
            "recipient_id": recipient_id,
            "message": message,
            "channel": channel,
            "status": "SENT",
            "created_at": now
        }
        self.notifications_col.insert_one(doc)

    def get_notifications_for_recipient(self, recipient_id: str) -> List[Dict[str, Any]]:
        docs = list(self.notifications_col.find({"recipient_id": recipient_id}).sort("created_at", pymongo.DESCENDING))
        return self._clean_docs(docs)

    def get_all_donations(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        query = {}
        if status and status.strip():
            query["status"] = status.strip().upper()
        docs = list(self.donations_col.find(query).sort("created_at", pymongo.DESCENDING))
        return self._clean_docs(docs)

    def get_all_organizations(self) -> List[Dict[str, Any]]:
        docs = list(self.organizations_col.find({}).sort("name", pymongo.ASCENDING))
        return self._clean_docs(docs)

    def get_all_volunteers(self) -> List[Dict[str, Any]]:
        docs = list(self.volunteers_col.find({}).sort("name", pymongo.ASCENDING))
        return self._clean_docs(docs)

    def get_all_pickup_tasks(self) -> List[Dict[str, Any]]:
        tasks = self._clean_docs(list(self.pickup_tasks_col.find({}).sort("created_at", pymongo.DESCENDING)))
        # Enrich with organization_name and volunteer_name for UI display parity
        for task in tasks:
            if task.get("organization_id"):
                org = self.get_organization_record(task["organization_id"])
                task["organization_name"] = org.get("name") if org else None
            if task.get("volunteer_id"):
                vol = self.get_volunteer_record(task["volunteer_id"])
                task["volunteer_name"] = vol.get("name") if vol else None
        return tasks

    def get_all_notifications(self, limit: int = 50) -> List[Dict[str, Any]]:
        docs = list(self.notifications_col.find({}).sort("created_at", pymongo.DESCENDING).limit(limit))
        return self._clean_docs(docs)

    def get_dashboard_stats(self) -> Dict[str, Any]:
        total_donations = self.donations_col.count_documents({})

        # Aggregate total food quantity
        pipeline = [{"$group": {"_id": None, "total_qty": {"$sum": "$quantity"}}}]
        agg_res = list(self.donations_col.aggregate(pipeline))
        total_food_quantity = agg_res[0]["total_qty"] if agg_res else 0.0

        available_donations = self.donations_col.count_documents({"status": "AVAILABLE"})
        active_rescues = self.donations_col.count_documents(
            {"status": {"$in": ["MATCHED", "PICKUP_PENDING", "PICKUP_ASSIGNED", "COLLECTED"]}}
        )
        delivered_rescues = self.donations_col.count_documents({"status": "DELIVERED"})
        total_organizations = self.organizations_col.count_documents({})
        total_volunteers = self.volunteers_col.count_documents({})
        available_volunteers = self.volunteers_col.count_documents({"current_status": "available"})

        # Status distribution
        status_pipeline = [{"$group": {"_id": "$status", "count": {"$sum": 1}}}]
        status_agg = list(self.donations_col.aggregate(status_pipeline))
        status_distribution = {item["_id"]: item["count"] for item in status_agg if item.get("_id")}

        return {
            "total_donations": total_donations,
            "total_food_quantity": round(float(total_food_quantity), 1),
            "available_donations": available_donations,
            "active_rescues": active_rescues,
            "delivered_rescues": delivered_rescues,
            "total_organizations": total_organizations,
            "total_volunteers": total_volunteers,
            "available_volunteers": available_volunteers,
            "status_distribution": status_distribution,
        }

    def reset_database_data(self, wipe_all: bool = False) -> None:
        """Reset donations, pickup tasks, and notifications for demo resets."""
        self.pickup_location_history_col.delete_many({})
        self.reimbursements_col.delete_many({})
        self.qr_codes_col.delete_many({})
        self.pickup_tasks_col.delete_many({})
        self.notifications_col.delete_many({})
        self.donations_col.delete_many({})
        self.audit_events_col.delete_many({})
        self.users_col.delete_many({})
        self.messages_col.delete_many({})
        if wipe_all:
            self.volunteers_col.delete_many({})
            self.organizations_col.delete_many({})
            self.donors_col.delete_many({})

    # Reimbursements (Accounting Ledger)
    def create_reimbursement_record(
        self,
        reimbursement_id: str,
        pickup_task_id: str,
        volunteer_id: str,
        distance_km: float,
        rate_per_km: float,
        transport_mode: str,
        amount: float,
        currency: str = "LKR",
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        now = self._now()
        doc = {
            "id": reimbursement_id,
            "pickup_task_id": pickup_task_id,
            "volunteer_id": volunteer_id,
            "distance_km": float(distance_km),
            "rate_per_km": float(rate_per_km),
            "transport_mode": str(transport_mode),
            "amount": float(amount),
            "currency": str(currency),
            "status": "PENDING",
            "created_at": now,
            "approved_at": None,
            "paid_at": None,
            "notes": notes
        }
        self.reimbursements_col.insert_one(doc)
        return self._clean_doc(doc) or {}

    def get_reimbursement_record(self, reimbursement_id: str) -> Optional[Dict[str, Any]]:
        doc = self.reimbursements_col.find_one({"id": reimbursement_id})
        return self._clean_doc(doc)

    def get_reimbursement_by_pickup_id(self, pickup_task_id: str) -> Optional[Dict[str, Any]]:
        doc = self.reimbursements_col.find_one({"pickup_task_id": pickup_task_id}, sort=[("created_at", pymongo.DESCENDING)])
        return self._clean_doc(doc)

    def get_reimbursements_for_volunteer(self, volunteer_id: str) -> List[Dict[str, Any]]:
        docs = list(self.reimbursements_col.find({"volunteer_id": volunteer_id}).sort("created_at", pymongo.DESCENDING))
        return self._clean_docs(docs)

    def get_all_reimbursements(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        query = {}
        if status and status.strip():
            query["status"] = status.strip().upper()
        reimbs = self._clean_docs(list(self.reimbursements_col.find(query).sort("created_at", pymongo.DESCENDING)))
        for r in reimbs:
            if r.get("volunteer_id"):
                vol = self.get_volunteer_record(r["volunteer_id"])
                r["volunteer_name"] = vol.get("name") if vol else None
        return reimbs

    def update_reimbursement_status_record(
        self,
        reimbursement_id: str,
        status: str,
        notes: Optional[str] = None
    ) -> bool:
        now = self._now()
        norm_status = str(status).strip().upper()
        updates: Dict[str, Any] = {"status": norm_status}
        if norm_status == "APPROVED":
            updates["approved_at"] = now
        elif norm_status == "PAID":
            updates["paid_at"] = now
        if notes is not None:
            updates["notes"] = notes

        res = self.reimbursements_col.update_one(
            {"id": reimbursement_id},
            {"$set": updates}
        )
        return res.matched_count > 0

    # GPS Location History
    def record_pickup_location(
        self,
        location_id: str,
        pickup_task_id: str,
        volunteer_id: str,
        latitude: float,
        longitude: float,
        accuracy_m: Optional[float] = None,
        timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        ts = timestamp or self._now()
        doc = {
            "id": location_id,
            "pickup_task_id": pickup_task_id,
            "volunteer_id": volunteer_id,
            "latitude": float(latitude),
            "longitude": float(longitude),
            "accuracy_m": float(accuracy_m) if accuracy_m is not None else None,
            "timestamp": ts
        }
        self.pickup_location_history_col.insert_one(doc)
        return self._clean_doc(doc) or {}

    def get_latest_pickup_location(self, pickup_task_id: str) -> Optional[Dict[str, Any]]:
        doc = self.pickup_location_history_col.find_one(
            {"pickup_task_id": pickup_task_id},
            sort=[("timestamp", pymongo.DESCENDING)]
        )
        return self._clean_doc(doc)

    def get_pickup_location_history(self, pickup_task_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        docs = list(self.pickup_location_history_col.find(
            {"pickup_task_id": pickup_task_id}
        ).sort("timestamp", pymongo.DESCENDING).limit(limit))
        return self._clean_docs(docs)

    # Volunteer Availability & Location Coordination
    def update_volunteer_availability(
        self,
        volunteer_id: str,
        status: str,
        current_location: Optional[str] = None,
        current_coordinates: Optional[Dict[str, Any]] = None
    ) -> bool:
        norm_status = str(status).strip().upper()
        now = self._now()
        updates: Dict[str, Any] = {
            "availability_status": norm_status,
            "current_status": norm_status.lower()
        }
        if current_location is not None:
            updates["current_location"] = current_location
        if current_coordinates is not None:
            updates["current_coordinates"] = current_coordinates
        if norm_status == "AVAILABLE":
            updates["last_available_at"] = now

        res = self.volunteers_col.update_one(
            {"id": volunteer_id},
            {"$set": updates}
        )
        return res.matched_count > 0

    def get_available_volunteers(
        self,
        service_area: Optional[str] = None,
        min_capacity: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        query = {
            "$or": [
                {"availability_status": "AVAILABLE"},
                {"current_status": "available"}
            ]
        }
        docs = self._clean_docs(list(self.volunteers_col.find(query)))
        vols = []
        for v in docs:
            cap = int(v.get("vehicle_capacity", 25) or 25)
            if min_capacity and cap < min_capacity:
                continue
            if service_area and str(service_area).strip():
                sa = str(v.get("service_area", "")).lower()
                loc = str(v.get("location", "")).lower()
                target_sa = str(service_area).strip().lower()
                if target_sa not in sa and target_sa not in loc and sa not in target_sa:
                    continue
            vols.append(v)
        return vols

    def update_pickup_task_logistics(
        self,
        task_id: str,
        pickup_coordinates: Optional[Dict[str, Any]] = None,
        destination_coordinates: Optional[Dict[str, Any]] = None,
        pickup_distance_km: Optional[float] = None,
        pickup_duration_minutes: Optional[int] = None,
        delivery_distance_km: Optional[float] = None,
        delivery_duration_minutes: Optional[int] = None,
        total_distance_km: Optional[float] = None,
        estimated_transport_cost: Optional[float] = None
    ) -> bool:
        now = self._now()
        updates: Dict[str, Any] = {"updated_at": now}
        if pickup_coordinates is not None:
            updates["pickup_coordinates"] = pickup_coordinates
            updates["pickup_location_confirmed"] = True
        if destination_coordinates is not None:
            updates["destination_coordinates"] = destination_coordinates
            updates["destination_location_confirmed"] = True
        if pickup_distance_km is not None:
            updates["pickup_distance_km"] = float(pickup_distance_km)
        if pickup_duration_minutes is not None:
            updates["pickup_duration_minutes"] = int(pickup_duration_minutes)
        if delivery_distance_km is not None:
            updates["delivery_distance_km"] = float(delivery_distance_km)
        if delivery_duration_minutes is not None:
            updates["delivery_duration_minutes"] = int(delivery_duration_minutes)
        if total_distance_km is not None:
            updates["total_distance_km"] = float(total_distance_km)
        if estimated_transport_cost is not None:
            updates["estimated_transport_cost"] = float(estimated_transport_cost)

        res = self.pickup_tasks_col.update_one(
            {"id": task_id},
            {"$set": updates}
        )
        return res.matched_count > 0

    # Audit Trail Event Logging
    def create_audit_event_record(
        self,
        event_id: str,
        event_type: str,
        actor: str,
        related_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        now = self._now()
        doc = {
            "id": event_id,
            "event_type": event_type,
            "actor": actor,
            "related_id": related_id,
            "metadata": metadata or {},
            "created_at": now
        }
        self.audit_events_col.insert_one(doc)
        return self._clean_doc(doc) or {}

    def get_audit_events_for_task(self, related_id: str) -> List[Dict[str, Any]]:
        docs = list(self.audit_events_col.find({"related_id": related_id}).sort("created_at", pymongo.ASCENDING))
        return self._clean_docs(docs)

    # User Profile & Onboarding Management
    def get_user_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        norm = self._normalize_phone(phone)
        doc = self.users_col.find_one({"phone_number": norm})
        if not doc:
            vol_rec = self.get_volunteer_by_phone(norm)
            if vol_rec and vol_rec.get("name"):
                return {
                    "phone_number": norm,
                    "display_name": vol_rec["name"],
                    "preferred_language": "en",
                    "preferred_response_mode": "text",
                    "user_role": "volunteer",
                    "onboarding_completed": True,
                    "default_location": vol_rec.get("service_area") or vol_rec.get("location"),
                    "created_at": vol_rec.get("created_at") or self._now(),
                    "last_seen_at": vol_rec.get("created_at") or self._now(),
                    "active_draft": {},
                    "conversation_state": {},
                    "metadata": {},
                }
            org_rec = self.get_organization_by_phone(norm)
            if org_rec and org_rec.get("name"):
                return {
                    "phone_number": norm,
                    "display_name": org_rec["name"],
                    "preferred_language": "en",
                    "preferred_response_mode": "text",
                    "user_role": "organization",
                    "onboarding_completed": True,
                    "default_location": org_rec.get("location") or org_rec.get("service_area"),
                    "created_at": org_rec.get("created_at") or self._now(),
                    "last_seen_at": org_rec.get("created_at") or self._now(),
                    "active_draft": {},
                    "conversation_state": {},
                    "metadata": {},
                }
            donor_rec = self.get_donor_by_phone(norm)
            if donor_rec and donor_rec.get("name"):
                return {
                    "phone_number": norm,
                    "display_name": donor_rec["name"],
                    "preferred_language": "en",
                    "preferred_response_mode": "text",
                    "user_role": "donor",
                    "onboarding_completed": True,
                    "default_location": donor_rec.get("location"),
                    "created_at": donor_rec.get("created_at") or self._now(),
                    "last_seen_at": donor_rec.get("created_at") or self._now(),
                    "active_draft": {},
                    "conversation_state": {},
                    "metadata": {},
                }
            return None
        res = self._clean_doc(doc)
        if res:
            res["onboarding_completed"] = bool(res.get("onboarding_completed", False))
            res["preferred_response_mode"] = res.get("preferred_response_mode") or "text"
            if not isinstance(res.get("metadata"), dict):
                res["metadata"] = {}
            if not isinstance(res.get("conversation_state"), dict):
                res["conversation_state"] = {}
            if not isinstance(res.get("active_draft"), dict):
                res["active_draft"] = {}

            # Enrich display_name and user_role from donor/volunteer/org records if fallback
            if not res.get("display_name") or res.get("display_name", "").startswith("User_") or res.get("user_role") in ["unknown", None, ""]:
                vol_rec = self.get_volunteer_by_phone(norm)
                if vol_rec and vol_rec.get("name"):
                    res["display_name"] = vol_rec["name"]
                    res["user_role"] = "volunteer"
                    res["onboarding_completed"] = True
                else:
                    org_rec = self.get_organization_by_phone(norm)
                    if org_rec and org_rec.get("name"):
                        res["display_name"] = org_rec["name"]
                        res["user_role"] = "organization"
                        res["onboarding_completed"] = True
                    else:
                        donor_rec = self.get_donor_by_phone(norm)
                        if donor_rec and donor_rec.get("name"):
                            res["display_name"] = donor_rec["name"]
                            res["user_role"] = "donor"
                            res["onboarding_completed"] = True

        return res

    def create_or_update_user(
        self,
        phone: str,
        display_name: Optional[str] = None,
        preferred_language: str = "en",
        preferred_response_mode: str = "text",
        user_role: str = "unknown",
        onboarding_completed: bool = False,
        default_location: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        norm = self._normalize_phone(phone)
        now = self._now()

        if not display_name or display_name.startswith("User_") or user_role in ["unknown", None, ""]:
            vol_rec = self.get_volunteer_by_phone(norm)
            if vol_rec and vol_rec.get("name"):
                display_name = display_name if (display_name and not display_name.startswith("User_")) else vol_rec["name"]
                user_role = "volunteer"
                onboarding_completed = True
                default_location = default_location or vol_rec.get("service_area") or vol_rec.get("location")
            else:
                org_rec = self.get_organization_by_phone(norm)
                if org_rec and org_rec.get("name"):
                    display_name = display_name if (display_name and not display_name.startswith("User_")) else org_rec["name"]
                    user_role = "organization"
                    onboarding_completed = True
                    default_location = default_location or org_rec.get("location") or org_rec.get("service_area")
                else:
                    donor_rec = self.get_donor_by_phone(norm)
                    if donor_rec and donor_rec.get("name"):
                        display_name = display_name if (display_name and not display_name.startswith("User_")) else donor_rec["name"]
                        user_role = "donor"
                        onboarding_completed = True
                        default_location = default_location or donor_rec.get("location")
        existing = self.users_col.find_one({"phone_number": norm})
        
        if existing:
            updates: Dict[str, Any] = {"last_seen_at": now}
            if display_name:
                updates["display_name"] = display_name
            if preferred_language:
                updates["preferred_language"] = preferred_language
            if preferred_response_mode:
                updates["preferred_response_mode"] = preferred_response_mode
            if user_role and user_role != "unknown":
                updates["user_role"] = user_role
            if onboarding_completed:
                updates["onboarding_completed"] = True
            if default_location:
                updates["default_location"] = default_location
            if metadata:
                updates["metadata"] = metadata
                
            self.users_col.update_one({"phone_number": norm}, {"$set": updates})
        else:
            doc = {
                "phone_number": norm,
                "display_name": display_name or f"User_{norm[-4:]}",
                "preferred_language": preferred_language or "en",
                "preferred_response_mode": preferred_response_mode or "text",
                "user_role": user_role,
                "onboarding_completed": bool(onboarding_completed),
                "default_location": default_location,
                "first_seen_at": now,
                "last_seen_at": now,
                "metadata": metadata or {},
                "conversation_state": {},
                "active_draft": {}
            }
            self.users_col.insert_one(doc)
            
        return self.get_user_by_phone(norm) or {}

    def update_user_profile(
        self,
        phone: str,
        display_name: Optional[str] = None,
        preferred_language: Optional[str] = None,
        preferred_response_mode: Optional[str] = None,
        user_role: Optional[str] = None,
        default_location: Optional[str] = None,
        active_donation_id: Optional[str] = None,
        active_task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        norm = self._normalize_phone(phone)
        now = self._now()
        existing = self.users_col.find_one({"phone_number": norm})
        if not existing:
            doc = {
                "phone_number": norm,
                "display_name": display_name or f"User_{norm[-4:]}",
                "preferred_language": preferred_language or "en",
                "preferred_response_mode": preferred_response_mode or "text",
                "user_role": user_role or "unknown",
                "default_location": default_location,
                "active_donation_id": active_donation_id,
                "active_task_id": active_task_id,
                "conversation_state": {},
                "active_draft": {},
                "onboarding_completed": False,
                "first_seen_at": now,
                "last_seen_at": now,
                "metadata": metadata or {}
            }
            self.users_col.insert_one(doc)
        else:
            updates: Dict[str, Any] = {"last_seen_at": now}
            if display_name is not None:
                updates["display_name"] = display_name
            if preferred_language is not None:
                updates["preferred_language"] = preferred_language
            if preferred_response_mode is not None:
                updates["preferred_response_mode"] = preferred_response_mode
            if user_role is not None:
                updates["user_role"] = user_role
            if default_location is not None:
                updates["default_location"] = default_location
            if active_donation_id is not None:
                updates["active_donation_id"] = active_donation_id
            if active_task_id is not None:
                updates["active_task_id"] = active_task_id
            if metadata is not None:
                updates["metadata"] = metadata
            self.users_col.update_one({"phone_number": norm}, {"$set": updates})
        return self.get_user_by_phone(norm) or {}

    def set_user_language(self, phone: str, language: str) -> bool:
        norm = self._normalize_phone(phone)
        now = self._now()
        res = self.users_col.update_one(
            {"phone_number": norm},
            {"$set": {"preferred_language": language.lower().strip(), "last_seen_at": now}},
            upsert=True
        )
        return True

    def set_user_response_mode(self, phone: str, mode: str) -> bool:
        norm = self._normalize_phone(phone)
        now = self._now()
        clean_mode = "voice" if "voice" in mode.lower() else "text"
        self.users_col.update_one(
            {"phone_number": norm},
            {"$set": {"preferred_response_mode": clean_mode, "last_seen_at": now}},
            upsert=True
        )
        return True

    def set_onboarding_completed(self, phone: str, completed: bool = True) -> bool:
        norm = self._normalize_phone(phone)
        now = self._now()
        res = self.users_col.update_one(
            {"phone_number": norm},
            {"$set": {"onboarding_completed": bool(completed), "last_seen_at": now}}
        )
        return res.matched_count > 0

    def get_user_conversation_state(self, phone: str) -> Dict[str, Any]:
        user = self.get_user_by_phone(phone)
        if user and isinstance(user.get("conversation_state"), dict):
            return user["conversation_state"]
        return {}

    def set_user_conversation_state(self, phone: str, state: Dict[str, Any]) -> bool:
        norm = self._normalize_phone(phone)
        now = self._now()
        self.users_col.update_one(
            {"phone_number": norm},
            {"$set": {"conversation_state": state or {}, "last_seen_at": now}},
            upsert=True
        )
        return True

    def clear_user_conversation_state(self, phone: str) -> bool:
        return self.set_user_conversation_state(phone, {})

    def save_draft_donation(self, phone: str, draft_data: Dict[str, Any]) -> Dict[str, Any]:
        norm = self._normalize_phone(phone)
        user = self.get_user_by_phone(norm)
        existing_draft = (user.get("active_draft") or {}) if user else {}
        if not isinstance(existing_draft, dict):
            existing_draft = {}
        merged = dict(existing_draft)
        for k, v in draft_data.items():
            if v is not None:
                merged[k] = v
        now = self._now()
        self.users_col.update_one(
            {"phone_number": norm},
            {"$set": {"active_draft": merged, "last_seen_at": now}},
            upsert=True
        )
        return merged

    def get_draft_donation(self, phone: str) -> Optional[Dict[str, Any]]:
        user = self.get_user_by_phone(phone)
        if user and user.get("active_draft"):
            draft = user["active_draft"]
            if isinstance(draft, dict) and any(draft.values()):
                return draft
        return None

    def clear_draft_donation(self, phone: str) -> bool:
        norm = self._normalize_phone(phone)
        now = self._now()
        res = self.users_col.update_one(
            {"phone_number": norm},
            {"$set": {"active_draft": {}, "last_seen_at": now}}
        )
        return True

    def get_all_users(self) -> List[Dict[str, Any]]:
        docs = list(self.users_col.find({}).sort("last_seen_at", pymongo.DESCENDING))
        users = []
        seen_phones = set()
        for doc in docs:
            c = self._clean_doc(doc)
            if c:
                norm = c.get("phone_number", "")
                if norm:
                    seen_phones.add(norm)
                c["onboarding_completed"] = bool(c.get("onboarding_completed", False))
                c["preferred_response_mode"] = c.get("preferred_response_mode") or "text"
                if not isinstance(c.get("metadata"), dict):
                    c["metadata"] = {}
                if not isinstance(c.get("conversation_state"), dict):
                    c["conversation_state"] = {}
                if not isinstance(c.get("active_draft"), dict):
                    c["active_draft"] = {}

                # Enrich display_name and user_role
                if not c.get("display_name") or c.get("display_name", "").startswith("User_") or c.get("user_role") in ["unknown", None, ""]:
                    vol_rec = self.get_volunteer_by_phone(norm)
                    if vol_rec and vol_rec.get("name"):
                        c["display_name"] = vol_rec["name"]
                        c["user_role"] = "volunteer"
                        c["onboarding_completed"] = True
                    else:
                        org_rec = self.get_organization_by_phone(norm)
                        if org_rec and org_rec.get("name"):
                            c["display_name"] = org_rec["name"]
                            c["user_role"] = "organization"
                            c["onboarding_completed"] = True
                        else:
                            donor_rec = self.get_donor_by_phone(norm)
                            if donor_rec and donor_rec.get("name"):
                                c["display_name"] = donor_rec["name"]
                                c["user_role"] = "donor"
                                c["onboarding_completed"] = True

                users.append(c)

        # Include registered volunteers not explicitly in users collection
        for vol in self.get_all_volunteers():
            v_phone = self._normalize_phone(vol.get("phone", ""))
            if v_phone and v_phone not in seen_phones:
                users.append({
                    "phone_number": v_phone,
                    "display_name": vol.get("name", "Volunteer"),
                    "preferred_language": "en",
                    "preferred_response_mode": "text",
                    "user_role": "volunteer",
                    "onboarding_completed": True,
                    "default_location": vol.get("service_area") or vol.get("location"),
                    "created_at": vol.get("created_at") or self._now(),
                    "last_seen_at": vol.get("created_at") or self._now(),
                    "active_draft": {},
                    "conversation_state": {},
                    "metadata": {},
                })
                seen_phones.add(v_phone)

        # Include registered organizations not explicitly in users collection
        for org in self.get_all_organizations():
            o_phone = self._normalize_phone(org.get("phone", ""))
            if o_phone and o_phone not in seen_phones:
                users.append({
                    "phone_number": o_phone,
                    "display_name": org.get("name", "Organization"),
                    "preferred_language": "en",
                    "preferred_response_mode": "text",
                    "user_role": "organization",
                    "onboarding_completed": True,
                    "default_location": org.get("location") or org.get("service_area"),
                    "created_at": org.get("created_at") or self._now(),
                    "last_seen_at": org.get("created_at") or self._now(),
                    "active_draft": {},
                    "conversation_state": {},
                    "metadata": {},
                })
                seen_phones.add(o_phone)

        # Include registered donors not explicitly in users collection
        for don in self.get_all_donors():
            d_phone = self._normalize_phone(don.get("phone", ""))
            if d_phone and d_phone not in seen_phones:
                users.append({
                    "phone_number": d_phone,
                    "display_name": don.get("name", "Donor"),
                    "preferred_language": "en",
                    "preferred_response_mode": "text",
                    "user_role": "donor",
                    "onboarding_completed": True,
                    "default_location": don.get("location"),
                    "created_at": don.get("created_at") or self._now(),
                    "last_seen_at": don.get("created_at") or self._now(),
                    "active_draft": {},
                    "conversation_state": {},
                    "metadata": {},
                })
                seen_phones.add(d_phone)

        return users

    def get_all_donors(self) -> List[Dict[str, Any]]:
        docs = list(self.donors_col.find({}).sort("created_at", pymongo.DESCENDING))
        return self._clean_docs(docs)

    def record_message(
        self,
        phone: str,
        sender: str,
        text: str,
        is_voice: bool = False,
        transcript: Optional[str] = None,
        timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        import uuid
        norm = self._normalize_phone(phone)
        msg_id = f"msg-{uuid.uuid4().hex[:8]}"
        ts = timestamp or self._now()
        doc = {
            "id": msg_id,
            "phone_number": norm,
            "sender": sender,
            "message_text": text,
            "is_voice": bool(is_voice),
            "transcript": transcript,
            "timestamp": ts
        }
        self.messages_col.insert_one(doc)

        # Update or create user record
        self.users_col.update_one(
            {"phone_number": norm},
            {
                "$set": {"last_seen_at": ts},
                "$setOnInsert": {
                    "phone_number": norm,
                    "display_name": f"User_{norm[-4:]}",
                    "preferred_language": "en",
                    "preferred_response_mode": "voice" if is_voice else "text",
                    "first_seen_at": ts,
                    "user_role": "unknown",
                    "onboarding_completed": False,
                    "metadata": {},
                    "conversation_state": {},
                    "active_draft": {}
                }
            },
            upsert=True
        )
        return self._clean_doc(doc) or {}

    def get_all_conversations(self) -> List[Dict[str, Any]]:
        # Fetch all registered users
        users = self.get_all_users()
        conversations = []

        for u in users:
            norm = u["phone_number"]
            # Get latest message
            latest_msg_doc = self.messages_col.find_one({"phone_number": norm}, sort=[("timestamp", pymongo.DESCENDING)])
            latest_msg = self._clean_doc(latest_msg_doc) if latest_msg_doc else None
            msg_count = self.messages_col.count_documents({"phone_number": norm})

            disp_name = u.get("display_name") or f"User_{norm[-4:]}"
            u_role = u.get("user_role", "unknown")
            if not disp_name or disp_name.startswith("User_") or u_role in ["unknown", None, ""]:
                donor_rec = self.get_donor_by_phone(norm)
                if donor_rec and donor_rec.get("name"):
                    disp_name = donor_rec["name"]
                    u_role = "donor"
                else:
                    vol_rec = self.get_volunteer_by_phone(norm)
                    if vol_rec and vol_rec.get("name"):
                        disp_name = vol_rec["name"]
                        u_role = "volunteer"
                    else:
                        org_rec = self.get_organization_by_phone(norm)
                        if org_rec and org_rec.get("name"):
                            disp_name = org_rec["name"]
                            u_role = "organization"

            conversations.append({
                "phone_number": norm,
                "display_name": disp_name,
                "user_role": u_role,
                "preferred_language": u.get("preferred_language", "en"),
                "preferred_response_mode": u.get("preferred_response_mode", "text"),
                "message_count": msg_count,
                "last_message": latest_msg.get("message_text", "") if latest_msg else "Conversation initiated",
                "last_message_sender": latest_msg.get("sender", "system") if latest_msg else "system",
                "last_message_is_voice": bool(latest_msg.get("is_voice", False)) if latest_msg else False,
                "last_activity": latest_msg.get("timestamp") if latest_msg else u.get("last_seen_at", self._now()),
                "onboarding_completed": bool(u.get("onboarding_completed", False)),
            })

        # Sort by last_activity descending
        conversations.sort(key=lambda c: str(c.get("last_activity", "")), reverse=True)
        return conversations

    def get_conversation_messages(self, phone: str, limit: int = 100) -> List[Dict[str, Any]]:
        norm = self._normalize_phone(phone)
        docs = list(self.messages_col.find({"phone_number": norm}).sort("timestamp", pymongo.ASCENDING).limit(limit))
        return self._clean_docs(docs)

    def get_all_audit_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        docs = list(self.audit_events_col.find({}).sort("created_at", pymongo.DESCENDING).limit(limit))
        return self._clean_docs(docs)

    def get_transport_settings(self) -> Dict[str, Any]:
        doc = self.system_settings_col.find_one({"setting_key": "transport_cost"})
        if doc and doc.get("setting_value"):
            try:
                val = doc["setting_value"]
                return json.loads(val) if isinstance(val, str) else val
            except Exception:
                pass
        return {
            "base_fare": 100.0,
            "cost_per_km": 80.0,
            "currency": "LKR",
            "rates_by_vehicle": {
                "Motorbike": 50.0,
                "Three-Wheeler": 90.0,
                "Car": 80.0,
                "Van": 120.0,
                "Bicycle": 25.0,
                "Electric Bike": 25.0
            },
            "vehicle_multipliers": {
                "Motorbike": 1.0,
                "Bicycle": 0.6,
                "Car": 1.5,
                "Van": 2.0,
                "Three-Wheeler": 1.2
            }
        }

    def update_transport_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        now = self._now()
        val_json = json.dumps(settings)
        self.system_settings_col.update_one(
            {"setting_key": "transport_cost"},
            {"$set": {"setting_value": val_json, "updated_at": now}},
            upsert=True
        )
        return settings

    # QR Code Handover Verification Persistence
    def create_qr_code_record(
        self,
        qr_id: str,
        task_id: str,
        donation_id: str,
        qr_type: str,
        token: str,
        token_hash: str,
        donor_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        assigned_volunteer_id: Optional[str] = None,
        status: str = "ACTIVE",
        created_at: Optional[str] = None,
        expires_at: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        now = created_at or self._now()
        doc = {
            "id": qr_id,
            "task_id": task_id,
            "donation_id": donation_id,
            "qr_type": qr_type.upper(),
            "token": token,
            "token_hash": token_hash,
            "donor_id": donor_id,
            "organization_id": organization_id,
            "assigned_volunteer_id": assigned_volunteer_id,
            "status": status.upper(),
            "created_at": now,
            "expires_at": expires_at,
            "verified_at": None,
            "verified_by": None,
            "metadata": metadata or {}
        }
        self.qr_codes_col.update_one({"id": qr_id}, {"$set": doc}, upsert=True)
        res = self.qr_codes_col.find_one({"id": qr_id})
        return self._clean_doc(res) or {}

    def get_qr_code_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        doc = self.qr_codes_col.find_one({"token": token.strip()})
        return self._clean_doc(doc)

    def get_qr_codes_for_task(self, task_id: str) -> List[Dict[str, Any]]:
        docs = list(self.qr_codes_col.find({"task_id": task_id}).sort("created_at", pymongo.ASCENDING))
        return self._clean_docs(docs)

    def get_qr_code_by_id(self, qr_id: str) -> Optional[Dict[str, Any]]:
        doc = self.qr_codes_col.find_one({"id": qr_id})
        return self._clean_doc(doc)

    def get_all_qr_codes(
        self,
        status: Optional[str] = None,
        qr_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        q: Dict[str, Any] = {}
        if status:
            q["status"] = status.upper()
        if qr_type:
            q["qr_type"] = qr_type.upper()
        docs = list(self.qr_codes_col.find(q).sort("created_at", pymongo.DESCENDING))
        return self._clean_docs(docs)

    def verify_qr_code_record(
        self,
        token: str,
        volunteer_id: Optional[str] = None,
        gps_coords: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Atomically verify a physical handover QR code and advance task lifecycle status."""
        qr = self.get_qr_code_by_token(token)
        if not qr:
            return {"success": False, "error": "INVALID_TOKEN", "message": "This FoodRescue verification code is not valid."}

        qr_status = qr.get("status", "ACTIVE")
        if qr_status == "VERIFIED":
            return {"success": False, "error": "ALREADY_USED", "message": "This handover QR code has already been verified."}
        if qr_status == "EXPIRED":
            return {"success": False, "error": "EXPIRED", "message": "This QR code has expired. Please request a new verification code."}
        if qr_status != "ACTIVE":
            return {"success": False, "error": "INACTIVE", "message": f"This QR code is {qr_status} and cannot be verified."}

        task_id = qr.get("task_id")
        task = self.get_pickup_task_record(task_id)
        if not task:
            return {"success": False, "error": "TASK_NOT_FOUND", "message": "Associated pickup task not found."}

        donation_id = qr.get("donation_id")
        qr_type = qr.get("qr_type", "PICKUP").upper()
        now = self._now()
        effective_vol_id = volunteer_id or qr.get("assigned_volunteer_id") or task.get("volunteer_id")

        # Authorization: verify volunteer matches assigned volunteer if provided
        assigned_vol_id = task.get("volunteer_id") or qr.get("assigned_volunteer_id")
        if volunteer_id and assigned_vol_id:
            vol_assigned = self.get_volunteer_record(assigned_vol_id) or self.get_volunteer_by_phone(assigned_vol_id)
            v_provided = self.get_volunteer_record(volunteer_id) or self.get_volunteer_by_phone(volunteer_id)
            if vol_assigned and v_provided and vol_assigned.get("id") != v_provided.get("id"):
                return {"success": False, "error": "UNAUTHORIZED_VOLUNTEER", "message": "This QR code belongs to another assigned volunteer."}

        if qr_type == "PICKUP":
            if task.get("status") in ["COLLECTED", "IN_TRANSIT", "DELIVERED", "COMPLETED"]:
                return {"success": False, "error": "ALREADY_COLLECTED", "message": "This donation has already been collected."}

            res = self.qr_codes_col.find_one_and_update(
                {"token": token.strip(), "status": "ACTIVE"},
                {"$set": {"status": "VERIFIED", "verified_at": now, "verified_by": effective_vol_id}},
                return_document=pymongo.ReturnDocument.AFTER
            )
            if not res:
                return {"success": False, "error": "ALREADY_USED", "message": "This handover QR code has already been verified."}

            self.pickup_tasks_col.update_one(
                {"id": task_id},
                {"$set": {"status": "COLLECTED", "delivery_status": "IN_TRANSIT", "food_collected_at": now, "updated_at": now}}
            )
            if donation_id:
                self.donations_col.update_one({"id": donation_id}, {"$set": {"status": "COLLECTED", "updated_at": now}})

            self.create_audit_event_record(
                event_id=f"aud-{now}",
                event_type="PICKUP_QR_VERIFIED",
                actor=str(effective_vol_id or "volunteer"),
                related_id=task_id,
                metadata={"token": token, "gps": gps_coords}
            )

        elif qr_type == "DELIVERY":
            if task.get("status") not in ["COLLECTED", "IN_TRANSIT"]:
                if task.get("status") in ["DELIVERED", "COMPLETED"]:
                    return {"success": False, "error": "ALREADY_DELIVERED", "message": "This delivery has already been completed."}
                return {"success": False, "error": "NOT_YET_COLLECTED", "message": "Cannot verify delivery before the food has been collected from the donor."}

            res = self.qr_codes_col.find_one_and_update(
                {"token": token.strip(), "status": "ACTIVE"},
                {"$set": {"status": "VERIFIED", "verified_at": now, "verified_by": effective_vol_id}},
                return_document=pymongo.ReturnDocument.AFTER
            )
            if not res:
                return {"success": False, "error": "ALREADY_USED", "message": "This handover QR code has already been verified."}

            self.pickup_tasks_col.update_one(
                {"id": task_id},
                {"$set": {"status": "COMPLETED", "delivery_status": "DELIVERED", "food_delivered_at": now, "updated_at": now}}
            )
            if donation_id:
                self.donations_col.update_one({"id": donation_id}, {"$set": {"status": "DELIVERED", "updated_at": now}})

            if effective_vol_id:
                self.volunteers_col.update_one(
                    {"$or": [{"id": effective_vol_id}, {"phone": effective_vol_id}]},
                    {"$set": {"current_status": "available", "availability_status": "AVAILABLE"}}
                )

            self.create_audit_event_record(
                event_id=f"aud-{now}",
                event_type="DELIVERY_QR_VERIFIED",
                actor=str(effective_vol_id or "volunteer"),
                related_id=task_id,
                metadata={"token": token, "gps": gps_coords}
            )

        updated_task = self.get_pickup_task_record(task_id)
        return {
            "success": True,
            "qr_type": qr_type,
            "task_id": task_id,
            "donation_id": donation_id,
            "verified_at": now,
            "verified_by": effective_vol_id,
            "task": updated_task,
        }

    def delete_donation_record(self, donation_id: str) -> bool:
        """Delete a food donation record and its linked tasks/QR codes."""
        try:
            self.qr_codes_col.delete_many({"donation_id": donation_id})
            self.pickup_tasks_col.delete_many({"donation_id": donation_id})
            res = self.donations_col.delete_one({"id": donation_id})
            return res.deleted_count > 0
        except Exception:
            return False

    def delete_donor_record(self, donor_id: str) -> bool:
        """Delete a donor record."""
        try:
            res = self.donors_col.delete_one({"id": donor_id})
            return res.deleted_count > 0
        except Exception:
            return False

    def delete_organization_record(self, org_id: str) -> bool:
        """Delete an organization record."""
        try:
            res = self.organizations_col.delete_one({"id": org_id})
            return res.deleted_count > 0
        except Exception:
            return False

    def delete_volunteer_record(self, volunteer_id: str) -> bool:
        """Delete a volunteer record."""
        try:
            res = self.volunteers_col.delete_one({"id": volunteer_id})
            return res.deleted_count > 0
        except Exception:
            return False

    def delete_user_record(self, phone: str) -> bool:
        """Delete a user profile and active state."""
        try:
            norm = self._normalize_phone(phone)
            res = self.users_col.delete_one({"phone_number": norm})
            return res.deleted_count > 0
        except Exception:
            return False

    def delete_pickup_task_record(self, task_id: str) -> bool:
        """Delete a pickup task record."""
        try:
            self.qr_codes_col.delete_many({"task_id": task_id})
            res = self.pickup_tasks_col.delete_one({"id": task_id})
            return res.deleted_count > 0
        except Exception:
            return False




